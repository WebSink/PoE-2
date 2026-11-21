"""Миграция профилей 2.0.0 -> 2.1.0: перенос uncapped-сопротивлений в `calculated`.

Тесты проверяют три вещи:
* миграция действительно переносит блок и не теряет числа;
* результат проходит все проверки валидатора (включая новый провенанс);
* миграция идемпотентна и не трогает файлы без `--write`.
"""

from __future__ import annotations

import copy
import json

import pytest


def _validate(validator, schema, profile):
    errors = validator.validate_schema(profile, schema)
    if errors:
        return errors
    errors.extend(validator.check_provenance(profile))
    errors.extend(validator.check_no_calculated_outside_scenarios(profile))
    errors.extend(validator.check_resistance_baseline(profile))
    errors.extend(validator.check_resistances(profile))
    return errors


def test_legacy_fixture_really_is_2_0_0(validator, schema, profile_v2):
    """Фикстура должна быть валидной 2.0.0-формой, иначе тест ниже ничего не значит."""
    assert profile_v2["schema_version"] == "2.0.0"
    assert "uncapped_resistances" in profile_v2["imported"]
    assert "resistance_baseline" not in profile_v2["calculated"]
    # схема 2.1.0 уже не принимает такую форму — миграция обязательна, а не косметика
    errors = validator.validate_schema(profile_v2, schema)
    assert any("uncapped_resistances" in e for e in errors)
    assert any("resistance_baseline" in e for e in errors)


def test_migration_moves_block_and_keeps_numbers(migration, profile_v2):
    uncapped_before = copy.deepcopy(profile_v2["imported"]["uncapped_resistances"])
    new, notes = migration.migrate_profile(profile_v2)

    assert new["schema_version"] == "2.1.0"
    assert "uncapped_resistances" not in new["imported"]
    baseline = new["calculated"]["resistance_baseline"]
    assert baseline["uncapped"] == uncapped_before
    assert baseline["penalty_reference"] == -20
    assert notes


def test_migration_does_not_mutate_input(migration, profile_v2):
    before = copy.deepcopy(profile_v2)
    migration.migrate_profile(profile_v2)
    assert profile_v2 == before


def test_migrated_profile_passes_every_check(validator, migration, schema, profile_v2):
    new, _ = migration.migrate_profile(profile_v2)
    assert _validate(validator, schema, new) == []


def test_migration_is_idempotent(migration, profile):
    new, notes = migration.migrate_profile(profile)
    assert new == profile
    assert notes == ["профиль уже на схеме 2.1.0, изменений нет"]


def test_migration_adds_engine_source_when_missing(migration, profile_v2):
    legacy = copy.deepcopy(profile_v2)
    legacy["sources"] = [s for s in legacy["sources"] if s["kind"] != "pob2_engine"]
    new, _ = migration.migrate_profile(legacy)
    source_id = new["calculated"]["resistance_baseline"]["source_id"]
    kinds = {s["id"]: s["kind"] for s in new["sources"]}
    assert kinds[source_id] == "pob2_engine"


def test_migration_rejects_profile_without_block(migration, profile):
    broken = copy.deepcopy(profile)
    broken["schema_version"] = "2.0.0"
    broken["calculated"].pop("resistance_baseline")
    with pytest.raises(migration.MigrationError):
        migration.migrate_profile(broken)


def test_migration_rejects_unknown_version(migration, profile_copy):
    profile_copy["schema_version"] = "9.9.9"
    with pytest.raises(migration.MigrationError):
        migration.migrate_profile(profile_copy)


def test_cli_check_mode_writes_nothing(migration, tmp_path, profile_v2):
    target = tmp_path / "legacy.json"
    target.write_text(json.dumps(profile_v2, ensure_ascii=False), encoding="utf-8")
    before = target.read_text(encoding="utf-8")

    assert migration.main(["--path", str(target), "--check"]) == 1
    assert target.read_text(encoding="utf-8") == before


def test_cli_write_mode_migrates_file(migration, validator, schema, tmp_path, profile_v2):
    target = tmp_path / "legacy.json"
    target.write_text(json.dumps(profile_v2, ensure_ascii=False), encoding="utf-8")

    assert migration.main(["--path", str(target), "--write"]) == 0
    migrated = json.loads(target.read_text(encoding="utf-8"))
    assert migrated["schema_version"] == "2.1.0"
    assert _validate(validator, schema, migrated) == []
