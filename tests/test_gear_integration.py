"""Интеграция с настоящим PoB2 через `pob-mcp`.

Тесты запускают реальный движок и поэтому помечены `integration`:

    uv run pytest tests/test_gear_integration.py -q -m integration

Если локальной установки `.tools/pob-mcp` нет, тесты пропускаются, а не падают:
CI без PoB2 не должен врать о результате.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from poe2cc.gear import (
    ENGINE_STATUS_OK,
    GearAnalyzer,
    load_candidate,
    load_context,
    locate_engine_command,
    parse_item_text,
)

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parent.parent
PROFILE_PATH = ROOT / "data" / "characters" / "sinkov.json"
BUILD_PATH = ROOT / "data" / "builds" / "sinkov-standard.xml"
CANDIDATE_PATH = ROOT / "data" / "candidates" / "sinkov-boots-windrush-partial.json"


def _engine_available() -> bool:
    return locate_engine_command() is not None


requires_engine = pytest.mark.skipif(
    not _engine_available(), reason="локальный pob-mcp не найден (.tools/pob-mcp)"
)
requires_build = pytest.mark.skipif(
    not BUILD_PATH.is_file(), reason="PoB2-экспорт Sinkov не найден (data/builds/ в Git не входит)"
)


@pytest.fixture(scope="module")
def real_context():
    return load_context(PROFILE_PATH, "campaign-act3-normal")


@pytest.fixture(scope="module")
def build_sha() -> str:
    return hashlib.sha256(BUILD_PATH.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def identity_boots_text():
    """Текущие ботинки, переписанные в текст PoE2: должны дать нулевую разницу."""
    return """Rarity: RARE
Victory League
Silk Slippers
Item Level: 60
Quality: 0
LevelReq: 36
Energy Shield: 79
+43 to maximum Energy Shield
+21 to maximum Life
+20 to maximum Mana
+13% to Fire Resistance
+19% to Cold Resistance
+60 to Stun Threshold
"""


@requires_engine
@requires_build
def test_engine_is_reachable_and_reports_version(real_context):
    analyzer = GearAnalyzer()
    report = analyzer.analyze(
        build_path=BUILD_PATH,
        candidate=parse_item_text(
            """Rarity: RARE
Probe
Silk Slippers
LevelReq: 36
+10 to maximum Life
""",
            slot="Boots",
        ),
        slot="Boots",
        context=real_context,
    )

    assert report.engine.status == ENGINE_STATUS_OK
    info = report.engine.info
    assert info["version"] not in (None, "", "unknown")
    assert info["tree_data_version"] not in (None, "", "unknown")


@requires_engine
@requires_build
def test_baseline_matches_profile_scenario(real_context):
    """База движка под конфигурацией сценария должна совпадать с профилем."""
    analyzer = GearAnalyzer()
    report = analyzer.analyze(
        build_path=BUILD_PATH,
        candidate=parse_item_text(
            """Rarity: RARE
Probe
Silk Slippers
LevelReq: 36
+10 to maximum Life
""",
            slot="Boots",
        ),
        slot="Boots",
        context=real_context,
    )

    deltas = {delta.stat: delta for delta in report.deltas}
    assert deltas["life"].before == pytest.approx(947.0)
    assert deltas["energy_shield"].before == pytest.approx(238.0)
    assert deltas["armour"].before == pytest.approx(300.0)
    assert deltas["movement_speed"].before == pytest.approx(96.0)


@requires_engine
@requires_build
def test_identity_item_produces_zero_change(real_context, identity_boots_text):
    """Тот же предмет в виде текста: движок должен показать нулевую разницу."""
    report = GearAnalyzer().analyze(
        build_path=BUILD_PATH,
        candidate=parse_item_text(identity_boots_text, slot="Boots"),
        slot="Boots",
        context=real_context,
    )

    assert report.engine.status == ENGINE_STATUS_OK
    for delta in report.deltas:
        assert delta.delta == pytest.approx(0.0), delta.stat
    for change in report.resistances:
        assert change.delta_capped == pytest.approx(0.0), change.element
    assert report.rating.verdict == "sidegrade"


@requires_engine
@requires_build
def test_original_build_is_unchanged_after_real_engine_run(real_context, build_sha):
    GearAnalyzer().analyze(
        build_path=BUILD_PATH,
        candidate=parse_item_text(
            """Rarity: RARE
