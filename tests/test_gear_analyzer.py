"""Анализатор замены экипировки: обязательные сценарии S5.1.

Все тесты в этом файле работают с детерминированным двойником движка
(`tests/fake_engine.py`). Настоящий PoB2 проверяется в
`tests/test_gear_integration.py`.
"""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

import pytest

from poe2cc.gear import (
    ENGINE_STATUS_ERROR,
    ENGINE_STATUS_OK,
    ENGINE_STATUS_UNAVAILABLE,
    GearAnalyzer,
    parse_item_json,
    parse_item_text,
)

# --------------------------------------------------------------------------- #
# 1. Предмет выше уровня персонажа
# --------------------------------------------------------------------------- #


def test_item_above_character_level_is_not_equippable(analyze, fake_engine):
    text = """Rarity: RARE
Late Boots
Silk Slippers
LevelReq: 60
+50 to maximum Life
"""
    report = analyze(text, engine=fake_engine())

    assert report.requirements.equippable is False
    assert report.rating.verdict == "not_equippable"
    level = next(check for check in report.requirements.checks if check.kind == "level")
    assert level.status == "not_satisfied"
    # движок не запускается для предмета, который нельзя надеть
    assert report.engine.status != ENGINE_STATUS_OK
    assert any("нельзя надеть" in item for item in report.limitations)


# --------------------------------------------------------------------------- #
# 2. Недостаточно атрибутов
# --------------------------------------------------------------------------- #


def test_insufficient_attributes_are_reported(analyze, fake_engine):
    item = parse_item_json(
        {
            "name": "Heavy Boots",
            "slot": "Boots",
            "required_level": 40,
            "attribute_requirements": {"strength": 150, "dexterity": 0, "intelligence": 0},
            "mods": [{"text": "+50 to maximum Life"}],
        }
    )
    report = GearAnalyzer().analyze(
        build_path=analyze.__self__ if False else _fixture_build(),
        candidate=item,
        slot="Boots",
        context=_context(),
        engine=fake_engine(),
    )

    assert report.requirements.equippable is False
    strength = next(check for check in report.requirements.checks if check.kind == "strength")
    assert strength.status == "not_satisfied"
    assert strength.actual == 67
    assert strength.required == 150


# --------------------------------------------------------------------------- #
# 3. Потеря сопротивления при замене ботинок
# --------------------------------------------------------------------------- #


def test_cold_resistance_loss_on_boot_swap(analyze, fake_engine, boots_text):
    text = boots_text.replace("+19% to Cold Resistance", "+10% to Cold Resistance")
    report = analyze(text, engine=fake_engine())

    cold = next(change for change in report.resistances if change.element == "cold")
    assert cold.delta_capped == pytest.approx(-9.0)
    assert any("падает" in warning for warning in report.warnings)
    assert "+19% to Cold Resistance" in report.lost_mods


# --------------------------------------------------------------------------- #
# 4. Превышение капа сопротивлений
# --------------------------------------------------------------------------- #


def test_resistance_above_cap_does_not_improve_totals(analyze, fake_engine):
    text = """Rarity: RARE
Fire Boots
Silk Slippers
LevelReq: 36
+40% to Fire Resistance
+20 to maximum Life
"""
    report = analyze(text, engine=fake_engine())

    fire = next(change for change in report.resistances if change.element == "fire")
    # до капа сопротивление выросло, после капа — уже было на максимуме
    assert fire.after_uncapped > fire.before_uncapped
    assert fire.after_capped == pytest.approx(75.0)
    assert fire.delta_capped == pytest.approx(0.0)
    assert any("уже на капе" in warning for warning in report.warnings)
    assert "fire_resistance" not in report.rating.as_dict()["components"][0]["key"]


# --------------------------------------------------------------------------- #
# 5. Смена типа защиты: энергетический щит -> броня
# --------------------------------------------------------------------------- #


