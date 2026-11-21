"""Общие фикстуры: валидатор, миграция, реальный профиль и билд Sinkov."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
VALIDATOR_PATH = ROOT / "scripts" / "validate_data.py"
MIGRATION_PATH = ROOT / "scripts" / "migrate_profiles_2_0_to_2_1.py"
PROFILE_PATH = ROOT / "data" / "characters" / "sinkov.json"
SCHEMA_PATH = ROOT / "data" / "schemas" / "character-profile.schema.json"
BUILD_PATH = ROOT / "data" / "builds" / "sinkov-standard.xml"


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_validator():
    return _load_module(VALIDATOR_PATH, "validate_data")


@pytest.fixture(scope="session")
def validator():
    return _load_validator()


@pytest.fixture(scope="session")
def migration():
    return _load_module(MIGRATION_PATH, "migrate_profiles_2_0_to_2_1")


@pytest.fixture(scope="session")
def schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


@pytest.fixture()
def profile() -> dict:
    return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))


@pytest.fixture()
def profile_copy(profile) -> dict:
    return copy.deepcopy(profile)


@pytest.fixture()
def profile_v2(profile) -> dict:
    """Профиль в форме схемы 2.0.0: uncapped-сопротивления ещё лежат в `imported`."""
    old = copy.deepcopy(profile)
    old["schema_version"] = "2.0.0"
    baseline = old["calculated"].pop("resistance_baseline")
    old["imported"]["uncapped_resistances"] = copy.deepcopy(baseline["uncapped"])
    return old


@pytest.fixture(scope="session")
def build_path() -> Path:
    """Локальный PoB2-экспорт Sinkov (`data/builds/` в Git не входит)."""
    return BUILD_PATH


# --------------------------------------------------------------------------- #
# Анализ экипировки (S5.1)
# --------------------------------------------------------------------------- #
FIXTURE_BUILD_PATH = Path(__file__).resolve().parent / "fixtures" / "minimal-build.xml"

BOOTS_TEXT = """Rarity: RARE
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


@pytest.fixture(scope="session")
def fixture_build() -> Path:
    """Синтетический PoB2-экспорт: тесты не зависят от игровых данных владельца."""
    return FIXTURE_BUILD_PATH


@pytest.fixture()
def context():
    from poe2cc.gear import load_context

    return load_context(PROFILE_PATH, "campaign-act3-normal")


@pytest.fixture()
def boots_text() -> str:
    return BOOTS_TEXT


@pytest.fixture()
def fake_engine():
    from fake_engine import FakeEngine

    return FakeEngine


@pytest.fixture()
def analyze(fixture_build, context):
    """Готовый вызов анализатора с подставленным движком-двойником."""

    from poe2cc.gear import GearAnalyzer, parse_item_text

    def run(item_text: str, *, engine=None, use_engine: bool = True, slot: str = "Boots"):
        candidate = parse_item_text(item_text, slot=slot)
        return GearAnalyzer().analyze(
            build_path=fixture_build,
            candidate=candidate,
            slot=slot,
            context=context,
            use_engine=use_engine,
            engine=engine,
        )

    return run
