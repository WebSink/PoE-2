"""Целостность профиля персонажа: схема, провенанс, арифметика.

Тесты делятся на две группы:
* реальный профиль `data/characters/sinkov.json` проходит все проверки;
* каждая проверка действительно ловит порчу данных (негативные кейсы).
"""

from __future__ import annotations

import json

PROFILE = "data/characters/sinkov.json"


# --------------------------------------------------------------------------- #
# Реальный профиль
# --------------------------------------------------------------------------- #
def test_real_profile_has_no_errors(validator, schema, profile):
    errors = validator.validate_schema(profile, schema)
    for check in (
        validator.check_provenance,
        validator.check_no_calculated_outside_scenarios,
        validator.check_resistance_baseline,
        validator.check_resistances,
        validator.check_spirit,
        validator.check_scenario_skills,
        validator.check_equipment,
    ):
        errors.extend(check(profile))
    errors.extend(validator.check_secrets_and_xml(profile, PROFILE))
    assert errors == []


def test_cli_reports_success(validator):
    assert validator.main([]) == 0


def test_every_scenario_is_fully_documented(profile):
    scenarios = profile["calculated"]["scenarios"]
    assert len(scenarios) >= 2
    for sc in scenarios:
        assert sc["captured_at"], sc["id"]
        assert sc["config_rationale"], sc["id"]
        # обоснование покрывает каждый ключ конфигурации
        assert set(sc["config"]) == set(sc["config_rationale"]), sc["id"]
        assert sc["source_id"] in {s["id"] for s in profile["sources"]}


def test_scenarios_do_not_mix_resistance_penalties(profile):
    penalties = {sc["config"]["resistancePenalty"] for sc in profile["calculated"]["scenarios"]}
    assert penalties == {-20, -60}
    for sc in profile["calculated"]["scenarios"]:
        # каждое сопротивление сценария посчитано при своём штрафе
        expected_fire = min(
            profile["calculated"]["resistance_baseline"]["uncapped"]["fire"]
            + sc["config"]["resistancePenalty"],
            75,
        )
        assert sc["defence"]["resistances"]["fire"] == expected_fire, sc["id"]


def test_history_snapshot_preserved(validator):
    assert validator.check_history() == []


# --------------------------------------------------------------------------- #
# Негативные кейсы: проверки обязаны ловить порчу
# --------------------------------------------------------------------------- #
def test_schema_rejects_missing_required_field(validator, schema, profile_copy):
    del profile_copy["imported"]["equipment"]
    errors = validator.validate_schema(profile_copy, schema)
    assert any("equipment" in e for e in errors)


def test_schema_rejects_unknown_top_level_field(validator, schema, profile_copy):
    profile_copy["dps"] = 123
    errors = validator.validate_schema(profile_copy, schema)
    assert any("dps" in e for e in errors)


def test_schema_rejects_bad_enum(validator, schema, profile_copy):
    profile_copy["imported"]["equipment"][0]["rarity"] = "MYTHIC"
    errors = validator.validate_schema(profile_copy, schema)
    assert any("rarity" in e for e in errors)


def test_provenance_catches_dangling_source(validator, profile_copy):
    profile_copy["character"]["source_id"] = "no-such-source"
    errors = validator.check_provenance(profile_copy)
    assert any("no-such-source" in e for e in errors)


def test_provenance_requires_rationale_for_every_config_key(validator, profile_copy):
    sc = profile_copy["calculated"]["scenarios"][0]
    sc["config_rationale"].pop("enemyArmour")
    errors = validator.check_provenance(profile_copy)
    assert any("enemyArmour" in e for e in errors)


def test_resistance_check_catches_wrong_value(validator, profile_copy):
    profile_copy["calculated"]["scenarios"][0]["defence"]["resistances"]["cold"] = 75
    errors = validator.check_resistances(profile_copy)
    assert any("cold" in e for e in errors)


def test_resistance_check_catches_mixed_penalty(validator, profile_copy):
    """Сопротивления, посчитанные при -60, не должны проходить в сценарии -20."""
    sc = profile_copy["calculated"]["scenarios"][0]
    assert sc["config"]["resistancePenalty"] == -20
    sc["defence"]["resistances"] = {"fire": 49, "cold": 6, "lightning": -5, "chaos": 0}
    errors = validator.check_resistances(profile_copy)
    assert len(errors) >= 3


def test_spirit_check_catches_broken_arithmetic(validator, profile_copy):
    spirit = profile_copy["imported"]["spirit_reservations"]
    spirit["free"] = 0
    errors = validator.check_spirit(profile_copy)
    assert any("free" in e for e in errors)


def test_spirit_check_catches_wrong_entry_sum(validator, profile_copy):
    spirit = profile_copy["imported"]["spirit_reservations"]
    spirit["entries"][0]["spirit"] = 10
    errors = validator.check_spirit(profile_copy)
    assert any("сумма резервов" in e for e in errors)


def test_spirit_check_catches_wrong_fits_flag(validator, profile_copy):
    spirit = profile_copy["imported"]["spirit_reservations"]
    for combo in spirit["simultaneous_combinations"]:
        if combo["spirit_used"] > spirit["maximum"]:
            combo["fits"] = True
            break
    errors = validator.check_spirit(profile_copy)
    assert any("fits" in e for e in errors)