def test_defence_switch_from_energy_shield_to_armour(analyze, fake_engine):
    text = """Rarity: RARE
Plated Striders
Silk Slippers
LevelReq: 36
Armour: 115
Energy Shield: 34
+30 to maximum Life
"""
    engine = fake_engine(
        effects={
            "Plated Striders": {"EnergyShield": -45.0, "Armour": 115.0, "Life": 30.0},
        }
    )
    report = analyze(text, engine=engine)

    es = next(delta for delta in report.deltas if delta.stat == "energy_shield")
    armour = next(delta for delta in report.deltas if delta.stat == "armour")

    assert es.delta == pytest.approx(-45.0)
    assert armour.delta == pytest.approx(115.0)
    assert es.basis == "engine"
    assert report.engine.status == ENGINE_STATUS_OK
    # локальная защита предмета показана отдельно и не суммируется с модификаторами
    assert report.gained_defences["armour"] == pytest.approx(115.0)
    assert report.lost_defences["energy_shield"] == pytest.approx(79.0 - 34.0)
    # 43 — это глобальный модификатор, 79-34 — локальная защита: разные строки
    assert report.lost_stats["energy_shield"] == pytest.approx(43.0)


# --------------------------------------------------------------------------- #
# 6. Нераспознанный модификатор
# --------------------------------------------------------------------------- #


def test_unknown_mod_is_kept_and_reported(analyze, fake_engine):
    text = """Rarity: RARE
Weird Boots
Silk Slippers
LevelReq: 36
+3 to Level of all Fire Skills
+20 to maximum Life
"""
    report = analyze(text, engine=fake_engine())

    assert len(report.candidate.unknown_mods) == 1
    assert report.candidate.unknown_mods[0].text == "+3 to Level of all Fire Skills"
    assert any("UNKNOWN" in warning for warning in report.warnings)
    assert any("нераспознанные" in item for item in report.limitations)
    # неизвестный модификатор не попал в арифметику
    assert "life" in {delta.stat for delta in report.deltas}
    assert report.candidate.declared.value("life") == 20.0


# --------------------------------------------------------------------------- #
# 7. Связанные бонусы против объявленного итога
# --------------------------------------------------------------------------- #


def test_linked_bonus_is_not_double_counted(analyze, fake_engine):
    """+83 в объявлении включает связанные бонусы: сумма строк не должна давать 166."""
    item = parse_item_json(
        {
            "name": "Linked Boots",
            "slot": "Boots",
            "required_level": 36,
            "mods": [
                {"text": "+55 to maximum Life"},
                {"text": "+28 to maximum Life"},
            ],
            "declared_totals": {"life": 83},
        }
    )
    report = GearAnalyzer().analyze(
        build_path=_fixture_build(),
        candidate=item,
        slot="Boots",
        context=_context(),
        use_engine=False,
    )

    life = next(delta for delta in report.deltas if delta.stat == "life")
    assert life.delta == pytest.approx(83.0 - 21.0)
    assert report.gained_stats["life"] == pytest.approx(62.0)


# --------------------------------------------------------------------------- #
# 8. Движок недоступен
# --------------------------------------------------------------------------- #


def test_engine_unavailable_degrades_to_declared_mode(analyze, fake_engine, boots_text):
    report = analyze(boots_text, engine=fake_engine(unavailable=True))

    assert report.engine.status == ENGINE_STATUS_UNAVAILABLE
    assert report.mode == "declared_only"
    assert any("недоступен" in warning for warning in report.warnings)
    assert all(delta.basis == "declared" for delta in report.deltas)
    assert report.rating.verdict == "inconclusive"
    assert report.integrity.unchanged is True


def test_missing_engine_binary_is_reported(analyze, monkeypatch, boots_text):
    """Автоопределение pob-mcp не находит бинарь — отчёт всё равно строится."""
    monkeypatch.setattr("poe2cc.gear.engine.locate_engine_command", lambda explicit=None: None)
    report = analyze(boots_text)

    assert report.engine.status == ENGINE_STATUS_UNAVAILABLE
    assert "pob-mcp" in (report.engine.error or "")


# --------------------------------------------------------------------------- #
# 9. Ошибка расчёта
# --------------------------------------------------------------------------- #


