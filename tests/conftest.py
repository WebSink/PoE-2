"""Общие фикстуры: доступ к валидатору и к реальному профилю Sinkov."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
VALIDATOR_PATH = ROOT / "scripts" / "validate_data.py"
PROFILE_PATH = ROOT / "data" / "characters" / "sinkov.json"
SCHEMA_PATH = ROOT / "data" / "schemas" / "character-profile.schema.json"


def _load_validator():
    spec = importlib.util.spec_from_file_location("validate_data", VALIDATOR_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def validator():
    return _load_validator()


@pytest.fixture(scope="session")
def schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


@pytest.fixture()
def profile() -> dict:
    return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))


@pytest.fixture()
def profile_copy(profile) -> dict:
    return copy.deepcopy(profile)
