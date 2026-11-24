"""Требования предмета: уровень, атрибуты и каскад при замене."""

from __future__ import annotations

import pytest

from poe2cc.gear import parse_item_json, parse_item_text
from poe2cc.gear.requirements import (
    NOT_SATISFIED,
    SATISFIED,
    UNKNOWN,
    attribute_evidence_incomplete,
    attributes_after_swap,
    attributes_without_slot_item,
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


# --------------------------------------------------------------------------- #
# Снятая вещь перестаёт действовать (review S5.1.1, пункт 1)
# --------------------------------------------------------------------------- #


def test_attributes_without_slot_item_removes_its_bonus():
    old = _boots(mods=[{"stat": "dexterity", "value": 30}])

    baseline = attributes_without_slot_item(SINKOV, old)

    assert baseline["dexterity"] == pytest.approx(67.0)
    assert baseline["strength"] == pytest.approx(67.0)
    assert baseline["intelligence"] == pytest.approx(46.0)


def test_attributes_without_slot_item_needs_no_item():
    assert attributes_without_slot_item(SINKOV, None) == SINKOV


def test_attributes_after_swap_removes_old_item_bonus():
    old = _boots(mods=[{"stat": "dexterity", "value": 30}])
    new = _boots(name="New Boots", mods=[{"text": "+20 to maximum Life"}])

    after = attributes_after_swap(new, SINKOV, old)

    assert after["dexterity"] == pytest.approx(67.0)


def test_candidate_requirement_is_not_satisfied_by_removed_item_bonus():
    """100 Dex включают +30 от снимаемых сапог: кандидату с ReqDex 80 не хватает 70."""
    old = _boots(mods=[{"stat": "dexterity", "value": 30}])
    candidate = _boots(
        name="Dex Boots",
        attribute_requirements={"strength": 0, "dexterity": 80, "intelligence": 0},
    )
    baseline = attributes_without_slot_item(
        {"strength": 67.0, "dexterity": 100.0, "intelligence": 46.0}, old
    )

    report = check_candidate(candidate, 46, baseline)

    dexterity = next(check for check in report.checks if check.kind == "dexterity")
    assert dexterity.status == NOT_SATISFIED
    assert dexterity.actual == pytest.approx(70.0)
    assert dexterity.required == pytest.approx(80.0)
    assert report.equippable is False


def test_cascade_blocks_when_removed_item_provided_the_attribute():
    """100 Dex = 70 своих + 30 от снимаемой вещи; другим предметам нужно 90."""
    new = _boots(name="No Dex Boots", mods=[{"text": "+20 to maximum Life"}])
    baseline = {"strength": 67.0, "dexterity": 100.0, "intelligence": 46.0}

    report = check_attribute_cascade(
        new,
        baseline,
        {"strength": 41.0, "dexterity": 90.0, "intelligence": 38.0},
        attributes_after={"strength": 67.0, "dexterity": 70.0, "intelligence": 46.0},
    )

    dexterity = next(check for check in report.checks if check.kind == "cascade_dexterity")
    assert dexterity.status == NOT_SATISFIED
    assert dexterity.actual == pytest.approx(70.0)
    assert [check.kind for check in report.blocking] == ["cascade_dexterity"]
    assert any(
        "атрибуты после замены: Сила 67, Ловкость 70, Интеллект 46" in note for note in report.notes
    )


def test_cascade_notes_when_aggregate_may_be_the_candidate_own_requirement():
    candidate = _boots(attribute_requirements={"strength": 0, "dexterity": 90, "intelligence": 0})

    report = check_attribute_cascade(
        candidate,
        SINKOV,
        {"strength": 41.0, "dexterity": 90.0, "intelligence": 38.0},
    )

    assert any("требование самого кандидата" in note for note in report.notes)


def test_declared_mode_cascade_is_marked_as_approximation():
    report = check_attribute_cascade(
        _boots(), SINKOV, {"strength": 1.0, "dexterity": 1.0, "intelligence": 1.0}
    )

    assert any("сложены из объявленных модификаторов" in note for note in report.notes)


# --------------------------------------------------------------------------- #
# Неизвестное состояние без предмета (review S5.1.2, пункт P1)
# --------------------------------------------------------------------------- #


def test_without_attributes_all_attribute_checks_are_unknown():
    """Нет состояния без заменяемого предмета — требования атрибутов не доказаны."""
    report = check_candidate(_boots(), 46, None)

    assert report.equippable is None
    assert {check.kind for check in report.unknown} == {
        "strength",
        "dexterity",
        "intelligence",
    }
    assert all(check.status == UNKNOWN for check in report.unknown)
    assert all(
        "атрибуты без заменяемого предмета не получены" in check.detail for check in report.unknown
    )
    assert any("не проверены" in note for note in report.notes)


def test_without_attributes_the_level_check_still_works():
    unreadable = check_candidate(_boots(required_level=60), 46, None)
    assert unreadable.equippable is not True
    level = next(check for check in unreadable.checks if check.kind == "level")
    assert level.status == NOT_SATISFIED


def test_unknown_attribute_mod_on_removed_item_is_detected():
    item = parse_item_text(
        """Rarity: RARE
Old Boots
Silk Slippers
LevelReq: 36
10% increased Dexterity
""",
        slot="Boots",
    )

    assert attribute_evidence_incomplete(item) is True


def test_complete_item_does_not_look_incomplete():
    assert attribute_evidence_incomplete(_boots()) is False
