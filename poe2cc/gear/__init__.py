"""Детерминированный анализ замены экипировки на движке PoB2.

Точка входа для кода и тестов:

    from poe2cc.gear import GearAnalyzer, load_candidate, load_context

    context = load_context("data/characters/sinkov.json", "campaign-act3-normal")
    candidate = load_candidate("candidate.txt", slot="Boots")
    report = GearAnalyzer().analyze(
        build_path="data/builds/sinkov-standard.xml",
        candidate=candidate,
        slot="Boots",
        context=context,
    )
    print(report.as_dict())

Никакой UI здесь нет (это S5.1): только модуль, CLI и отчёты.
"""

from __future__ import annotations

from .analyzer import (
    ENGINE_STATUS_ERROR,
    ENGINE_STATUS_OK,
    ENGINE_STATUS_SKIPPED,
    ENGINE_STATUS_UNAVAILABLE,
    AnalysisError,
    AnalysisReport,
    GearAnalyzer,
    StatDelta,
    XmlIntegrity,
)
from .engine import (
    EngineCalculationError,
    EngineInfo,
    EngineUnavailable,
    McpStdioEngine,
    locate_engine_command,
)
from .items import (
    Item,
    ItemParseError,
    items_from_xml,
    load_candidate,
    parse_item_json,
    parse_item_text,
)
from .modifiers import ParsedMod, parse_mod
from .rating import Rating, evaluate
from .report import dumps_json, render_text, write_json
from .requirements import RequirementReport, check_candidate
from .scenario import ProfileContext, ProfileError, context_from_profile, load_context

__all__ = [
    "ENGINE_STATUS_ERROR",
    "ENGINE_STATUS_OK",
    "ENGINE_STATUS_SKIPPED",
    "ENGINE_STATUS_UNAVAILABLE",
    "AnalysisError",
    "AnalysisReport",
    "EngineCalculationError",
    "EngineInfo",
    "EngineUnavailable",
    "GearAnalyzer",
    "Item",
    "ItemParseError",
    "McpStdioEngine",
    "ParsedMod",
    "ProfileContext",
    "ProfileError",
    "Rating",
    "RequirementReport",
    "StatDelta",
    "XmlIntegrity",
    "check_candidate",
    "context_from_profile",
    "dumps_json",
    "evaluate",
    "items_from_xml",
    "load_candidate",
    "load_context",
    "locate_engine_command",
    "parse_item_json",
    "parse_item_text",
    "parse_mod",
    "render_text",
    "write_json",
]
