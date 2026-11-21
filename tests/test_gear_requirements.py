"""Требования предмета: уровень, атрибуты и каскад при замене."""

from __future__ import annotations

import pytest

from poe2cc.gear import parse_item_json, parse_item_text
from poe2cc.gear.requirements import (
    NOT_SATISFIED,
    SATISFIED,
    UNKNOWN,
    attributes_after_swap,
    check_attribute_cascade,
    check_candidate,
)

SINKOV = {
    "strength": 67.0,
    "dexterity": 97.0,
    "intelligence": 46.0,
}


def _boots(**overrides):
    payload = {
        "name": "Test Boots",
        "slot": "Boots",
        "required_level": 45,
        "attribute_requirements": {"strength": 20, "dexterity": 20, "intelligence": 20},
        "mods": [{"text": "+20 to maximum Life"}],
    }
    payload.update(overrides)
    return parse_item_json(payload)


def test_equippable_when_level_and_attributes_fit():
    report = check_candidate(_boots(), 46, SINKOV)

    assert report.equippable is True
    assert report.blocking == []
    assert all(check.status == SATISFIED for check in report.checks)


def test_item_above_character_level_blocks():
    report = check_candidate(_boots(required_level=60), 46, SINKOV)

    assert report.equippable is False
    level_check = next(check for check in report.checks if check.kind == "level")
    assert level_check.status == NOT_SATISFIED
    assert "60" in level_check.detail and "46" in level_check.detail
    assert [check.kind for check in report.blocking] == ["level"]


def test_insufficient_attributes_block():
    report = check_candidate(
        _boots(attribute_requirements={"strength": 120, "dexterity": 20, "intelligence": 20}),
        46,
        SINKOV,
    )

    assert report.equippable is False
    strength = next(check for check in report.checks if check.kind == "strength")
    assert strength.status == NOT_SATISFIED
    assert strength.required == 120
    assert strength.actual == 67
    assert [check.label for check in report.blocking] == ["Сила"]


def test_unknown_requirements_are_not_treated_as_satisfied():
    item = parse_item_text(
        """Rarity: RARE
Mystery Boots
Silk Slippers
+20 to maximum Life
""",
        slot="Boots",
    )
    report = check_candidate(item, 46, SINKOV)

    assert report.equippable is None
    assert report.unknown
    assert "не указано" in report.unknown[0].detail
    assert any("требования атрибутов неизвестны" in note for note in report.notes)


def test_level_equal_to_requirement_is_allowed():
    report = check_candidate(_boots(required_level=46), 46, SINKOV)

    assert report.equippable is True


def test_attributes_after_swap_applies_item_bonus():
    item = _boots(mods=[{"stat": "strength", "value": 15}, {"stat": "life", "value": 20}])

    after = attributes_after_swap(item, SINKOV)

    assert after["strength"] == pytest.approx(82.0)
    assert after["dexterity"] == pytest.approx(97.0)


def test_cascade_detects_broken_requirement_after_swap():
    """Кандидат забирает силу — и требование другого предмета перестаёт выполняться."""
    item = _boots(mods=[{"stat": "strength", "value": -30}, {"stat": "life", "value": 10}])

    report = check_attribute_cascade(
        item,
        SINKOV,
        {"strength": 60, "dexterity": 0, "intelligence": 0},
    )

    assert report.equippable is False
    strength = next(check for check in report.checks if check.kind == "cascade_strength")
    assert strength.status == NOT_SATISFIED
    assert strength.actual == pytest.approx(37.0)
    assert strength.required == pytest.approx(60.0)


def test_cascade_uses_engine_attributes_when_provided():
    item = _boots(mods=[{"stat": "strength", "value": -30}])

    report = check_attribute_cascade(
        item,
        SINKOV,
        {"strength": 60, "dexterity": 0, "intelligence": 0},
        attributes_after={"strength": 64.0, "dexterity": 97.0, "intelligence": 46.0},
    )

    assert report.equippable is True


def test_cascade_without_aggregate_requirements_is_unknown():
    report = check_attribute_cascade(_boots(), SINKOV, None)

    assert report.equippable is None
    assert all(check.status == UNKNOWN for check in report.checks)
    assert any("только движку" in note for note in report.notes)


def test_report_as_dict_is_json_ready():
    report = check_candidate(_boots(required_level=60), 46, SINKOV)
    payload = report.as_dict()

    assert payload["equippable"] is False
    assert payload["blocking"] == ["level"]
    assert {check["kind"] for check in payload["checks"]} == {
        "level",
        "strength",
        "dexterity",
        "intelligence",
    }
