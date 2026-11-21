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
    item: Item, character_level: float, attributes: dict[str, float]
) -> RequirementReport:
    """Проверяет требования самого кандидата.

    `attributes` — атрибуты персонажа *до* замены и без собственных бонусов
    кандидата: предмет не может удовлетворять свои же требования.
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
                attributes.get(kind),
                "Requires ... Str/Dex/Int",
            )
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


def attributes_after_swap(item: Item, attributes: dict[str, float]) -> dict[str, float]:
    """Атрибуты персонажа после замены: собственные бонусы кандидата теперь считаются."""
    result = dict(attributes)
    for kind in ("strength", "dexterity", "intelligence"):
        delta = item.declared.additive_value(kind)
        if delta:
            result[kind] = result.get(kind, 0) + delta
    return result


def check_attribute_cascade(
    item: Item,
    attributes: dict[str, float],
    aggregate_requirements: dict[str, float] | None,
    attributes_after: dict[str, float] | None = None,
) -> RequirementReport:
    """Проверяет, не сломает ли замена требования других предметов и камней."""
    report = RequirementReport()
    after = dict(attributes_after) if attributes_after else attributes_after_swap(item, attributes)
    deltas = {
        kind: after[kind] - attributes.get(kind, 0)
        for kind in ("strength", "dexterity", "intelligence")
        if abs(after.get(kind, 0) - attributes.get(kind, 0)) > 1e-9
    }
    if deltas:
        report.notes.append(
            "замена меняет атрибуты: "
            + ", ".join(
                f"{_ATTRIBUTE_LABELS[kind]} {delta:+g}" for kind, delta in sorted(deltas.items())
            )
        )

    if aggregate_requirements is None:
        report.notes.append(
            "агрегированные требования предметов и камней (ReqStr/ReqDex/ReqInt) известны "
            "только движку: каскад атрибутов не проверен"
        )
        for kind in ("strength", "dexterity", "intelligence"):
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

    for kind in ("strength", "dexterity", "intelligence"):
        required = aggregate_requirements.get(kind)
        report.checks.append(
            _compare(
                f"cascade_{kind}",
                f"{_ATTRIBUTE_LABELS[kind]} (другие предметы и камни)",
                required,
                after.get(kind),
                "ReqStr/ReqDex/ReqInt движка",
            )
        )
    if not report.blocking:
        report.notes.append(
            "каскад атрибутов проверен: требования других предметов и камней выполняются"
        )
    return report


def attribute_summary(attributes: dict[str, float]) -> str:
    return ", ".join(
        f"{_ATTRIBUTE_LABELS[kind]} {attributes.get(kind, 0):g}"
        for kind in ("strength", "dexterity", "intelligence")
    )
