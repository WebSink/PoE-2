"""Итоговая оценка: веса, пороги и объяснение."""

from __future__ import annotations

import pytest

from poe2cc.gear.rating import (
    DOWNGRADE_THRESHOLD,
    UPGRADE_THRESHOLD,
    VERDICT_DOWNGRADE,
    VERDICT_INCONCLUSIVE,
    VERDICT_NOT_EQUIPPABLE,
    VERDICT_REQUIREMENTS_BROKEN,
    VERDICT_SIDEGRADE,
    VERDICT_UPGRADE,
    evaluate,
)


def _evaluate(**overrides):
    payload = {
        "stat_deltas": {},
        "bases": {},
        "equippable": True,
        "missing": [],
        "ehp_delta_percent": None,
        "dps_delta_percent": None,
        "capped_resistances": None,
    }
    payload.update(overrides)
    return evaluate(payload.pop("stat_deltas"), **payload)


def test_life_gain_above_threshold_is_upgrade():
    rating = _evaluate(stat_deltas={"life": 20.0}, bases={"life": "engine"})

    assert rating.score == pytest.approx(10.0)
    assert rating.verdict == VERDICT_UPGRADE
    assert rating.provisional_verdict is None
    assert rating.components[0].basis == "engine"


def test_small_change_is_sidegrade():
    rating = _evaluate(stat_deltas={"life": 4.0}, bases={"life": "engine"})

    assert DOWNGRADE_THRESHOLD < rating.score < UPGRADE_THRESHOLD
    assert rating.verdict == VERDICT_SIDEGRADE


def test_loss_above_threshold_is_downgrade():
    rating = _evaluate(stat_deltas={"life": -40.0}, bases={"life": "engine"})

    assert rating.verdict == VERDICT_DOWNGRADE


def test_not_equippable_overrides_positive_score():
    rating = _evaluate(stat_deltas={"life": 500.0}, bases={"life": "engine"}, equippable=False)

    assert rating.score > UPGRADE_THRESHOLD
    assert rating.verdict == VERDICT_NOT_EQUIPPABLE


def test_missing_values_make_verdict_inconclusive():
    rating = _evaluate(
        stat_deltas={"life": 100.0},
        bases={"life": "engine"},
        missing=["armour"],
    )

    assert rating.verdict == VERDICT_INCONCLUSIVE
    assert rating.partial is True
    assert rating.provisional_verdict == VERDICT_UPGRADE


def test_capped_resistance_change_is_weighted():
    rating = _evaluate(
        stat_deltas={},
        bases={"cold_resistance": "engine"},
        capped_resistances={"cold_resistance": -19.0},
    )

    component = rating.components[0]
    assert component.key == "cold_resistance_capped"
    assert component.contribution == pytest.approx(-57.0)
    assert "после капа" in component.label
    assert rating.verdict == VERDICT_DOWNGRADE


def test_resistances_inside_stat_deltas_are_ignored_to_avoid_double_count():
    rating = _evaluate(
        stat_deltas={"cold_resistance": -19.0},
        bases={"cold_resistance": "engine"},
        capped_resistances={"cold_resistance": -19.0},
    )

    assert [component.key for component in rating.components] == ["cold_resistance_capped"]


def test_ehp_and_dps_relative_change_are_counted():
    rating = _evaluate(
        stat_deltas={},
        bases={},
        ehp_delta_percent=10.0,
        dps_delta_percent=-10.0,
    )

    keys = {component.key for component in rating.components}
    assert keys == {"total_ehp", "total_dps"}
    assert rating.score == pytest.approx(0.0)


def test_explanation_contains_formula_and_total():
    rating = _evaluate(stat_deltas={"life": 20.0, "mana": -10.0}, bases={})

    text = "\n".join(rating.explanation)
    assert "Здоровье" in text
    assert "вес" in text
    assert "итог" in text


def test_as_dict_is_serialisable():
    rating = _evaluate(stat_deltas={"life": 20.0}, bases={"life": "engine"})
    payload = rating.as_dict()

    assert payload["verdict"] == VERDICT_UPGRADE
    assert payload["verdict_label"]
    assert payload["thresholds"]["upgrade"] == UPGRADE_THRESHOLD
    assert payload["components"][0]["key"] == "life"


# --------------------------------------------------------------------------- #
# Блокирующий каскад требований (review S5.1.1, пункт 2)
# --------------------------------------------------------------------------- #


def test_broken_requirements_override_a_positive_score():
    rating = _evaluate(
        stat_deltas={"life": 200.0},
        bases={"life": "engine"},
        blocking_requirements=["Ловкость: 70 меньше требуемых 90"],
    )

    assert rating.score > UPGRADE_THRESHOLD
    assert rating.verdict == VERDICT_REQUIREMENTS_BROKEN
    assert rating.provisional_verdict is None
    assert any("нарушает требования" in line for line in rating.explanation)
    assert any("Ловкость" in line for line in rating.explanation)


def test_broken_requirements_beat_a_negative_score_too():
    rating = _evaluate(
        stat_deltas={"life": -200.0},
        bases={"life": "engine"},
        blocking_requirements=["Сила: 30 меньше требуемых 60"],
    )

    assert rating.verdict == VERDICT_REQUIREMENTS_BROKEN


def test_not_equippable_wins_over_broken_requirements():
    """Кандидат сам не надевается — это отдельная причина, а не каскад."""
    rating = _evaluate(
        stat_deltas={"life": 200.0},
        bases={},
        equippable=False,
        blocking_requirements=["Ловкость: 70 меньше требуемых 90"],
    )

    assert rating.verdict == VERDICT_NOT_EQUIPPABLE


def test_without_blocking_requirements_a_positive_score_is_upgrade_again():
    rating = _evaluate(stat_deltas={"life": 200.0}, bases={"life": "engine"})

    assert rating.verdict == VERDICT_UPGRADE
    assert rating.provisional_verdict is None


# --------------------------------------------------------------------------- #
# Неизвестная экипируемость (review S5.1.2, пункт P1)
# --------------------------------------------------------------------------- #


def test_unknown_equippability_never_becomes_upgrade():
    """Балл не превращает недоказанную возможность надеть в рекомендацию."""
    rating = _evaluate(stat_deltas={"life": 500.0}, bases={"life": "engine"}, equippable=None)

    assert rating.score > UPGRADE_THRESHOLD
    assert rating.verdict == VERDICT_INCONCLUSIVE
    assert rating.provisional_verdict is None
    assert any("не проверена" in line or "не доказан" in line for line in rating.explanation)


def test_unknown_equippability_does_not_become_downgrade_either():
    rating = _evaluate(stat_deltas={"life": -500.0}, bases={"life": "engine"}, equippable=None)

    assert rating.verdict == VERDICT_INCONCLUSIVE


def test_unknown_equippability_wins_over_broken_requirements():
    rating = _evaluate(
        stat_deltas={"life": 500.0},
        bases={"life": "engine"},
        equippable=None,
        blocking_requirements=["Ловкость: 70 меньше требуемых 90"],
    )

    assert rating.verdict == VERDICT_INCONCLUSIVE