Probe
Silk Slippers
LevelReq: 36
+25 to maximum Life
+7% to Lightning Resistance
""",
            slot="Boots",
        ),
        slot="Boots",
        context=real_context,
    )

    assert hashlib.sha256(BUILD_PATH.read_bytes()).hexdigest() == build_sha


@requires_engine
@requires_build
def test_engine_does_not_enforce_requirements(real_context):
    """Документируем поведение движка: он надевает предмет выше уровня персонажа."""
    report = GearAnalyzer().analyze(
        build_path=BUILD_PATH,
        candidate=parse_item_text(
            """Rarity: RARE
Too High
Silk Slippers
LevelReq: 60
+500 to maximum Life
""",
            slot="Boots",
        ),
        slot="Boots",
        context=real_context,
    )

    assert report.requirements.equippable is False
    assert report.rating.verdict == "not_equippable"
    # анализатор не запускает движок для такой вещи — иначе получилось бы «+500 жизни»
    assert report.engine.status != ENGINE_STATUS_OK


@requires_engine
@requires_build
def test_two_candidates_are_compared_under_the_same_config(real_context):
    analyzer = GearAnalyzer()
    first = analyzer.analyze(
        build_path=BUILD_PATH,
        candidate=parse_item_text(
            """Rarity: RARE
Life Boots
Silk Slippers
LevelReq: 36
+60 to maximum Life
+5% to Cold Resistance
""",
            slot="Boots",
        ),
        slot="Boots",
        context=real_context,
    )
    second = analyzer.analyze(
        build_path=BUILD_PATH,
        candidate=parse_item_text(
            """Rarity: RARE
Res Boots
Silk Slippers
LevelReq: 36
+10 to maximum Life
+35% to Cold Resistance
""",
            slot="Boots",
        ),
        slot="Boots",
        context=real_context,
    )

    assert first.scenario.as_dict() == second.scenario.as_dict()
    first_base = {delta.stat: delta.before for delta in first.deltas}
    second_base = {delta.stat: delta.before for delta in second.deltas}
    assert first_base == second_base


@requires_build
def test_real_sinkov_boots_candidate_in_declared_mode(real_context):
    """Реальный кандидат «Ураганная спешка»: только подтверждённые свойства.

    Полного текста предмета нет, поэтому движок не запускается — и отчёт обязан
    честно сказать, что именно осталось непосчитанным.
    """
    candidate = load_candidate(CANDIDATE_PATH, slot="Boots")
    report = GearAnalyzer().analyze(
        build_path=BUILD_PATH,
        candidate=candidate,
        slot="Boots",
        context=real_context,
    )

    assert report.mode == "declared_only"
    assert report.engine.status != ENGINE_STATUS_OK
    assert report.current_item is not None
    assert report.current_item.name == "Victory League"

    # +83 — объявленный итог, включая связанные бонусы: строки не суммируются повторно
    life = next(delta for delta in report.deltas if delta.stat == "life")
    assert life.delta == pytest.approx(83.0 - 21.0)

    cold = next(change for change in report.resistances if change.element == "cold")
    assert cold.delta_capped == pytest.approx(-19.0)
    lightning = next(change for change in report.resistances if change.element == "lightning")
    assert lightning.delta_capped == pytest.approx(21.0)

    # уровень подходит (46 >= 45), но требования атрибутов неизвестны: база не указана
    level = next(check for check in report.requirements.checks if check.kind == "level")
    assert level.status == "satisfied"
    assert report.requirements.equippable is None
    assert any("нельзя достоверно воспроизвести" in item for item in report.limitations)
    assert report.integrity.unchanged is True
