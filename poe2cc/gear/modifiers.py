"""Разбор модификаторов предмета в канонические характеристики.

Правила, которые здесь зашиты:

1. Модификатор либо распознан и переведён в канонический ключ, либо помечен
   `UNKNOWN` с сохранением исходного текста. Догадок нет.
2. Складываются только *объявленные* строки. Итоговые значения предмета
   (например, `Armour: 115`, полученное уже с учётом локального процента)
   повторно не суммируются: `14% increased Armour and Energy Shield` — это
   модификатор, который уже вошёл в 115, а не добавка к нему.
3. Если у предмета объявлен итог по характеристике (`declared_totals`), он
   заменяет сумму строк, а не дополняет её. Именно так связанные бонусы
   (руны, `Bonded:`) не считаются дважды.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import stats

NUMBER = r"(?P<value>[+-]?\d+(?:\.\d+)?)"

RESOLVED = "resolved"
UNKNOWN = "unknown"

#: kind модификатора -> человекочитаемый источник
MOD_KINDS = {
    "implicit": "имплисит",
    "explicit": "явный модификатор",
    "rune": "руна / soul core",
    "crafted": "крафт",
    "corrupted": "порча",
    "unknown": "неизвестный источник",
}


def _single(stat: str):
    def build(value: float) -> list[tuple[str, float]]:
        return [(stat, value)]

    return build


def _multi(*stat_keys: str):
    def build(value: float) -> list[tuple[str, float]]:
        return [(key, value) for key in stat_keys]

    return build


def _defence_percent(*stat_keys: str):
    """Локальный процент защиты: он уже учтён в защите предмета."""

    def build(value: float) -> list[tuple[str, float]]:
        return [(key, value) for key in stat_keys]

    return build


#: (регулярное выражение, какие характеристики меняет)
_PATTERNS: tuple[tuple[re.Pattern[str], object], ...] = (
    (re.compile(rf"^{NUMBER} to maximum Life$"), _single("life")),
    (re.compile(rf"^{NUMBER} to maximum Mana$"), _single("mana")),
    (re.compile(rf"^{NUMBER} to maximum Energy Shield$"), _single("energy_shield")),
    (re.compile(rf"^{NUMBER} to Armour$"), _single("armour")),
    (re.compile(rf"^{NUMBER} to Evasion Rating$"), _single("evasion")),
    (re.compile(rf"^{NUMBER} to Stun Threshold$"), _single("stun_threshold")),
    (re.compile(rf"^{NUMBER} to Spirit$"), _single("spirit")),
    (re.compile(rf"^{NUMBER} to Strength$"), _single("strength")),
    (re.compile(rf"^{NUMBER} to Dexterity$"), _single("dexterity")),
    (re.compile(rf"^{NUMBER} to Intelligence$"), _single("intelligence")),
    (re.compile(rf"^{NUMBER} to all Attributes$"), _multi(*stats.EXPANSIONS["all_attributes"])),
    (re.compile(rf"^{NUMBER}% to Fire Resistance$"), _single("fire_resistance")),
    (re.compile(rf"^{NUMBER}% to Cold Resistance$"), _single("cold_resistance")),
    (re.compile(rf"^{NUMBER}% to Lightning Resistance$"), _single("lightning_resistance")),
    (re.compile(rf"^{NUMBER}% to Chaos Resistance$"), _single("chaos_resistance")),
    (
        re.compile(rf"^{NUMBER}% to all Elemental Resistances$"),
        _multi(*stats.EXPANSIONS["all_elemental_resistance"]),
    ),
    (re.compile(rf"^{NUMBER}% increased Movement Speed$"), _single("movement_speed")),
    (re.compile(rf"^{NUMBER}% increased maximum Life$"), _single("life_percent")),
    (re.compile(rf"^{NUMBER}% increased maximum Mana$"), _single("mana_percent")),
    (re.compile(rf"^{NUMBER}% increased maximum Energy Shield$"), _single("energy_shield_percent")),
    (re.compile(rf"^{NUMBER}% increased Armour$"), _single("armour_percent")),
    (re.compile(rf"^{NUMBER}% increased Evasion Rating$"), _single("evasion_percent")),
    (
        re.compile(rf"^{NUMBER}% increased Armour and Energy Shield$"),
        _defence_percent("armour_percent", "energy_shield_percent"),
    ),
    (
        re.compile(rf"^{NUMBER}% increased Evasion and Energy Shield$"),
        _defence_percent("evasion_percent", "energy_shield_percent"),
    ),
    (
        re.compile(rf"^{NUMBER}% increased Armour, Evasion and Energy Shield$"),
        _defence_percent("armour_percent", "evasion_percent", "energy_shield_percent"),
    ),
)

_REDUCED = re.compile(rf"^{NUMBER}% reduced (?P<rest>.+)$")
_INCREASED_GENERIC = re.compile(rf"^{NUMBER}% increased (?P<rest>.+)$")

#: Префиксы, которые PoB2 ставит перед модификаторами рун и чар.
_PREFIXES = (
    ("{enchant}{rune}", "rune"),
    ("{rune}", "rune"),
    ("{enchant}", "crafted"),
    ("{crafted}", "crafted"),
    ("{corrupted}", "corrupted"),
)

BONDED_PREFIX = "Bonded: "


def normalise_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\u00a0", " ")).strip()


@dataclass(frozen=True)
class ParsedMod:
    """Один модификатор предмета в разобранном виде."""

    text: str
    kind: str = "explicit"
    status: str = RESOLVED
    effects: tuple[tuple[str, float], ...] = ()
    note: str | None = None

    @property
    def is_unknown(self) -> bool:
        return self.status == UNKNOWN

    @property
    def stats(self) -> tuple[str, ...]:
        return tuple(stat for stat, _ in self.effects)

    def as_dict(self) -> dict:
        payload = {
            "text": self.text,
            "kind": self.kind,
            "kind_label": MOD_KINDS.get(self.kind, self.kind),
            "status": self.status,
            "effects": [{"stat": stat, "value": value} for stat, value in self.effects],
        }
        if self.note:
            payload["note"] = self.note
        if self.is_unknown:
            payload["raw_text"] = self.text
        return payload


def strip_prefix(text: str) -> tuple[str, str | None]:
    """Снимает служебные префиксы PoB2 и возвращает (текст, kind)."""
    kind: str | None = None
    value = text
    for prefix, prefix_kind in _PREFIXES:
        if value.startswith(prefix):
            value = value[len(prefix) :]
            kind = kind or prefix_kind
            break
    if value.startswith(BONDED_PREFIX):
        value = value[len(BONDED_PREFIX) :]
        kind = kind or "rune"
    return value.strip(), kind


def parse_mod(text: str, kind: str | None = None) -> ParsedMod:
    """Разбирает один модификатор. Неизвестное сохраняется как UNKNOWN."""
    original = normalise_text(text)
    body, prefix_kind = strip_prefix(original)
    resolved_kind = kind or prefix_kind or "explicit"

    for pattern, builder in _PATTERNS:
        match = pattern.match(body)
        if match:
            value = float(match.group("value"))
            return ParsedMod(
                text=original,
                kind=resolved_kind,
                effects=tuple(builder(value)),  # type: ignore[operator]
            )

    reduced = _REDUCED.match(body)
    if reduced:
        value = -float(reduced.group("value"))
        for pattern, builder in _PATTERNS:
            probe = pattern.match(f"{reduced.group('value')}% increased {reduced.group('rest')}")
            if probe:
                return ParsedMod(
                    text=original,
                    kind=resolved_kind,
                    effects=tuple(builder(value)),  # type: ignore[operator]
                    note="сформулировано как reduced, учтено со знаком минус",
                )
        return ParsedMod(
            text=original,
            kind=resolved_kind,
            status=UNKNOWN,
            note="reduced-модификатор не распознан: неизвестно, к какой характеристике он относится",
        )

    increased = _INCREASED_GENERIC.match(body)
    if increased:
        return ParsedMod(
            text=original,
            kind=resolved_kind,
            status=UNKNOWN,
            note=(
                "процентный модификатор не распознан как аддитивный: "
                "такие величины зависят от базы и считаются только движком"
            ),
        )

    return ParsedMod(
        text=original,
        kind=resolved_kind,
        status=UNKNOWN,
        note="модификатор не распознан: сохранён исходный текст",
    )


@dataclass
class StatContribution:
    """Вклад предмета в одну характеристику, с указанием, откуда он взялся."""

    stat: str
    value: float
    basis: str
    lines: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "stat": self.stat,
            "label": stats.label(self.stat),
            "unit": stats.unit(self.stat),
            "value": self.value,
            "basis": self.basis,
            "lines": list(self.lines),
            "notes": list(self.notes),
        }


@dataclass
class DeclaredProfile:
    """Что предмет заявляет о себе — без обращения к движку."""

    contributions: dict[str, StatContribution] = field(default_factory=dict)
    mods: list[ParsedMod] = field(default_factory=list)
    unknown_mods: list[ParsedMod] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def value(self, stat: str) -> float | None:
        contribution = self.contributions.get(stat)
        return contribution.value if contribution else None

    def additive_value(self, stat: str) -> float | None:
        """Значение, только если характеристику можно получить сложением."""
        if not stats.is_additive(stat):
            return None
        return self.value(stat)

    def engine_only_stats(self) -> list[str]:
        return sorted(key for key in self.contributions if not stats.is_additive(key))


BASIS_SUM = "declared_modifiers_sum"
BASIS_TOTAL = "declared_total"


def build_declared_profile(
    mods: list[ParsedMod], declared_totals: dict[str, float] | None = None
) -> DeclaredProfile:
    """Складывает объявленные модификаторы, не задваивая связанные бонусы."""
    profile = DeclaredProfile(mods=list(mods))
    buckets: dict[str, list[tuple[str, float]]] = {}

    for mod in mods:
        if mod.is_unknown:
            profile.unknown_mods.append(mod)
            continue
        for stat, value in mod.effects:
            buckets.setdefault(stat, []).append((mod.text, value))

    for stat, entries in buckets.items():
        total = sum(value for _, value in entries)
        profile.contributions[stat] = StatContribution(
            stat=stat,
            value=total,
            basis=BASIS_SUM,
            lines=[text for text, _ in entries],
        )

    for stat, declared in (declared_totals or {}).items():
        declared_value = float(declared)
        existing = profile.contributions.get(stat)
        if existing is None:
            profile.contributions[stat] = StatContribution(
                stat=stat,
                value=declared_value,
                basis=BASIS_TOTAL,
                notes=[
                    "объявлен итог без построчного текста: связанные бонусы уже включены, "
                    "повторно не суммируются"
                ],
            )
            continue
        if abs(existing.value - declared_value) > 0.01:
            profile.warnings.append(
                f"{stats.label(stat)}: объявленный итог {declared_value:g} не совпал с суммой "
                f"строк {existing.value:g}; использован объявленный итог, строки повторно "
                "не суммируются"
            )
            existing.notes.append(
                f"строки дают {existing.value:g}, объявленный итог {declared_value:g} заменяет их"
            )
            existing.value = declared_value
            existing.basis = BASIS_TOTAL
        else:
            existing.basis = BASIS_TOTAL
            existing.notes.append(
                f"сумма строк совпала с объявленным итогом {declared_value:g}: "
                "связанные бонусы уже внутри, задвоения нет"
            )

    for stat, contribution in profile.contributions.items():
        if not stats.is_additive(stat):
            contribution.notes.append("величина не аддитивна: изменение считает только движок PoB2")

    return profile
