"""Проверки требований предмета: уровень, сила, ловкость, интеллект.

Движок PoB2 **не** отказывается надеть предмет с невыполненными требованиями: он
считает статы так, будто предмет надет. Поэтому требования проверяются здесь, до
расчёта, иначе отчёт показал бы «улучшение» от вещи, которую персонаж не может
носить (это проверено вызовом `equip_item_raw` с `LevelReq: 60` на персонаже 46
уровня: движок применил модификатор `+500 to maximum Life`).

Отдельный случай — каскад атрибутов: замена предмета может убрать `+Dexterity`,
после чего требования других предметов или камней перестанут выполняться.
В режиме движка это ловится сравнением атрибутов с `ReqStr`/`ReqDex`/`ReqInt`,
которые PoB2 считает по предметам **и** камням.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .items import Item

SATISFIED = "satisfied"
NOT_SATISFIED = "not_satisfied"
UNKNOWN = "unknown"

_ATTRIBUTE_LABELS = {
    "strength": "Сила",
    "dexterity": "Ловкость",
    "intelligence": "Интеллект",
}

ATTRIBUTES = ("strength", "dexterity", "intelligence")

#: Нераспознанный модификатор, который может менять атрибуты (проценты, условия).
_ATTRIBUTE_MOD_RE = re.compile(r"strength|dexterity|intelligence|attributes", re.IGNORECASE)


@dataclass
class RequirementCheck:
    kind: str
    label: str
    required: float | None
    actual: float | None
    status: str
    detail: str

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "label": self.label,
            "required": self.required,
            "actual": self.actual,
            "status": self.status,
            "detail": self.detail,
        }


@dataclass
class RequirementReport:
    checks: list[RequirementCheck] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def blocking(self) -> list[RequirementCheck]:
        return [check for check in self.checks if check.status == NOT_SATISFIED]

    @property
    def unknown(self) -> list[RequirementCheck]:
        return [check for check in self.checks if check.status == UNKNOWN]

    @property
    def equippable(self) -> bool | None:
        """True / False / None (не хватает данных)."""
        if self.blocking:
            return False
        if self.unknown:
            return None
        return True

    def as_dict(self) -> dict:
        return {
            "equippable": self.equippable,
            "checks": [check.as_dict() for check in self.checks],
            "blocking": [check.kind for check in self.blocking],
            "unknown": [check.kind for check in self.unknown],
            "notes": list(self.notes),
        }


def _compare(kind: str, label: str, required: float | None, actual: float | None, what: str):
    if required is None:
        return RequirementCheck(
            kind=kind,
            label=label,
            required=None,
            actual=actual,
            status=UNKNOWN,
            detail=f"требование не указано в данных предмета: {what}",
        )
    if actual is None:
        return RequirementCheck(
            kind=kind,
            label=label,
            required=required,
            actual=None,
            status=UNKNOWN,
            detail=f"неизвестно фактическое значение: {what}",
        )
    if actual + 1e-9 >= required:
        return RequirementCheck(
            kind=kind,
            label=label,
            required=required,
            actual=actual,
            status=SATISFIED,
            detail=f"{actual:g} из {required:g}",
        )
    return RequirementCheck(
        kind=kind,
        label=label,
        required=required,
        actual=actual,
        status=NOT_SATISFIED,
        detail=f"{actual:g} меньше требуемых {required:g}",
    )


def check_candidate(
    item: Item, character_level: float, attributes: dict[str, float] | None
) -> RequirementReport:
    """Проверяет требования самого кандидата.

    `attributes` — атрибуты персонажа *без* заменяемого предмета и без
    собственных бонусов кандидата: предмет не может удовлетворять свои же
    требования, а снимаемая вещь перестаёт действовать (см.
    `attributes_without_slot_item`). `None` — достоверно получить это состояние
    не удалось: тогда проверка атрибутов остаётся `UNKNOWN`, а не «выполнено».
    """
    report = RequirementReport()
    report.checks.append(
        _compare("level", "Уровень персонажа", item.required_level, character_level, "LevelReq")
    )
    for kind in ("strength", "dexterity", "intelligence"):
        report.checks.append(
            _compare(
                kind,
                _ATTRIBUTE_LABELS[kind],
                item.attribute_requirements.get(kind),
                None if attributes is None else attributes.get(kind),
                "Requires ... Str/Dex/Int"
                if attributes is not None
                else "атрибуты без заменяемого предмета не получены",
            )
        )
    if attributes is None:
        report.notes.append(
            "атрибуты без заменяемого предмета неизвестны: требования атрибутов кандидата "
            "не проверены, вердикт не может быть «улучшение»"
        )
    if all(item.attribute_requirements.get(kind) is None for kind in _ATTRIBUTE_LABELS):
        report.notes.append(
            "требования атрибутов неизвестны: в данных предмета нет строки «Requires ... "
            "Str/Dex/Int»; проверить их можно только полным текстом предмета"
        )
    report.notes.append(
        "собственные бонусы кандидата не учитываются в его же требованиях — как в игре"
    )
    return report


def attribute_evidence_incomplete(item: Item | None) -> bool:
    """Есть ли на предмете источник атрибутов, который не сводится к плоскому бонусу.

    `attributes_without_slot_item` вычитает только распознанные плоские
    `+N to Strength/Dexterity/Intelligence`. Проценты, условия и нераспознанные
    строки так не отнять: если они упоминают атрибуты, доступное значение может
    быть завышено, и проверять по нему требования нельзя.
    """
    if item is None:
        return False
    return any(_ATTRIBUTE_MOD_RE.search(mod.text) for mod in item.unknown_mods)


def attributes_without_slot_item(
    attributes: dict[str, float], item: Item | None
) -> dict[str, float]:
    """Атрибуты персонажа, если снять предмет из заменяемого слота.

    Это приближение: вычитается только объявленный плоский бонус предмета.
    Процентные и условные источники атрибутов так не отнять — поэтому в режиме
    без движка результат помечается как объявленный, а не как измеренный.
    """
    result = dict(attributes)
    if item is None:
        return result
    for kind in ATTRIBUTES:
        delta = item.declared.additive_value(kind)
        if delta:
            result[kind] = result.get(kind, 0.0) - delta
    return result


def attributes_after_swap(
    item: Item, attributes: dict[str, float], removed: Item | None = None
) -> dict[str, float]:
    """Атрибуты персонажа после замены: снимаемая вещь уходит, кандидат приходит."""
    result = attributes_without_slot_item(attributes, removed)
    for kind in ATTRIBUTES:
        delta = item.declared.additive_value(kind)
        if delta:
            result[kind] = result.get(kind, 0.0) + delta
    return result


def check_attribute_cascade(
    item: Item,
    attributes: dict[str, float],
    aggregate_requirements: dict[str, float] | None,
    attributes_after: dict[str, float] | None = None,
    removed: Item | None = None,
) -> RequirementReport:
    """Проверяет, не сломает ли замена требования других предметов и камней.

    `attributes` — атрибуты *без* снимаемой вещи (база для сравнения),
    `attributes_after` — фактические атрибуты после замены (лучше всего — из
    `stats_after` движка). Без движка доступна только объявленная часть, поэтому
    проверка опирается на сумму модификаторов и помечается как приближение.
    """
    report = RequirementReport()
    after = (
        dict(attributes_after)
        if attributes_after is not None
        else attributes_after_swap(item, attributes, removed)
    )
    if after != {kind: attributes.get(kind, 0.0) for kind in ATTRIBUTES}:
        # абсолютные значения однозначны для любого источника базы
        report.notes.append("атрибуты после замены: " + attribute_summary(after))
    if attributes_after is None:
        report.notes.append(
            "атрибуты после замены сложены из объявленных модификаторов: проценты "
            "и условные источники так не учитываются, нужен движок для точного числа"
        )

    if aggregate_requirements is None:
        report.notes.append(
            "агрегированные требования предметов и камней (ReqStr/ReqDex/ReqInt) известны "
            "только движку: каскад атрибутов не проверен"
        )
        for kind in ATTRIBUTES:
            report.checks.append(
                RequirementCheck(
                    kind=f"cascade_{kind}",
                    label=f"{_ATTRIBUTE_LABELS[kind]} (другие предметы и камни)",
                    required=None,
                    actual=after.get(kind),
                    status=UNKNOWN,
                    detail="нужен расчёт движка",
                )
            )
        return report

    for kind in ATTRIBUTES:
        required = aggregate_requirements.get(kind)
        report.checks.append(
            _compare(
                f"cascade_{kind}",
                f"{_ATTRIBUTE_LABELS[kind]} (другие предметы и камни)",
                required,
                after.get(kind),
                "ReqStr/ReqDex/ReqInt движка после замены",
            )
        )
    _note_overlap_with_candidate(report, item, aggregate_requirements)
    if not report.blocking:
        report.notes.append(
            "каскад атрибутов проверен: требования других предметов и камней выполняются"
        )
    return report


def _note_overlap_with_candidate(
    report: RequirementReport, item: Item, aggregate_requirements: dict[str, float]
) -> None:
    """Предупреждает, что ReqX движка может быть требованием самого кандидата.

    Движок отдаёт максимум по всем надетым предметам и камням и не различает,
    чьё именно требование главное. Если объявленное требование кандидата не
    меньше агрегированного, списать возможное нарушение только на «другие
    предметы» нельзя.
    """
    overlaps: list[str] = []
    for kind in ATTRIBUTES:
        own = item.attribute_requirements.get(kind)
        aggregate = aggregate_requirements.get(kind)
        if own is None or aggregate is None:
            continue
        if own + 1e-9 >= aggregate:
            overlaps.append(f"{_ATTRIBUTE_LABELS[kind]} {own:g}")
    if overlaps:
        report.notes.append(
            "агрегированные ReqStr/ReqDex/ReqInt включают требование самого кандидата ("
            + ", ".join(overlaps)
            + "): движок берёт максимум по всем предметам и камням и не различает источники"
        )


def attribute_summary(attributes: dict[str, float]) -> str:
    return ", ".join(
        f"{_ATTRIBUTE_LABELS[kind]} {attributes.get(kind, 0):g}" for kind in ATTRIBUTES
    )