def test_engine_calculation_error_is_not_masked(analyze, fake_engine, boots_text):
    engine = fake_engine(fail_on_equip="+43 to maximum Energy Shield")
    report = analyze(boots_text, engine=engine)

    assert report.engine.status == ENGINE_STATUS_ERROR
    assert report.engine.error
    assert report.mode == "declared_only"
    # никаких чисел движка в отчёте при ошибке
    assert all(delta.basis == "declared" for delta in report.deltas)
    assert report.rating.verdict == "inconclusive"


# --------------------------------------------------------------------------- #
# 10. Исходный XML не меняется
# --------------------------------------------------------------------------- #


def test_original_build_is_never_modified(analyze, fake_engine, boots_text, fixture_build):
    before = hashlib.sha256(fixture_build.read_bytes()).hexdigest()
    before_mtime = fixture_build.stat().st_mtime_ns

    report = analyze(boots_text, engine=fake_engine())

    after = hashlib.sha256(fixture_build.read_bytes()).hexdigest()
    assert before == after
    assert fixture_build.stat().st_mtime_ns == before_mtime
    assert report.integrity.unchanged is True
    assert report.integrity.sha256_before == report.integrity.sha256_after
    assert report.integrity.temp_copy_used is True
    assert report.integrity.temp_copy_removed is True


def test_engine_gets_a_temp_copy_not_the_original(analyze, fake_engine, boots_text, fixture_build):
    engine = fake_engine()
    analyze(boots_text, engine=engine)

    assert engine.loaded_build is not None
    assert Path(engine.loaded_build) != fixture_build
    assert "poe2cc-gear-" in engine.loaded_build
    assert not Path(engine.loaded_build).exists()


def test_temp_directories_do_not_leak(analyze, fake_engine, boots_text):
    temp_root = Path(tempfile.gettempdir())
    before = {path.name for path in temp_root.glob("poe2cc-gear-*")}

    analyze(boots_text, engine=fake_engine())

    after = {path.name for path in temp_root.glob("poe2cc-gear-*")}
    assert after == before


# --------------------------------------------------------------------------- #
# 11. Два предмета при одинаковой конфигурации монстра
# --------------------------------------------------------------------------- #


def test_two_candidates_share_identical_monster_config(analyze, fake_engine):
    first = """Rarity: RARE
First Boots
Silk Slippers
LevelReq: 36
+40 to maximum Life
+15% to Cold Resistance
"""
    second = """Rarity: RARE
Second Boots
Silk Slippers
LevelReq: 36
+80 to maximum Life
+5% to Cold Resistance
"""
    engine_one = fake_engine()
    engine_two = fake_engine()

    report_one = analyze(first, engine=engine_one)
    report_two = analyze(second, engine=engine_two)

    assert engine_one.config_calls == engine_two.config_calls
    assert {key for key, _ in engine_one.config_calls} == {
        "resistancePenalty",
        "enemyIsBoss",
        "enemyLevel",
        "enemyArmour",
        "enemyEvasion",
        "enemyFireResist",
        "enemyColdResist",
        "enemyLightningResist",
        "enemyChaosResist",
    }
    assert report_one.scenario.as_dict() == report_two.scenario.as_dict()

    cold_one = next(change for change in report_one.resistances if change.element == "cold")
    cold_two = next(change for change in report_two.resistances if change.element == "cold")
    # разные кандидаты, одна и та же база сравнения
    assert cold_one.before_uncapped == cold_two.before_uncapped
    assert cold_one.after_uncapped != cold_two.after_uncapped


# --------------------------------------------------------------------------- #
# Дополнительно: контракт отчёта
# --------------------------------------------------------------------------- #


def test_report_is_json_serialisable(analyze, fake_engine, boots_text):
    import json

    report = analyze(boots_text, engine=fake_engine())
    payload = json.loads(json.dumps(report.as_dict(), ensure_ascii=False))

    assert payload["report_version"] == "1.0.0"
    assert payload["integrity"]["unchanged"] is True
    assert payload["engine"]["status"] == ENGINE_STATUS_OK
    assert payload["engine"]["info"]["version"] == "0.23.1-test"
    assert payload["rating"]["verdict"] in {
        "upgrade",
        "sidegrade",
        "downgrade",
        "not_equippable",
        "inconclusive",
    }