def test_spirit_check_catches_unknown_ability(validator, profile_copy):
    spirit = profile_copy["imported"]["spirit_reservations"]
    spirit["simultaneous_combinations"][0]["combination"].append("Herald of Doom")
    errors = validator.check_spirit(profile_copy)
    assert any("Herald of Doom" in e for e in errors)


def test_calculated_outside_scenario_is_rejected(validator, profile_copy):
    profile_copy["ehp"] = 1216
    errors = validator.check_no_calculated_outside_scenarios(profile_copy)
    assert errors


def test_secret_key_is_rejected(validator, profile_copy):
    profile_copy["sources"][1]["refresh_token"] = "abc"
    errors = validator.check_secrets_and_xml(profile_copy, PROFILE)
    assert any("refresh_token" in e for e in errors)


def test_long_hex_blob_is_rejected(validator, profile_copy):
    profile_copy["character"]["progress"] = "a" * 40
    errors = validator.check_secrets_and_xml(profile_copy, PROFILE)
    assert any("hex" in e for e in errors)


def test_artifact_sha256_is_allowed(validator, profile):
    sha = profile["sources"][1]["artifact_sha256"]
    assert len(sha) == 64
    assert validator.check_secrets_and_xml(profile, PROFILE) == []


def test_embedded_xml_is_rejected(validator, profile_copy):
    profile_copy["imported"]["equipment"][0]["mods"].append("Rarity: RARE")
    errors = validator.check_secrets_and_xml(profile_copy, PROFILE)
    assert any("XML" in e for e in errors)


def test_scenario_skill_unknown_group_is_rejected(validator, profile_copy):
    profile_copy["calculated"]["scenarios"][0]["skills"][0]["group"] = 99
    errors = validator.check_scenario_skills(profile_copy)
    assert any("99" in e for e in errors)


def test_duplicate_equipment_slot_is_rejected(validator, profile_copy):
    equipment = profile_copy["imported"]["equipment"]
    equipment.append(dict(equipment[0]))
    errors = validator.check_equipment(profile_copy)
    assert any("слоты" in e for e in errors)


def test_observed_level_not_above_current(profile):
    """Наблюдения в игре старше импорта и не должны его опережать."""
    assert profile["observed"]["level"] <= profile["character"]["level"]
    assert profile["observed"]["superseded_by"] is not None


def test_profile_is_valid_json_utf8(validator):
    raw = (validator.ROOT / PROFILE).read_bytes()
    text = raw.decode("utf-8")
    assert json.loads(text)["schema_version"] == "2.1.0"


# --------------------------------------------------------------------------- #
# Провенанс uncapped-сопротивлений (схема 2.1.0)
# --------------------------------------------------------------------------- #
def test_resistance_baseline_is_engine_provenance(validator, profile):
    """uncapped-сопротивления — расчёт движка, а не импорт из аккаунта."""
    assert "uncapped_resistances" not in profile["imported"]
    baseline = profile["calculated"]["resistance_baseline"]
    sources = {s["id"]: s for s in profile["sources"]}
    assert sources[baseline["source_id"]]["kind"] == "pob2_engine"
    assert baseline["penalty_reference"] == 0
    assert validator.check_resistance_baseline(profile) == []


def test_resistance_baseline_must_not_live_in_imported(validator, profile_copy):
    """Если вернуть блок в imported, проверка обязана это заметить."""
    profile_copy["imported"]["uncapped_resistances"] = {
        "fire": 109,
        "cold": 66,
        "lightning": 55,
        "chaos": 0,
    }
    errors = validator.check_resistance_baseline(profile_copy)
    assert any("imported.uncapped_resistances" in e for e in errors)


def test_resistance_baseline_requires_engine_source(validator, profile_copy):
    profile_copy["calculated"]["resistance_baseline"]["source_id"] = "pob2-import-2026-11-21"
    errors = validator.check_resistance_baseline(profile_copy)
    assert any("pob2_import" in e for e in errors)


def test_resistance_baseline_evidence_is_recomputed(validator, profile_copy):
    profile_copy["calculated"]["resistance_baseline"]["evidence"][1]["total"]["cold"] = 60
    errors = validator.check_resistance_baseline(profile_copy)
    assert any("cold" in e for e in errors)


def test_resistance_baseline_evidence_must_match_scenario(validator, profile_copy):
    """Evidence сверяется с капнутым сопротивлением своего сценария."""
    profile_copy["calculated"]["scenarios"][0]["defence"]["resistances"]["cold"] = 60
    errors = validator.check_resistance_baseline(profile_copy)
    assert any("campaign-act3-normal" in e for e in errors)


def test_resistance_baseline_evidence_penalty_must_match_scenario(validator, profile_copy):
    evidence = profile_copy["calculated"]["resistance_baseline"]["evidence"]
    evidence[1]["resistancePenalty"] = -60
    errors = validator.check_resistance_baseline(profile_copy)
    assert any("штраф" in e for e in errors)
