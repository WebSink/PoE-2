"""Итоговая оценка предмета с объяснением каждого вклада.

Оценка намеренно детерминированная и «плоская»: это не игровой расчёт, а сумма
вкладов по фиксированным весам. Поэтому в отчёте всегда есть и формула, и список
того, что посчитать не удалось — цифра без объяснения здесь бесполезна.

Веса подобраны так, чтобы 1 пункт сопротивления стоил примерно как 6 здоровья,
а 1% скорости передвижения — как 0.5 здоровья. Это договорённость проекта, а не
игровая механика; менять её можно только вместе с тестами.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import stats

UPGRADE_THRESHOLD = 3.0
DOWNGRADE_THRESHOLD = -3.0

VERDICT_UPGRADE = "upgrade"
VERDICT_SIDEGRADE = "sidegrade"
VERDICT_DOWNGRADE = "downgrade"
VERDICT_NOT_EQUIPPABLE = "not_equippable"
VERDICT_INCONCLUSIVE = "inconclusive"

VERDICT_LABELS = {
    VERDICT_UPGRADE: "улучшение",
    VERDICT_SIDEGRADE: "примерно то же самое",
    VERDICT_DOWNGRADE: "ухудшение",
    VERDICT_NOT_EQUIPPABLE: "надеть нельзя",
    VERDICT_INCONCLUSIVE: "недостаточно данных для вывода",
}

#: Веса для метрик движка: на 1% относительного изменения.
EHP_WEIGHT_PER_PERCENT = 0.5
DPS_WEIGHT_PER_PERCENT = 0.5


@dataclass
class RatingComponent:
    key: str
    label: str
    delta: float
    unit: str
    weight: float
    contribution: float
    basis: str
    note: str | None = None

    def as_dict(self) -> dict:
        payload = {
            "key": self.key,
            "label": self.label,
            "delta": round(self.delta, 4),
            "unit": self.unit,
            "weight": self.weight,
            "contribution": round(self.contribution, 4),
            "basis": self.basis,
        }
        if self.note:
            payload["note"] = self.note
        return payload


@dataclass
class Rating:
    score: float
    verdict: str
    provisional_verdict: str | None
    partial: bool
    components: list[RatingComponent] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    explanation: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "score": round(self.score, 3),
            "verdict": self.verdict,
            "verdict_label": VERDICT_LABELS[self.verdict],
            "provisional_verdict": self.provisional_verdict,
            "partial": self.partial,
            "thresholds": {
                "upgrade": UPGRADE_THRESHOLD,
                "downgrade": DOWNGRADE_THRESHOLD,
            },
            "components": [component.as_dict() for component in self.components],
            "missing": list(self.missing),
            "explanation": list(self.explanation),
        }


def _verdict(score: float) -> str:
    if score >= UPGRADE_THRESHOLD:
        return VERDICT_UPGRADE
    if score <= DOWNGRADE_THRESHOLD:
        return VERDICT_DOWNGRADE
    return VERDICT_SIDEGRADE


def evaluate(
    stat_deltas: dict[str, float],
    *,
    bases: dict[str, str],
    equippable: bool | None,
    missing: list[str],
    ehp_delta_percent: float | None = None,
    dps_delta_percent: float | None = None,
    capped_resistances: dict[str, float] | None = None,
) -> Rating:
    """Считает оценку по изменениям характеристик.

    `stat_deltas` — уже посчитанные изменения (движком или объявленные).
    `bases` — происхождение каждого числа: `engine` или `declared`.
    `capped_resistances` — изменения сопротивлений *после* капа: именно они
    влияют на выживаемость, поэтому в оценку идут они, а не «до капа».
    """
    components: list[RatingComponent] = []
    resistance_keys = set(stats.RESISTANCES)

    for key, delta in sorted(stat_deltas.items()):
        if key in resistance_keys:
            continue
        meta = stats.STATS.get(key)
        if meta is None or meta.weight == 0.0:
            continue
        if abs(delta) < 1e-9:
            continue
        components.append(
            RatingComponent(
                key=key,
                label=meta.label,
                delta=delta,
                unit=meta.unit,
                weight=meta.weight,
                contribution=delta * meta.weight,
                basis=bases.get(key, "declared"),
            )
        )

    for key, delta in sorted((capped_resistances or {}).items()):
        meta = stats.STATS.get(key)
        if meta is None or abs(delta) < 1e-9:
            continue
        components.append(
            RatingComponent(
                key=f"{key}_capped",
                label=f"{meta.label} (после капа)",
                delta=delta,
                unit="percent",
                weight=meta.weight,
                contribution=delta * meta.weight,
                basis=bases.get(key, "declared"),
                note="в оценку идёт изменение после капа: сверх капа сопротивления не работают",
            )
        )

    if ehp_delta_percent is not None and abs(ehp_delta_percent) > 1e-9:
        components.append(
            RatingComponent(
                key="total_ehp",
                label="EHP (относительное изменение)",
                delta=ehp_delta_percent,
                unit="percent",
                weight=EHP_WEIGHT_PER_PERCENT,
                contribution=ehp_delta_percent * EHP_WEIGHT_PER_PERCENT,
                basis="engine",
                note="EHP считается движком под конфигурацией сценария",
            )
        )

    if dps_delta_percent is not None and abs(dps_delta_percent) > 1e-9:
        components.append(
            RatingComponent(
                key="total_dps",
                label="TotalDPS (относительное изменение)",
                delta=dps_delta_percent,
                unit="percent",
                weight=DPS_WEIGHT_PER_PERCENT,
                contribution=dps_delta_percent * DPS_WEIGHT_PER_PERCENT,
                basis="engine",
                note="TotalDPS основного умения; разовый урон и DPS не сравниваются",
            )
        )

    score = sum(component.contribution for component in components)
    partial = bool(missing)

    if equippable is False:
        verdict = VERDICT_NOT_EQUIPPABLE
    elif partial:
        verdict = VERDICT_INCONCLUSIVE
    else:
        verdict = _verdict(score)

    explanation: list[str] = []
    ordered = sorted(components, key=lambda item: abs(item.contribution), reverse=True)
    for component in ordered:
        sign = "+" if component.contribution >= 0 else ""
        explanation.append(
            f"{component.label}: {component.delta:+g} {component.unit}, вес "
            f"{component.weight:g} = {sign}{component.contribution:.2f} ({component.basis})"
        )
    if not explanation:
        explanation.append("изменений по взвешенным характеристикам нет")
    explanation.append(
        f"итог: {score:.2f} при порогах ±{UPGRADE_THRESHOLD:g} -> {VERDICT_LABELS[verdict]}"
    )
    if partial:
        explanation.append(
            "оценка неполная: без движка не посчитаны "
            + ", ".join(stats.label(key) for key in missing)
        )

    return Rating(
        score=score,
        verdict=verdict,
        provisional_verdict=_verdict(score) if partial and equippable is not False else None,
        partial=partial,
        components=components,
        missing=list(missing),
        explanation=explanation,
    )
