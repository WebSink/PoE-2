"""Модификаторы и объявленный вклад предмета в характеристики."""

from __future__ import annotations

import pytest

from poe2cc.gear import parse_item_json, parse_item_text
from poe2cc.gear.modifiers import build_declared_profile, parse_mod
from poe2cc.gear.stats import EXPANSIONS


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("+83 to maximum Life", (("life", 83.0),)),
        ("+14% to Fire Resistance", (("fire_resistance", 14.0),)),
        ("20% increased Movement Speed", (("movement_speed", 20.0),)),
        ("+15 to Strength", (("strength", 15.0),)),
        ("+12 to Stun Threshold", (("stun_threshold", 12.0),)),
        ("+34 to maximum Energy Shield", (("energy_shield", 34.0),)),
        ("+115 to Armour", (("armour", 115.0),)),
    ],
)
def test_parse_mod_resolves_known_lines(text, expected):
    mod = parse_mod(text)

    assert mod.status == "resolved"
    assert mod.effects == expected


def test_parse_mod_expands_all_attributes():
    mod = parse_mod("+10 to all Attributes")

    assert mod.status == "resolved"
    assert {key for key, _ in mod.effects} == set(EXPANSIONS["all_attributes"])


def test_parse_mod_expands_all_elemental_resistances():
    mod = parse_mod("+12% to all Elemental Resistances")

    assert {key for key, _ in mod.effects} == set(EXPANSIONS["all_elemental_resistance"])


def test_parse_mod_reads_maximum_resistance_as_cap_change():
    """+N% to maximum ... Resistance меняет кап, а не запас сопротивления."""
    mod = parse_mod("+2% to maximum Lightning Resistance")

    assert mod.status == "resolved"
    assert mod.effects == (("max_lightning_resistance", 2.0),)
    assert "lightning_resistance" not in mod.stats


def test_parse_mod_expands_all_maximum_elemental_resistances():
    mod = parse_mod("+1% to all maximum Elemental Resistances")

    assert {key for key, _ in mod.effects} == {
        "max_fire_resistance",
        "max_cold_resistance",
        "max_lightning_resistance",
    }


def test_parse_mod_handles_reduced_as_negative():
    mod = parse_mod("10% reduced Movement Speed")

    assert mod.effects == (("movement_speed", -10.0),)


def test_parse_mod_strips_pob2_tags_and_bonded_prefix():
    rune = parse_mod("{rune}+10 to Strength")
    crafted = parse_mod("{crafted}+20 to maximum Life")
    bonded = parse_mod("Bonded: +15 to maximum Mana")

    assert rune.effects == (("strength", 10.0),)
    assert rune.kind == "rune"
    assert crafted.effects == (("life", 20.0),)
    assert crafted.kind == "crafted"
    assert bonded.effects == (("mana", 15.0),)


def test_parse_mod_marks_unknown_and_keeps_raw_text():
    text = "+5 to Level of all Fire Skills"
    mod = parse_mod(text)

    assert mod.status == "unknown"
    assert mod.effects == ()
    assert mod.text == text
    assert mod.note


def test_declared_totals_override_summed_lines():
    """Связанные бонусы нельзя считать дважды: итог из объявления главнее суммы строк."""
    item = parse_item_json(
        {
            "name": "Linked Boots",
            "mods": [
                {"text": "+55 to maximum Life"},
                {"text": "+28 to maximum Life"},
            ],
            "declared_totals": {"life": 83},
        }
    )

    declared = item.declared
    life = declared.contributions["life"]

    assert life.value == 83.0
    assert life.basis == "declared_total"
    assert declared.value("life") == 83.0
    # строки сохранены для отчёта, но в арифметику не идут второй раз
    assert life.lines == ["+55 to maximum Life", "+28 to maximum Life"]


def test_summed_lines_used_when_no_declared_total():
    item = parse_item_json(
        {
            "name": "Sum Boots",
            "mods": [{"text": "+55 to maximum Life"}, {"text": "+28 to maximum Life"}],
        }
    )

    life = item.declared.contributions["life"]

    assert life.value == 83.0
    assert life.basis == "declared_modifiers_sum"


def test_declared_total_for_absent_line_is_still_counted():
    item = parse_item_json(
        {
            "name": "Total Only",
            "mods": [{"text": "+14% to Fire Resistance"}],
            "declared_totals": {"life": 83},
        }
    )

    assert item.declared.value("life") == 83.0
    assert item.declared.value("fire_resistance") == 14.0


def test_build_declared_profile_ignores_unknown_mods():
    item = parse_item_text(
        """Rarity: RARE
Mystery
Silk Slippers
LevelReq: 36
+5 to Level of all Fire Skills
+20 to maximum Life
""",
        slot="Boots",
    )

    declared = build_declared_profile(item.mods, {})

    assert declared.value("life") == 20.0
    assert len(item.unknown_mods) == 1


def test_mismatch_between_declared_total_and_lines_is_reported():
    """Если сумма строк не равна объявленному итогу, это видно в предупреждениях."""
    item = parse_item_json(
        {
            "name": "Conflicting Boots",
            "mods": [{"text": "+55 to maximum Life"}],
            "declared_totals": {"life": 83},
        }
    )

    declared = item.declared

    assert declared.value("life") == 83.0
    assert declared.contributions["life"].basis == "declared_total"
    assert any("не совпал с суммой" in warning for warning in declared.warnings)