def test_missing_build_file_raises(fixture_build, context, boots_text):
    from poe2cc.gear import AnalysisError

    with pytest.raises(AnalysisError, match="билд не найден"):
        GearAnalyzer().analyze(
            build_path=fixture_build.parent / "nope.xml",
            candidate=parse_item_text(boots_text, slot="Boots"),
            slot="Boots",
            context=context,
        )


def test_engine_mode_marks_numbers_as_engine(analyze, fake_engine, boots_text):
    report = analyze(boots_text, engine=fake_engine())

    assert report.mode == "engine"
    assert report.deltas
    assert all(delta.basis == "engine" for delta in report.deltas)
    assert all(change.basis == "engine" for change in report.resistances)


# -- вспомогательное -------------------------------------------------------- #
def _fixture_build() -> Path:
    return Path(__file__).resolve().parent / "fixtures" / "minimal-build.xml"


def _context():
    from conftest import PROFILE_PATH

    from poe2cc.gear import load_context

    return load_context(PROFILE_PATH, "campaign-act3-normal")


def test_explicit_engine_path_is_not_silently_replaced(analyze, boots_text):
    """Явно указанный несуществующий pob-mcp — это ошибка, а не повод взять другой."""
    report = analyze(boots_text, engine=None, use_engine=True)
    assert report.engine.status == ENGINE_STATUS_OK  # автоопределение работает

    analyzer = GearAnalyzer(engine_command=str(_fixture_build().parent / "nope-pob-mcp.exe"))
    report = analyzer.analyze(
        build_path=_fixture_build(),
        candidate=parse_item_text(boots_text, slot="Boots"),
        slot="Boots",
        context=_context(),
    )

    assert report.engine.status == ENGINE_STATUS_UNAVAILABLE
    assert "nope-pob-mcp.exe" in (report.engine.error or "")


# =========================================================================== #
# Независимый review S5.1.1: подтверждённые дефекты и их регрессии
# =========================================================================== #

from dataclasses import replace  # noqa: E402

from fake_engine import DEFAULT_BASE_STATS  # noqa: E402


def _stats_with(**overrides):
    stats = dict(DEFAULT_BASE_STATS)
    stats.update(overrides)
    return stats


# --------------------------------------------------------------------------- #
# 1. Атрибуты: снимаемая вещь перестаёт действовать
# --------------------------------------------------------------------------- #


def test_swap_that_removes_attributes_breaks_cascade(analyze, fake_engine):
    """100 Dex = 70 своих + 30 от снимаемых сапог; другому предмету нужно 90."""
    engine = fake_engine(
        base_stats=_stats_with(Dex=100.0, ReqDex=90.0),
        current_item_effects={"Dex": 30.0},
        effects={"No Dex Boots": {"Life": 20.0}},
    )
    text = """Rarity: RARE
No Dex Boots
Silk Slippers
LevelReq: 36
+20 to maximum Life
"""
    report = analyze(text, engine=engine)

    assert report.engine.status == ENGINE_STATUS_OK
    assert engine.get_stats(["Dex"])["Dex"] == pytest.approx(70.0)

    cascade = next(check for check in report.cascade.checks if check.kind == "cascade_dexterity")
    assert cascade.status == "not_satisfied"
    assert cascade.actual == pytest.approx(70.0)
    assert cascade.required == pytest.approx(90.0)
    assert [check.kind for check in report.cascade.blocking] == ["cascade_dexterity"]
    assert report.rating.verdict == "requirements_broken"


