"""Контекст анализа: сценарий расчёта, персонаж и baseline сопротивлений из профиля.

Всё, что берётся из `data/characters/<profile>.json`, несёт свой провенанс:
`source_id`, `captured_at`, `kind` источника. Анализатор не «придумывает»
конфигурацию монстров — она копируется из сценария профиля целиком.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class ProfileError(ValueError):
    """Профиль не даёт того, что нужно для анализа."""


@dataclass(frozen=True)
class Character:
    name: str
    level: int
    ascendancy: str | None
    league: str | None
    attributes: dict[str, float]
    source_id: str | None

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "level": self.level,
            "ascendancy": self.ascendancy,
            "league": self.league,
            "attributes": dict(self.attributes),
            "source_id": self.source_id,
        }


@dataclass(frozen=True)
class Scenario:
    id: str
    label: str
    config: dict[str, Any]
    source_id: str
    captured_at: str
    defence: dict[str, Any] | None = None
    skills: list[dict] | None = None

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "config": dict(self.config),
            "source_id": self.source_id,
            "captured_at": self.captured_at,
        }


@dataclass(frozen=True)
class ResistanceBaseline:
    uncapped: dict[str, float]
    source_id: str
    captured_at: str
    penalty_reference: float
    method: str | None = None

    def as_dict(self) -> dict:
        return {
            "uncapped": dict(self.uncapped),
            "source_id": self.source_id,
            "captured_at": self.captured_at,
            "penalty_reference": self.penalty_reference,
            "method": self.method,
            "provenance": "calculated.resistance_baseline (выход движка, не импорт)",
        }


@dataclass(frozen=True)
class ProfileContext:
    profile_id: str
    character: Character
    scenario: Scenario
    resistance_baseline: ResistanceBaseline | None
    engine: dict[str, Any] | None = None

    def as_dict(self) -> dict:
        return {
            "profile_id": self.profile_id,
            "character": self.character.as_dict(),
            "scenario": self.scenario.as_dict(),
            "resistance_baseline": (
                self.resistance_baseline.as_dict() if self.resistance_baseline else None
            ),
            "profile_engine": dict(self.engine or {}),
        }


def context_from_profile(profile: dict, scenario_id: str | None = None) -> ProfileContext:
    """Собирает контекст из профиля схемы 2.x."""
    calculated = profile.get("calculated") or {}
    scenarios = calculated.get("scenarios") or []
    if not scenarios:
        raise ProfileError("в профиле нет calculated.scenarios: нечего воспроизводить")

    if scenario_id is None:
        scenario = scenarios[0]
    else:
        matches = [item for item in scenarios if item.get("id") == scenario_id]
        if not matches:
            available = ", ".join(str(item.get("id")) for item in scenarios)
            raise ProfileError(f"сценарий {scenario_id!r} не найден; доступны: {available}")
        scenario = matches[0]

    character_payload = profile.get("character") or {}
    imported = profile.get("imported") or {}
    attributes = imported.get("attributes") or {}
    character = Character(
        name=str(character_payload.get("name") or "unknown"),
        level=int(character_payload.get("level") or 0),
        ascendancy=character_payload.get("ascendancy"),
        league=character_payload.get("league"),
        attributes={
            "strength": float(attributes.get("strength") or 0),
            "dexterity": float(attributes.get("dexterity") or 0),
            "intelligence": float(attributes.get("intelligence") or 0),
        },
        source_id=character_payload.get("source_id") or imported.get("source_id"),
    )

    baseline_payload = calculated.get("resistance_baseline")
    baseline: ResistanceBaseline | None = None
    if baseline_payload:
        baseline = ResistanceBaseline(
            uncapped={
                element: float(value)
                for element, value in (baseline_payload.get("uncapped") or {}).items()
            },
            source_id=str(baseline_payload.get("source_id") or ""),
            captured_at=str(baseline_payload.get("captured_at") or ""),
            penalty_reference=float(baseline_payload.get("penalty_reference") or 0),
            method=baseline_payload.get("method"),
        )

    return ProfileContext(
        profile_id=str(profile.get("profile_id") or "unknown"),
        character=character,
        scenario=Scenario(
            id=str(scenario.get("id")),
            label=str(scenario.get("label") or ""),
            config=dict(scenario.get("config") or {}),
            source_id=str(scenario.get("source_id") or ""),
            captured_at=str(scenario.get("captured_at") or ""),
            defence=scenario.get("defence"),
            skills=scenario.get("skills"),
        ),
        resistance_baseline=baseline,
        engine=calculated.get("engine"),
    )


def load_context(profile_path, scenario_id: str | None = None) -> ProfileContext:
    import json
    from pathlib import Path

    path = Path(profile_path)
    try:
        profile = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProfileError(f"профиль {path} не читается: {exc}") from exc
    return context_from_profile(profile, scenario_id)
