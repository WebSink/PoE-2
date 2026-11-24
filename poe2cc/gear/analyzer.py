"""Детерминированный анализ замены одного предмета.

Порядок действий (он же — контракт модуля):

1. исходный `.xml` читается и хэшируется; работа идёт только с временной копией;
2. кандидат разбирается в нормализованный вид, требования проверяются *до* расчёта;
3. движок загружает копию, получает конфигурацию сценария и baseline-статы;
4. кандидат подставляется через `equip_item_raw`, статы пересчитываются;
5. считается разница, проверяется, что исходный файл не изменился;
6. если движок недоступен, выдаётся честный отчёт только по объявленным свойствам.

Ни одно число не берётся из головы: либо `get_stats` движка, либо объявленный
модификатор предмета, либо арифметика сопротивлений из baseline профиля.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import engine as engine_module
from . import rating as rating_module
from . import requirements as requirements_module
from . import stats
from .items import Item, ItemParseError, items_from_xml, normalise_slot
from .scenario import Character, ProfileContext, Scenario

REPORT_VERSION = "1.0.0"
RESIST_CAP = 75.0

#: Нераспознанная строка, которая может менять максимум сопротивления.
_MAX_RES_MOD_RE = re.compile(r"maximum[^.]*resistance|resistance[^.]*maximum", re.IGNORECASE)

STATUS_COMPUTED = "computed"
STATUS_ENGINE_REQUIRED = "engine_required"
STATUS_UNKNOWN = "unknown"

BASIS_ENGINE = "engine"
BASIS_DECLARED = "declared"

#: Происхождение капа сопротивления.
BASIS_BASELINE = "profile_baseline"
BASIS_REFERENCE = "reference_cap"

ENGINE_STATUS_OK = "ok"
ENGINE_STATUS_SKIPPED = "skipped"
ENGINE_STATUS_UNAVAILABLE = "unavailable"
ENGINE_STATUS_ERROR = "error"

_STAT_FIELDS = sorted(
    set(stats.ENGINE_FIELDS.values()) | set(stats.ENGINE_UNCAPPED_FIELDS.values())
)
_EXTRA_FIELDS = ["TotalDPS", "FullDPS", "TotalEHP", "ReqStr", "ReqDex", "ReqInt"]
ENGINE_FIELDS = _STAT_FIELDS + _EXTRA_FIELDS

_RESISTANCE_ELEMENTS = {
    "fire_resistance": "fire",
    "cold_resistance": "cold",
    "lightning_resistance": "lightning",
    "chaos_resistance": "chaos",
}
_ELEMENT_TO_STAT = {element: stat_key for stat_key, element in _RESISTANCE_ELEMENTS.items()}


class AnalysisError(RuntimeError):
    """Анализ невозможен из-за входных данных."""


# --------------------------------------------------------------------------- #
# Результаты
# --------------------------------------------------------------------------- #
@dataclass
class StatDelta:
    stat: str
    delta: float | None
    status: str
    basis: str
    before: float | None = None
    after: float | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def material(self) -> bool:
        return stats.is_material(self.stat)

    def as_dict(self) -> dict:
        return {
            "stat": self.stat,
            "label": stats.label(self.stat),
            "unit": stats.unit(self.stat),
            "before": None if self.before is None else round(self.before, 4),
            "after": None if self.after is None else round(self.after, 4),
            "delta": None if self.delta is None else round(self.delta, 4),
            "status": self.status,
            "basis": self.basis,
            "material": self.material,
            "notes": list(self.notes),
        }


@dataclass
class MetricDelta:
    key: str
    label: str
    before: float | None
    after: float | None
    unit: str
    basis: str = BASIS_ENGINE
    note: str | None = None

    @property
    def delta(self) -> float | None:
        if self.before is None or self.after is None:
            return None
        return self.after - self.before

    @property
    def delta_percent(self) -> float | None:
        if self.before in (None, 0) or self.after is None:
            return None
        return (self.after - self.before) / self.before * 100.0

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "before": None if self.before is None else round(self.before, 4),
            "after": None if self.after is None else round(self.after, 4),
            "delta": None if self.delta is None else round(self.delta, 4),
            "delta_percent": (None if self.delta_percent is None else round(self.delta_percent, 3)),
            "unit": self.unit,
            "basis": self.basis,
            "note": self.note,
        }


@dataclass
class ResistanceChange:
    element: str
    before_uncapped: float | None
    after_uncapped: float | None
    before_capped: float | None
    after_capped: float | None
    basis: str
    notes: list[str] = field(default_factory=list)
    #: Предел сопротивления для состояния до/после; None — кап неизвестен.
    before_cap: float | None = None
    after_cap: float | None = None
    cap_basis: str | None = None

    @property
    def delta_capped(self) -> float | None:
        if self.before_capped is None or self.after_capped is None:
            return None
        # значение выше собственного капа или кап неизвестен, а значение выше
        # базового — итог не доказан, разницу нельзя показывать как факт
        if self.after_capped > RESIST_CAP + 1e-9 and (
            self.after_cap is None or self.after_capped > self.after_cap + 1e-9
        ):
            return None
        return self.after_capped - self.before_capped

    @property
    def delta_uncapped(self) -> float | None:
        if self.before_uncapped is None or self.after_uncapped is None:
            return None
        return self.after_uncapped - self.before_uncapped

    def as_dict(self) -> dict:
        return {
            "element": self.element,
            "before_uncapped": _round(self.before_uncapped),
            "after_uncapped": _round(self.after_uncapped),
            "before_capped": _round(self.before_capped),
            "after_capped": _round(self.after_capped),
            "delta_uncapped": _round(self.delta_uncapped),
            "delta_capped": _round(self.delta_capped),
            "before_cap": _round(self.before_cap),
            "after_cap": _round(self.after_cap),
            "cap_basis": self.cap_basis,
            "basis": self.basis,
            "notes": list(self.notes),
        }


@dataclass
class XmlIntegrity:
    build_path: str
    sha256_before: str
    sha256_after: str
    unchanged: bool
    temp_copy_used: bool
    temp_copy_removed: bool

    def as_dict(self) -> dict:
        return {
            "build_path": self.build_path,
            "sha256_before": self.sha256_before,
            "sha256_after": self.sha256_after,
            "unchanged": self.unchanged,
            "temp_copy_used": self.temp_copy_used,
            "temp_copy_removed": self.temp_copy_removed,
        }


@dataclass
class EngineState:
    status: str
    info: dict[str, Any] | None = None
    error: str | None = None
    reason: str | None = None
    sanity: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "info": self.info,
            "error": self.error,
            "reason": self.reason,
            "sanity_check": list(self.sanity),
            "note": (
                "числа с basis=engine — это вывод Path of Building - PoE2, "
                "а не расчёт языковой модели"
            ),
        }


@dataclass
class AnalysisReport:
    generated_at: str
    character: Character
    slot: str
    candidate: Item
    current_item: Item | None
    scenario: Scenario
    profile: dict[str, Any]
    requirements: requirements_module.RequirementReport
    cascade: requirements_module.RequirementReport
    deltas: list[StatDelta]
    resistances: list[ResistanceChange]
    metrics: list[MetricDelta]
    lost_stats: dict[str, float]
    gained_stats: dict[str, float]
    lost_defences: dict[str, float]
    gained_defences: dict[str, float]
    lost_mods: list[str]
    gained_mods: list[str]
    rating: rating_module.Rating
    engine: EngineState
    integrity: XmlIntegrity
    limitations: list[str]
    warnings: list[str]
    mode: str

    def as_dict(self) -> dict:
        return {
            "report_version": REPORT_VERSION,
            "generated_at": self.generated_at,
            "mode": self.mode,
            "profile": self.profile,
            "character": self.character.as_dict(),
            "slot": self.slot,
            "scenario": self.scenario.as_dict(),
            "candidate": self.candidate.as_dict(),
            "current_item": self.current_item.as_dict() if self.current_item else None,
            "equippable": self.requirements.equippable,
            "requirements": self.requirements.as_dict(),
            "attribute_cascade": self.cascade.as_dict(),
            "deltas": [delta.as_dict() for delta in self.deltas],
            "resistances": [change.as_dict() for change in self.resistances],
            "metrics": [metric.as_dict() for metric in self.metrics],
            "lost_stats": {key: round(value, 4) for key, value in self.lost_stats.items()},
            "gained_stats": {key: round(value, 4) for key, value in self.gained_stats.items()},
            "lost_defences": {key: round(value, 4) for key, value in self.lost_defences.items()},
            "gained_defences": {
                key: round(value, 4) for key, value in self.gained_defences.items()
            },
            "lost_mods": list(self.lost_mods),
            "gained_mods": list(self.gained_mods),
            "rating": self.rating.as_dict(),
            "engine": self.engine.as_dict(),
            "integrity": self.integrity.as_dict(),
            "limitations": list(self.limitations),
            "warnings": list(self.warnings),
        }

    @property
    def engine_used(self) -> bool:
        return self.engine.status == ENGINE_STATUS_OK


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 4)


@dataclass
class _EngineRun:
    stats_before: dict[str, Any]
    stats_without_item: dict[str, Any] | None
    stats_after: dict[str, Any]
    main_skill: str | None
    items_after: dict[str, Any]
    sanity: list[str]
    info: dict[str, Any]
    unequip_error: str | None = None


@dataclass
class _TempState:
    """Существование временной копии билда.

    `removed` меняется только после проверки, что каталога действительно больше
    нет. Если очистка упала или каталог остался, в отчёте будет `removed=False`,
    а не удобная неправда.
    """

    used: bool = False
    removed: bool = True


def _remove_tree(path: Path) -> bool:
    """Удаляет каталог и возвращает True только при подтверждённом отсутствии."""
    if not path.exists():
        return True
    try:
        shutil.rmtree(path)
    except OSError:
        return not path.exists()
    return not path.exists()


# --------------------------------------------------------------------------- #
# Анализатор
# --------------------------------------------------------------------------- #
class GearAnalyzer:
    """Сравнивает надетый предмет с кандидатом на временной копии билда."""

    def __init__(
        self,
        *,
        engine_command: str | None = None,
        timeout: float = 120.0,
        clock: Callable[[], datetime] | None = None,
        engine_factory: Callable[..., engine_module.McpStdioEngine] | None = None,
    ) -> None:
        self._engine_command = engine_command
        self._timeout = timeout
        self._clock = clock or (lambda: datetime.now(UTC))
        self._engine_factory = engine_factory or engine_module.McpStdioEngine

    # -- публичный вход ------------------------------------------------------ #
    def analyze(
        self,
        *,
        build_path: str | Path,
        candidate: Item,
        slot: str,
        context: ProfileContext,
        use_engine: bool = True,
        engine: engine_module.PobEngine | None = None,
    ) -> AnalysisReport:
        build = Path(build_path)
        if not build.is_file():
            raise AnalysisError(f"билд не найден: {build}")

        canonical_slot = normalise_slot(slot)
        if not canonical_slot:
            raise AnalysisError("не указан слот экипировки")

        build_bytes = build.read_bytes()
        sha_before = hashlib.sha256(build_bytes).hexdigest()
        try:
            build_text = build_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise AnalysisError(f"билд не читается как UTF-8: {exc}") from exc

        try:
            equipped = items_from_xml(build_text)
        except ItemParseError as exc:
            raise AnalysisError(str(exc)) from exc
        current_item = equipped.get(canonical_slot)

        declared_attributes = requirements_module.attributes_without_slot_item(
            dict(context.character.attributes), current_item
        )
        declared_evidence_exact = not requirements_module.attribute_evidence_incomplete(
            current_item
        )
        # предварительная проверка нужна только для решения о запуске движка:
        # она не попадает в отчёт, если движок отработает
        skip_check = requirements_module.check_candidate(
            candidate, context.character.level, declared_attributes
        )

        warnings: list[str] = list(candidate.declared.warnings)
        if candidate.unknown_mods:
            warnings.append(
                f"нераспознанных модификаторов: {len(candidate.unknown_mods)} — они сохранены "
                "как UNKNOWN и не участвуют в арифметике"
            )

        engine_state = EngineState(status=ENGINE_STATUS_SKIPPED)
        engine_run: _EngineRun | None = None
        temp = _TempState()

        reason = self._engine_skip_reason(candidate, skip_check, use_engine)
        if reason:
            engine_state.reason = reason
            engine_state.status = ENGINE_STATUS_SKIPPED
        else:
            try:
                engine_run = self._run_engine(
                    build,
                    candidate,
                    canonical_slot,
                    context.scenario,
                    has_current_item=current_item is not None,
                    temp=temp,
                    engine=engine,
                )
                engine_state.status = ENGINE_STATUS_OK
                engine_state.info = engine_run.info
                engine_state.sanity = engine_run.sanity
            except engine_module.EngineUnavailable as exc:
                engine_state.status = ENGINE_STATUS_UNAVAILABLE
                engine_state.error = str(exc)
                engine_state.reason = "движок PoB2 недоступен"
                warnings.append(f"движок недоступен: {exc}")
            except engine_module.EngineCalculationError as exc:
                engine_state.status = ENGINE_STATUS_ERROR
                engine_state.error = str(exc)
                engine_state.reason = "движок вернул ошибку расчёта"
                warnings.append(f"ошибка расчёта движка: {exc}")
            except engine_module.EngineError as exc:  # pragma: no cover - защитный слой
                engine_state.status = ENGINE_STATUS_ERROR
                engine_state.error = str(exc)
                warnings.append(f"ошибка движка: {exc}")
            except Exception as exc:  # непредвиденная ошибка не должна терять отчёт
                engine_state.status = ENGINE_STATUS_ERROR
                engine_state.error = f"{type(exc).__name__}: {exc}"
                engine_state.reason = "непредвиденная ошибка движка"
                warnings.append(f"непредвиденная ошибка движка: {type(exc).__name__}: {exc}")

        sha_after = hashlib.sha256(build.read_bytes()).hexdigest()
        integrity = XmlIntegrity(
            build_path=str(build),
            sha256_before=sha_before,
            sha256_after=sha_after,
            unchanged=sha_before == sha_after,
            temp_copy_used=temp.used,
            temp_copy_removed=temp.removed,
        )
        if not integrity.unchanged:
            warnings.append(
                "ВНИМАНИЕ: исходный XML изменился во время анализа — результат недействителен"
            )

        attributes_after: dict[str, float] | None = None
        if engine_run is not None:
            # статы после замены уже включают кандидата: это верное состояние для каскада
            attributes_after = self._attributes_from_stats(engine_run.stats_after)
            if engine_run.stats_without_item is None:
                # движок не отдал состояние после снятия: требования не доказаны
                requirements_report = requirements_module.check_candidate(
                    candidate, context.character.level, None
                )
                warnings.append(
                    "движок не дал состояние без заменяемого предмета: требования атрибутов "
                    "кандидата не проверены, вердикт не может быть «улучшение»"
                )
                if engine_run.unequip_error:
                    warnings.append(
                        f"снять предмет в движке не удалось: {engine_run.unequip_error}"
                    )
            else:
                requirements_report = requirements_module.check_candidate(
                    candidate,
                    context.character.level,
                    self._attributes_from_stats(engine_run.stats_without_item),
                )
        else:
            available = declared_attributes if declared_evidence_exact else None
            requirements_report = requirements_module.check_candidate(
                candidate, context.character.level, available
            )
            if not declared_evidence_exact:
                warnings.append(
                    "на снимаемом предмете есть нераспознанные модификаторы атрибутов: "
                    "проверить требования кандидата по объявленным значениям нельзя"
                )

        cascade = requirements_module.check_attribute_cascade(
            candidate,
            declared_attributes,
            self._aggregate_requirements(engine_run),
            attributes_after,
        )

        deltas, resistances = self._compute_deltas(candidate, current_item, context, engine_run)
        metrics = self._compute_metrics(engine_run)
        lost_stats, gained_stats, lost_mods, gained_mods = self._diff_mods(candidate, current_item)
        lost_defences, gained_defences = self._diff_defences(candidate, current_item)

        missing = sorted(
            {delta.stat for delta in deltas if delta.material and delta.status != STATUS_COMPUTED}
            | {
                _ELEMENT_TO_STAT[change.element]
                for change in resistances
                if change.delta_capped is None
            }
        )
        capped_deltas = {
            _ELEMENT_TO_STAT[change.element]: change.delta_capped
            for change in resistances
            if change.delta_capped is not None
        }
        bases = {delta.stat: delta.basis for delta in deltas}
        for change in resistances:
            stat_key = _ELEMENT_TO_STAT.get(change.element)
            if stat_key is not None:
                bases[stat_key] = change.basis
        ehp = next((metric for metric in metrics if metric.key == "total_ehp"), None)
        dps = next((metric for metric in metrics if metric.key == "total_dps"), None)
        rating = rating_module.evaluate(
            {delta.stat: delta.delta or 0.0 for delta in deltas if delta.delta is not None},
            bases=bases,
            equippable=requirements_report.equippable,
            missing=missing,
            ehp_delta_percent=ehp.delta_percent if ehp else None,
            dps_delta_percent=dps.delta_percent if dps else None,
            capped_resistances=capped_deltas,
            blocking_requirements=[check.detail for check in cascade.blocking],
        )

        limitations = self._limitations(candidate, current_item, engine_state, resistances)
        warnings.extend(self._resistance_warnings(resistances))
        if cascade.blocking:
            warnings.append(
                "замена ломает требования других предметов или камней: "
                + "; ".join(check.detail for check in cascade.blocking)
            )

        return AnalysisReport(
            generated_at=self._clock().isoformat(timespec="seconds"),
            character=context.character,
            slot=canonical_slot,
            candidate=candidate,
            current_item=current_item,
            scenario=context.scenario,
            profile=context.as_dict(),
            requirements=requirements_report,
            cascade=cascade,
            deltas=deltas,
            resistances=resistances,
            metrics=metrics,
            lost_stats=lost_stats,
            gained_stats=gained_stats,
            lost_defences=lost_defences,
            gained_defences=gained_defences,
            lost_mods=lost_mods,
            gained_mods=gained_mods,
            rating=rating,
            engine=engine_state,
            integrity=integrity,
            limitations=limitations,
            warnings=warnings,
            mode="engine" if engine_state.status == ENGINE_STATUS_OK else "declared_only",
        )

    # -- движок -------------------------------------------------------------- #
    def _engine_skip_reason(
        self,
        candidate: Item,
        requirements_report: requirements_module.RequirementReport,
        use_engine: bool,
    ) -> str | None:
        if not use_engine:
            return "расчёт движка отключён параметром use_engine"
        if requirements_report.equippable is False:
            blocking = "; ".join(check.detail for check in requirements_report.blocking)
            return f"предмет нельзя надеть, поэтому движок не считает его эффект ({blocking})"
        blockers = candidate.engine_blockers()
        if blockers:
            return "предмет нельзя достоверно воспроизвести в PoB2: " + "; ".join(blockers)
        return None

    def _run_engine(
        self,
        build: Path,
        candidate: Item,
        slot: str,
        scenario: Scenario,
        *,
        has_current_item: bool,
        temp: _TempState,
        engine: engine_module.PobEngine | None,
    ) -> _EngineRun:
        own_engine = engine is None
        active = engine
        workdir = Path(tempfile.mkdtemp(prefix="poe2cc-gear-"))
        temp.used = True
        temp.removed = False
        result: _EngineRun | None = None
        try:
            copy_path = workdir / "build.xml"
            shutil.copy2(build, copy_path)
            if own_engine:
                active = self._engine_factory(self._engine_command, timeout=self._timeout)
                active.start()  # type: ignore[attr-defined]
            assert active is not None
            active.load_build(str(copy_path))
            for key, value in scenario.config.items():
                active.set_config(key, value)

            stats_before = active.get_stats(ENGINE_FIELDS)
            main_skill = _main_skill_name(active.get_skills())
            # состояние без заменяемого предмета — то, чем персонаж реально располагает
            # до надевания кандидата; только по нему можно проверять его требования
            stats_without_item: dict[str, Any] | None = None
            unequip_error: str | None = None
            if has_current_item:
                try:
                    active.unequip_item(slot)
                except engine_module.EngineError as exc:
                    # без состояния «до надевания» требования не доказать,
                    # но остальной расчёт замены остаётся полезным
                    unequip_error = str(exc)
                else:
                    stats_without_item = active.get_stats(ENGINE_FIELDS)
            else:
                stats_without_item = stats_before
            active.equip_item(candidate.item_text_for_engine(), slot)
            stats_after = active.get_stats(ENGINE_FIELDS)
            items_after = active.get_items()
            sanity = active.sanity_check()

            info = (
                active.info.as_dict()
                if hasattr(active, "info")
                else {"transport": "injected engine", "version": "unknown"}
            )
            result = _EngineRun(
                stats_before=stats_before,
                stats_without_item=stats_without_item,
                stats_after=stats_after,
                unequip_error=unequip_error,
                main_skill=main_skill,
                items_after=items_after,
                sanity=sanity,
                info=info,
            )
            return result
        finally:
            try:
                if own_engine and active is not None:
                    active.close()
            finally:
                # удаляем всегда: и при успехе, и при исключении, и при падении движка
                temp.removed = _remove_tree(workdir)

    @staticmethod
    def _attributes_from_stats(engine_stats: dict[str, Any]) -> dict[str, float]:
        return {
            "strength": float(engine_stats.get("Str") or 0),
            "dexterity": float(engine_stats.get("Dex") or 0),
            "intelligence": float(engine_stats.get("Int") or 0),
        }

    @staticmethod
    def _aggregate_requirements(engine_run: _EngineRun | None) -> dict[str, float] | None:
        if engine_run is None:
            return None
        stats_after = engine_run.stats_after
        required = {
            "strength": stats_after.get("ReqStr"),
            "dexterity": stats_after.get("ReqDex"),
            "intelligence": stats_after.get("ReqInt"),
        }
        if any(value is None for value in required.values()):
            return None
        return {key: float(value) for key, value in required.items()}  # type: ignore[arg-type]

    # -- разница ------------------------------------------------------------- #
    def _compute_deltas(
        self,
        candidate: Item,
        current_item: Item | None,
        context: ProfileContext,
        engine_run: _EngineRun | None,
    ) -> tuple[list[StatDelta], list[ResistanceChange]]:
        if engine_run is not None:
            deltas = self._engine_deltas(engine_run)
            resistances = self._engine_resistances(engine_run, context, candidate, current_item)
            return deltas, resistances

        deltas = self._declared_deltas(candidate, current_item)
        resistances = self._projected_resistances(candidate, current_item, context)
        return deltas, resistances

    def _engine_deltas(self, engine_run: _EngineRun) -> list[StatDelta]:
        deltas: list[StatDelta] = []
        before, after = engine_run.stats_before, engine_run.stats_after
        for stat_key, field_name in sorted(stats.ENGINE_FIELDS.items()):
            if stat_key in _RESISTANCE_ELEMENTS:
                # сопротивления живут отдельным блоком: там важны значения до и после капа
                continue
            value_before = before.get(field_name)
            value_after = after.get(field_name)
            if not isinstance(value_before, (int, float)) or not isinstance(
                value_after, (int, float)
            ):
                continue
            scale = 100.0 if stat_key == "movement_speed" else 1.0
            notes = [f"get_stats.{field_name}"]
            if stat_key == "movement_speed":
                notes.append(
                    "MovementSpeedMod — множитель: значение переведено в процентные пункты"
                )
            deltas.append(
                StatDelta(
                    stat=stat_key,
                    before=float(value_before) * scale,
                    after=float(value_after) * scale,
                    delta=(float(value_after) - float(value_before)) * scale,
                    status=STATUS_COMPUTED,
                    basis=BASIS_ENGINE,
                    notes=notes,
                )
            )
        return deltas

    def _engine_resistances(
        self,
        engine_run: _EngineRun,
        context: ProfileContext,
        candidate: Item,
        current_item: Item | None,
    ) -> list[ResistanceChange]:
        """Сопротивления из движка вместе с фактическим капом.

        Отдельного поля «кап сопротивления» движок не отдаёт. Если значение
        упирается в кап, `FireResist` меньше `FireResistTotal` ровно на избыток:
        тогда `FireResist` и есть кап для этого состояния. Если насыщения нет,
        кап после замены — это доказанный кап до замены плюс объявленная разница
        максимального сопротивления между кандидатом и снимаемым предметом. Старый
        профильный кап не подставляется как значение для нового предмета: если
        кандидат меняет максимум, это было бы заведомо неверно, а если разница
        неизвестна — кап остаётся UNKNOWN.
        """
        changes: list[ResistanceChange] = []
        before, after = engine_run.stats_before, engine_run.stats_after
        baseline_max = context.resistance_baseline.maximum if context.resistance_baseline else None
        for stat_key, element in _RESISTANCE_ELEMENTS.items():
            capped_field = stats.ENGINE_FIELDS[stat_key]
            total_field = stats.ENGINE_UNCAPPED_FIELDS[stat_key]
            before_uncapped = _as_float(before.get(total_field))
            after_uncapped = _as_float(after.get(total_field))
            before_capped = _as_float(before.get(capped_field))
            after_capped = _as_float(after.get(capped_field))
            before_cap, before_basis = _resolve_cap(
                before_uncapped,
                before_capped,
                fallback=(baseline_max or {}).get(element),
            )
            # насыщение после замены — единственное прямое измерение капа движком
            measured_after, _ = _resolve_cap(after_uncapped, after_capped, fallback=None)
            after_cap, after_basis, cap_problem = _resolve_after_cap(
                measured=measured_after,
                before_cap=before_cap,
                before_basis=before_basis,
                declared_delta=_max_res_change(element, candidate, current_item),
            )
            notes = [
                f"get_stats.{capped_field} (после капа)",
                f"get_stats.{total_field} (до капа)",
            ]
            if cap_problem:
                notes.append(cap_problem)
            if (
                after_cap is not None
                and after_capped is not None
                and after_capped > after_cap + 1e-9
            ):
                notes.append(
                    f"движок показывает {after_capped:g}% при расчётном капе {after_cap:g}%: "
                    "кап после замены неизвестен"
                )
                after_cap = None
                after_basis = None
            cap_basis = _pick_cap_basis(before_basis, after_basis)
            if (
                before_cap is not None
                and after_cap is not None
                and abs(after_cap - before_cap) > 1e-9
            ):
                notes.append(
                    f"кап меняется модификатором предмета: {before_cap:g}% -> {after_cap:g}%"
                )
            if cap_basis is None:
                notes.append(
                    "кап сопротивления неизвестен: движок не отдаёт его полем, "
                    "а насыщения нет — в профиле нет измеренного капа"
                )
            changes.append(
                ResistanceChange(
                    element=element,
                    before_uncapped=before_uncapped,
                    after_uncapped=after_uncapped,
                    before_capped=before_capped,
                    after_capped=after_capped,
                    before_cap=before_cap,
                    after_cap=after_cap,
                    cap_basis=cap_basis,
                    basis=BASIS_ENGINE,
                    notes=notes,
                )
            )
        return changes

    def _declared_deltas(self, candidate: Item, current_item: Item | None) -> list[StatDelta]:
        old = current_item.declared if current_item else None
        new = candidate.declared
        keys = set(new.contributions) | set(old.contributions if old else {})

        # защита предмета задана итоговыми значениями, а не модификаторами
        defence_keys = set(candidate.defences) | set(current_item.defences if current_item else {})
        for key in defence_keys:
            if key in stats.STATS:
                keys.add(key)

        deltas: list[StatDelta] = []
        for key in sorted(keys):
            if key in _RESISTANCE_ELEMENTS:
                # сопротивления живут отдельным блоком: там значения до и после капа
                continue
            new_value = new.value(key) or 0.0
            old_value = old.value(key) if old else 0.0
            old_value = old_value or 0.0
            delta = new_value - old_value

            if stats.is_additive(key):
                deltas.append(
                    StatDelta(
                        stat=key,
                        before=old_value if old else None,
                        after=new_value,
                        delta=delta,
                        status=STATUS_COMPUTED,
                        basis=BASIS_DECLARED,
                        notes=[
                            "before/after — вклад предмета по объявленным модификаторам; "
                            "итоговое значение персонажа не пересчитано движком"
                        ],
                    )
                )
            else:
                deltas.append(
                    StatDelta(
                        stat=key,
                        before=None,
                        after=None,
                        delta=None,
                        status=STATUS_ENGINE_REQUIRED,
                        basis=BASIS_DECLARED,
                        notes=[
                            "величина не аддитивна (проценты или итоговая защита предмета): "
                            "изменение может посчитать только движок PoB2"
                        ],
                    )
                )
        return deltas

    def _projected_resistances(
        self,
        candidate: Item,
        current_item: Item | None,
        context: ProfileContext,
    ) -> list[ResistanceChange]:
        baseline = context.resistance_baseline
        penalty = float(context.scenario.config.get("resistancePenalty") or 0.0)
        old = current_item.declared if current_item else None
        new = candidate.declared
        maximum = baseline.maximum if baseline is not None else None

        changes: list[ResistanceChange] = []
        for stat_key, element in _RESISTANCE_ELEMENTS.items():
            notes: list[str] = []
            if baseline is None or element not in baseline.uncapped:
                changes.append(
                    ResistanceChange(
                        element=element,
                        before_uncapped=None,
                        after_uncapped=None,
                        before_capped=None,
                        after_capped=None,
                        basis=BASIS_DECLARED,
                        notes=[
                            "в профиле нет calculated.resistance_baseline: "
                            "проекцию сопротивлений построить нельзя"
                        ],
                    )
                )
                continue

            before_uncapped = float(baseline.uncapped[element])
            old_value = (old.value(stat_key) if old else 0.0) or 0.0
            new_value = new.value(stat_key) or 0.0
            after_uncapped = before_uncapped - old_value + new_value

            applied_penalty = 0.0 if element == "chaos" else penalty
            before_total = before_uncapped + applied_penalty
            after_total = after_uncapped + applied_penalty

            measured_cap = (maximum or {}).get(element)
            before_cap = float(measured_cap) if measured_cap is not None else None
            after_cap, cap_basis, cap_problem = _resolve_after_cap(
                measured=None,
                before_cap=before_cap,
                before_basis=BASIS_BASELINE,
                declared_delta=_max_res_change(element, candidate, current_item),
            )
            if before_cap is not None:
                before_capped = min(before_total, before_cap)
                notes.append(
                    f"baseline {before_uncapped:g} (источник {baseline.source_id}), "
                    f"штраф сценария {applied_penalty:g}, кап до замены {before_cap:g}% "
                    f"(профиль, {baseline.captured_at})"
                )
            else:
                before_capped = before_total if before_total <= RESIST_CAP else None
                notes.append(
                    f"baseline {before_uncapped:g} (источник {baseline.source_id}), "
                    f"штраф сценария {applied_penalty:g}"
                )
                notes.append(
                    "измеренного капа сопротивления в профиле нет: "
                    "значения выше 75% без движка не переводятся в итог"
                )
            if cap_problem:
                notes.append(cap_problem)
            if before_cap is not None and after_cap is not None:
                after_capped = min(after_total, after_cap)
                if abs(after_cap - before_cap) > 1e-9:
                    notes.append(
                        f"кап меняется модификатором предмета: {before_cap:g}% -> {after_cap:g}%"
                    )
            else:
                # кап неизвестен; ниже 75% он на итог не влияет, выше — уже влияет
                after_capped = after_total if after_total <= RESIST_CAP else None
            if element == "chaos":
                notes.append("штраф акта не влияет на сопротивление хаосу")
            if before_capped is not None and before_total - before_capped > 1e-9:
                notes.append(f"до замены значение упирается в кап {before_cap:g}%")
            if after_capped is not None and after_total - after_capped > 1e-9:
                notes.append("после замены избыток сопротивления не даёт выживаемости")
            changes.append(
                ResistanceChange(
                    element=element,
                    before_uncapped=before_uncapped,
                    after_uncapped=after_uncapped,
                    before_capped=before_capped,
                    after_capped=after_capped,
                    before_cap=before_cap,
                    after_cap=after_cap,
                    cap_basis=cap_basis,
                    basis=BASIS_DECLARED,
                    notes=notes,
                )
            )
        return changes

    def _compute_metrics(self, engine_run: _EngineRun | None) -> list[MetricDelta]:
        if engine_run is None:
            return []
        before, after = engine_run.stats_before, engine_run.stats_after
        main_skill = engine_run.main_skill or "основное умение"
        metrics = [
            MetricDelta(
                key="total_ehp",
                label="EHP",
                before=_as_float(before.get("TotalEHP")),
                after=_as_float(after.get("TotalEHP")),
                unit="flat",
                note="Effective Hit Pool движка под конфигурацией сценария",
            ),
            MetricDelta(
                key="total_dps",
                label=f"TotalDPS основного умения ({main_skill})",
                before=_as_float(before.get("TotalDPS")),
                after=_as_float(after.get("TotalDPS")),
                unit="dps",
                note="разовый урон и DPS — разные величины, они не сравниваются напрямую",
            ),
            MetricDelta(
                key="full_dps",
                label="FullDPS",
                before=_as_float(before.get("FullDPS")),
                after=_as_float(after.get("FullDPS")),
                unit="dps",
            ),
        ]
        return [
            metric
            for metric in metrics
            if (metric.before is not None or metric.after is not None)
            and not (metric.before == 0 and metric.after == 0)
        ]

    # -- модификаторы: что потеряно, что получено ----------------------------- #
    def _diff_mods(
        self, candidate: Item, current_item: Item | None
    ) -> tuple[dict[str, float], dict[str, float], list[str], list[str]]:
        if current_item is None:
            return {}, {}, [], []

        old = current_item.declared
        new = candidate.declared
        lost_stats: dict[str, float] = {}
        gained_stats: dict[str, float] = {}
        lost_mods: list[str] = []
        gained_mods: list[str] = []

        for stat_key, contribution in old.contributions.items():
            new_value = new.value(stat_key) or 0.0
            difference = contribution.value - new_value
            if difference > 1e-9:
                lost_stats[stat_key] = difference
                lost_mods.extend(
                    contribution.lines
                    or [f"{contribution.value:+g} {stats.label(stat_key)} (объявленный итог)"]
                )

        for stat_key, contribution in new.contributions.items():
            old_value = old.value(stat_key) or 0.0
            difference = contribution.value - old_value
            if difference > 1e-9:
                gained_stats[stat_key] = difference
                gained_mods.extend(
                    contribution.lines
                    or [f"{contribution.value:+g} {stats.label(stat_key)} (объявленный итог)"]
                )

        # локальная защита предмета (Armour/Energy Shield/Evasion в шапке) живёт
        # отдельным блоком `lost_defences`/`gained_defences`: она не суммируется с модификаторами
        return lost_stats, gained_stats, _dedupe(lost_mods), _dedupe(gained_mods)

    def _diff_defences(
        self, candidate: Item, current_item: Item | None
    ) -> tuple[dict[str, float], dict[str, float]]:
        """Локальная защита предмета (броня/уклонение/ES) — отдельно от модификаторов.

        Локальное значение вроде «Energy Shield: 79» и глобальный модификатор
        «+43 to maximum Energy Shield» — разные вещи, поэтому они не суммируются
        в один показатель. Если источник кандидата не гарантирует полноту списка
        защит, отсутствующий ключ — это UNKNOWN, а не ноль: потеря 79 ES не
        выдумывается только потому, что её умолчали.
        """
        if current_item is None:
            return {}, {}
        old = current_item.defences
        new = candidate.defences
        lost: dict[str, float] = {}
        gained: dict[str, float] = {}
        for defence in sorted(set(old) | set(new)):
            before = old.get(defence)
            if before is None:
                before = 0.0 if current_item.defences_complete else None
            after = new.get(defence)
            if after is None:
                after = 0.0 if candidate.defences_complete else None
            if before is None or after is None:
                continue
            difference = after - before
            if difference < -1e-9:
                lost[defence] = -difference
            elif difference > 1e-9:
                gained[defence] = difference
        return lost, gained

    # -- текст отчёта -------------------------------------------------------- #
    def _limitations(
        self,
        candidate: Item,
        current_item: Item | None,
        engine_state: EngineState,
        resistances: list[ResistanceChange],
    ) -> list[str]:
        limitations: list[str] = []
        if engine_state.status != ENGINE_STATUS_OK:
            reason = engine_state.reason or "причина не указана"
            limitations.append("расчёт движка не выполнялся: " + reason)
            blockers = candidate.engine_blockers()
            if blockers and not all(blocker in reason for blocker in blockers):
                limitations.append(
                    "чтобы включить движок, нужен полный текст предмета: " + "; ".join(blockers)
                )
            limitations.append(
                "броня, уклонение, энергетический щит, скорость передвижения, DPS и EHP "
                "без движка не считаются: их нельзя получить сложением модификаторов"
            )
        else:
            limitations.append(
                "PoB2 не проверяет требования предмета: проверка уровня и атрибутов "
                "выполнена анализатором до расчёта"
            )
            limitations.append(
                "числа движка действительны только для конфигурации сценария; "
                "другая конфигурация — другие числа"
            )
            limitations.append(
                "DPS показан только для основного умения (TotalDPS/FullDPS): групповой DPS "
                "требует отдельного прохода с set_main_skill по каждой группе камней"
            )
        if current_item is None:
            limitations.append("в указанном слоте нет предмета: сравнение идёт с пустым слотом")
        elif not current_item.engine_ready:
            limitations.append(
                "текущий предмет прочитан из XML и не имеет полного текста для движка"
            )
        if candidate.unknown_mods:
            limitations.append(
                "нераспознанные модификаторы не влияют на числа отчёта, но могут менять "
                "реальный результат в игре"
            )
        missing_defences = sorted(
            defence
            for defence in (current_item.defences if current_item else {})
            # для полного списка защит отсутствие ключа — это ноль, а не пробел в данных
            if defence not in candidate.defences and not candidate.defences_complete
        )
        if missing_defences:
            limitations.append(
                "в данных кандидата не указана защита предмета "
                + ", ".join(missing_defences)
                + ": изменение этого показателя остаётся неизвестным"
            )
        limitations.append(
            "рыночная цена и доступность объявления не проверяются: торговых интеграций нет"
        )
        unknown_caps = sorted(change.element for change in resistances if change.cap_basis is None)
        if unknown_caps:
            limitations.append(
                "кап сопротивления неизвестен для стихий "
                + ", ".join(unknown_caps)
                + ": значения выше 75% без движка не переводятся в итог, пока в профиле "
                "нет измеренного calculated.resistance_baseline.maximum"
            )
        return limitations

    @staticmethod
    def _resistance_warnings(changes: list[ResistanceChange]) -> list[str]:
        warnings: list[str] = []
        for change in changes:
            delta_uncapped = change.delta_uncapped
            delta_capped = change.delta_capped
            if delta_uncapped is None or delta_capped is None:
                continue
            if abs(delta_uncapped) > 1e-9 and abs(delta_capped) < 1e-9:
                cap = f"{change.before_cap:g}%" if change.before_cap is not None else "неизвестен"
                warnings.append(
                    f"{change.element}: изменение {delta_uncapped:+g}% не влияет на итог — "
                    f"сопротивление уже на капе (кап {cap})"
                )
            elif delta_capped < -1e-9:
                warnings.append(
                    f"{change.element}: итоговое сопротивление падает на {abs(delta_capped):g}% "
                    f"(до {change.after_capped:g}%)"
                )
        return warnings


def _as_float(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _max_res_unknown(item: Item | None, element: str) -> bool:
    """Может ли нераспознанная строка предмета менять максимум этой стихии."""
    if item is None:
        return False
    for mod in item.unknown_mods:
        text = mod.text.lower()
        if not _MAX_RES_MOD_RE.search(text):
            continue
        if element in text or "all" in text:
            return True
    return False


def _max_res_change(element: str, candidate: Item, current_item: Item | None) -> float | None:
    """Разница максимума сопротивления между кандидатом и снимаемым предметом.

    `None` — разницу определить нельзя: на одном из предметов есть нераспознанная
    (в том числе условная) строка про максимум сопротивления. Ноль возвращается
    только когда таких строк нет и оба объявленных значения известны.
    """
    if _max_res_unknown(candidate, element) or _max_res_unknown(current_item, element):
        return None
    key = stats.MAX_RESISTANCES[element]
    old = (current_item.declared.value(key) if current_item else 0.0) or 0.0
    new = candidate.declared.value(key) or 0.0
    return new - old


def _resolve_after_cap(
    *,
    measured: float | None,
    before_cap: float | None,
    before_basis: str | None,
    declared_delta: float | None,
) -> tuple[float | None, str | None, str | None]:
    """Кап после замены: насыщение движка > кап до замены + разница > UNKNOWN.

    Возвращает `(кап, base, причина_неизвестности)`. Старый профильный кап не
    используется как окончательное значение, если кандидат меняет максимум:
    иначе отчёт показал бы сопротивление выше собственного капа.
    """
    if measured is not None:
        return measured, BASIS_ENGINE, None
    if before_cap is None:
        return (
            None,
            None,
            (
                "кап после замены неизвестен: кап до замены тоже не измерен, "
                "а насыщения в движке нет"
            ),
        )
    if declared_delta is None:
        return (
            None,
            None,
            (
                "кап после замены неизвестен: в модификаторах есть нераспознанная или "
                "условная строка про максимум сопротивления — разницу определить нельзя"
            ),
        )
    after = before_cap + declared_delta
    if after < RESIST_CAP - 1e-9:
        return (
            None,
            None,
            (
                f"кап после замены неизвестен: расчёт даёт {after:g}% ниже базового "
                f"{RESIST_CAP:g}% — данные о максимуме до замены не согласуются"
            ),
        )
    basis = BASIS_DECLARED if abs(declared_delta) > 1e-9 else before_basis
    return after, basis, None


def _resolve_cap(
    total: float | None, capped: float | None, fallback: float | None
) -> tuple[float | None, str | None]:
    """Предел сопротивления из насыщения движка, иначе из измеренного профиля.

    Насыщение — единственный случай, когда движок прямо показывает кап: если
    `*Resist` меньше `*ResistTotal`, разница — избыток сверх капа, значит
    `*Resist` ровно равен капу.
    """
    if total is not None and capped is not None and total - capped > 1e-9:
        return capped, BASIS_ENGINE
    if fallback is not None:
        return float(fallback), BASIS_BASELINE
    return None, None


def _pick_cap_basis(before: str | None, after: str | None) -> str | None:
    """Самое сильное свидетельство о капе: движок > модификатор > профиль."""
    for basis in (BASIS_ENGINE, BASIS_DECLARED, BASIS_BASELINE):
        if basis in (before, after):
            return basis
    return before or after


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _main_skill_name(skills: dict[str, Any]) -> str | None:
    for group in skills.get("socketGroups") or []:
        if not group.get("isMainSkill"):
            continue
        gems = group.get("gems") or []
        if gems:
            return gems[0].get("nameSpec")
    return None