def test_candidate_own_requirement_is_not_helped_by_removed_item(analyze, fake_engine):
    """Кандидат требует 80 Dex, но после снятия старой вещи остаётся 70."""
    engine = fake_engine(
        base_stats=_stats_with(Dex=100.0, ReqDex=65.0),
        current_item_effects={"Dex": 30.0},
        effects={"Dex Boots": {"Life": 20.0}},
    )
    text = """Rarity: RARE
Dex Boots
Silk Slippers
LevelReq: 36
Requires: Level 36, 80 Dex
+20 to maximum Life
"""
    report = analyze(text, engine=engine)

    dexterity = next(check for check in report.requirements.checks if check.kind == "dexterity")
    assert dexterity.status == "not_satisfied"
    assert dexterity.actual == pytest.approx(70.0)
    assert dexterity.required == pytest.approx(80.0)
    assert report.requirements.equippable is False
    assert report.rating.verdict == "not_equippable"


# --------------------------------------------------------------------------- #
# 2. Блокирующий каскад не даёт вердикт «улучшение»
# --------------------------------------------------------------------------- #


def test_big_gain_does_not_become_upgrade_when_cascade_breaks(analyze, fake_engine):
    engine = fake_engine(
        base_stats=_stats_with(Dex=100.0, ReqDex=90.0),
        current_item_effects={"Dex": 30.0},
        effects={"Big Life Boots": {"Life": 300.0}},
    )
    text = """Rarity: RARE
Big Life Boots
Silk Slippers
LevelReq: 36
+300 to maximum Life
"""
    report = analyze(text, engine=engine)

    assert report.rating.score > 3.0
    assert report.rating.verdict == "requirements_broken"
    assert report.rating.provisional_verdict is None
    assert any("ломает требования" in warning for warning in report.warnings)


# --------------------------------------------------------------------------- #
# 3. Потеря локальной защиты предмета
# --------------------------------------------------------------------------- #


def test_lost_local_energy_shield_is_reported(analyze):
    text = """Rarity: RARE
Plated Striders
Silk Slippers
LevelReq: 36
Armour: 115
+30 to maximum Life
"""
    report = analyze(text, use_engine=False)

    # 79 локального ES текущих сапог исчезает вместе с ними
    assert report.lost_defences["energy_shield"] == pytest.approx(79.0)
    assert report.gained_defences["armour"] == pytest.approx(115.0)
    # локальная защита не смешивается с глобальными модификаторами
    assert "energy_shield" not in report.gained_defences
    assert "armour" not in report.lost_defences
    # список защит кандидата полный (текст предмета): потерю можно утверждать
    assert not any("не указана защита" in item for item in report.limitations)


def test_absence_of_defence_in_json_is_unknown_not_zero(analyze):
    item = parse_item_json(
        {
            "name": "Manual Boots",
            "slot": "Boots",
            "required_level": 36,
            "defences": {"armour": 115},
            "mods": [{"text": "+30 to maximum Life"}],
        }
    )
    report = GearAnalyzer().analyze(
        build_path=_fixture_build(),
        candidate=item,
        slot="Boots",
        context=_context(),
        use_engine=False,
    )

    # ES не указан: это «неизвестно», а не «ноль», потерю 79 не приписываем
    assert "energy_shield" not in report.lost_defences
    assert report.gained_defences["armour"] == pytest.approx(115.0)
    assert any("не указана защита предмета energy_shield" in item for item in report.limitations)


# --------------------------------------------------------------------------- #
# 4. Максимум сопротивления
# --------------------------------------------------------------------------- #


def test_projection_uses_measured_maximum(analyze):
    plain = """Rarity: RARE
Storm Boots
Silk Slippers
LevelReq: 36
+60% to Lightning Resistance
+20 to maximum Life
"""
    capped = plain.replace(
        "+60% to Lightning Resistance",
        "+60% to Lightning Resistance\n+2% to maximum Lightning Resistance",
    )

    without = analyze(plain, use_engine=False)
    with_max = analyze(capped, use_engine=False)

    plain_lightning = next(c for c in without.resistances if c.element == "lightning")
    max_lightning = next(c for c in with_max.resistances if c.element == "lightning")

    assert plain_lightning.after_cap == pytest.approx(75.0)
    assert plain_lightning.delta_capped == pytest.approx(40.0)

    assert max_lightning.before_cap == pytest.approx(75.0)
    assert max_lightning.after_cap == pytest.approx(77.0)
    assert max_lightning.cap_basis == "declared"
    assert max_lightning.delta_capped == pytest.approx(42.0)


def test_projection_marks_cap_unknown_without_measured_maximum(analyze, context):
    without_maximum = replace(
        context, resistance_baseline=replace(context.resistance_baseline, maximum=None)
    )
    item = parse_item_text(
        """Rarity: RARE
Storm Boots
Silk Slippers
LevelReq: 36
+60% to Lightning Resistance
""",
        slot="Boots",
    )

    report = GearAnalyzer().analyze(
        build_path=_fixture_build(),
        candidate=item,
        slot="Boots",
        context=without_maximum,
        use_engine=False,
    )

    lightning = next(c for c in report.resistances if c.element == "lightning")
    assert lightning.after_capped is None
    assert lightning.delta_capped is None
    assert lightning.cap_basis is None
    # неизвестное сопротивление не выпадает из оценки молча
    assert "lightning_resistance" in report.rating.missing
    assert report.rating.verdict == "inconclusive"
    assert any("кап сопротивления неизвестен" in item for item in report.limitations)


def test_engine_limit_is_derived_from_saturation(analyze, fake_engine):
    engine = fake_engine(
        base_stats=_stats_with(LightningResist=35.0, LightningResistTotal=35.0),
        resist_cap=77.0,
        effects={"Max Res Boots": {"Life": 10.0}},
    )
    text = """Rarity: RARE
Max Res Boots
Silk Slippers
LevelReq: 36
+150% to Lightning Resistance
+2% to maximum Lightning Resistance
+10 to maximum Life
"""
    report = analyze(text, engine=engine)

    lightning = next(c for c in report.resistances if c.element == "lightning")
    assert lightning.before_uncapped == pytest.approx(35.0)
    assert lightning.after_uncapped == pytest.approx(185.0)
    assert lightning.after_capped == pytest.approx(77.0)
    assert lightning.after_cap == pytest.approx(77.0)
    assert lightning.cap_basis == "engine"


def test_report_prints_actual_limit_instead_of_75(analyze, fake_engine, boots_text):
    from poe2cc.gear import render_text

    report = analyze(boots_text, engine=fake_engine())
    text = render_text(report)

    assert "кап сопротивления" in text
    assert "75.0%" in text
    assert "кап 75%" not in text


# --------------------------------------------------------------------------- #
# 5. Временная копия удаляется и при ошибке
# --------------------------------------------------------------------------- #


def test_unexpected_engine_exception_degrades_and_cleans_up(analyze, fake_engine, boots_text):
    temp_root = Path(tempfile.gettempdir())
    before = {path.name for path in temp_root.glob("poe2cc-gear-*")}

    engine = fake_engine()

    def boom(*args, **kwargs):
        raise RuntimeError("сломалось на equip")

    engine.equip_item = boom
    report = analyze(boots_text, engine=engine)

    assert report.engine.status == ENGINE_STATUS_ERROR
    assert "RuntimeError" in (report.engine.error or "")
    assert report.integrity.temp_copy_used is True
    assert report.integrity.temp_copy_removed is True
    after = {path.name for path in temp_root.glob("poe2cc-gear-*")}
    assert after == before


def test_temp_copy_removed_is_false_when_directory_survives(
    analyze, fake_engine, boots_text, monkeypatch
):
    """Флаг удаления выставляется только после подтверждённого отсутствия каталога."""
    import shutil as shutil_module

    real_rmtree = shutil_module.rmtree
    leaked: list[Path] = []

    def stubborn(path, *args, **kwargs):
        leaked.append(Path(path))

    monkeypatch.setattr(shutil_module, "rmtree", stubborn)
    try:
        report = analyze(boots_text, engine=fake_engine())
        assert report.integrity.temp_copy_used is True
        assert report.integrity.temp_copy_removed is False
    finally:
        monkeypatch.undo()
        for path in leaked:
            real_rmtree(path, ignore_errors=True)
