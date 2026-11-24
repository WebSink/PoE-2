"""Текстовая и JSON-сериализация отчёта анализа.

Текстовая форма нужна для CLI и для документации: в ней всегда видно, откуда
взято каждое число (`basis`) и чего посчитать не удалось.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import stats
from .analyzer import (
    ENGINE_STATUS_ERROR,
    ENGINE_STATUS_OK,
    ENGINE_STATUS_SKIPPED,
    ENGINE_STATUS_UNAVAILABLE,
    STATUS_COMPUTED,
    STATUS_ENGINE_REQUIRED,
    STATUS_UNKNOWN,
    AnalysisReport,
)
from .rating import VERDICT_LABELS

_STATUS_LABELS = {
    STATUS_COMPUTED: "посчитано",
    STATUS_ENGINE_REQUIRED: "нужен движок",
    STATUS_UNKNOWN: "неизвестно",
}

_ENGINE_LABELS = {
    ENGINE_STATUS_OK: "выполнен (PoB2 через pob-mcp)",
    ENGINE_STATUS_SKIPPED: "не выполнялся",
    ENGINE_STATUS_UNAVAILABLE: "движок недоступен",
    ENGINE_STATUS_ERROR: "ошибка расчёта",
}


def _number(value: float | None, unit: str = "") -> str:
    if value is None:
        return "—"
    if unit == "percent":
        return f"{value:+.1f}%"
    if abs(value - round(value)) < 1e-9:
        return f"{value:+.0f}"
    return f"{value:+.2f}"


def _plain(value: float | None, unit: str = "") -> str:
    if value is None:
        return "—"
    if unit == "percent":
        return f"{value:.1f}%"
    if abs(value - round(value)) < 1e-9:
        return f"{value:.0f}"
    return f"{value:.2f}"


def _level(value: float | None) -> str:
    if value is None:
        return "не указан"
    return f"{value:g}"


def render_text(report: AnalysisReport) -> str:
    lines: list[str] = []
    scenario = report.scenario
    lines.append("=" * 78)
    lines.append(f"Анализ замены предмета, слот: {report.slot}")
    lines.append("=" * 78)
    lines.append(
        f"Персонаж: {report.character.name}, уровень {report.character.level}, "
        f"{report.character.ascendancy or 'класс неизвестен'}, лига {report.character.league or '—'}"
    )
    lines.append(f"Профиль: {report.profile['profile_id']}")
    lines.append(f"Сценарий: {scenario.id} — {scenario.label}")
    config = ", ".join(f"{key}={value}" for key, value in sorted(scenario.config.items()))
    lines.append(f"Конфигурация: {config}")
    lines.append(f"Движок: {_ENGINE_LABELS.get(report.engine.status, report.engine.status)}")
    if report.engine.info:
        info = report.engine.info
        lines.append(
            f"  PoB2 {info.get('version', '?')}, tree data {info.get('tree_data_version', '?')}, "
            f"{info.get('transport', '?')}"
        )
    if report.engine.error:
        lines.append(f"  причина: {report.engine.error}")
    elif report.engine.reason:
        lines.append(f"  причина: {report.engine.reason}")

    lines.append("")
    lines.append("-- Предметы " + "-" * 65)
    current = report.current_item
    if current is None:
        lines.append("Сейчас в слоте: пусто")
    else:
        defences = ", ".join(f"{key} {value:g}" for key, value in current.defences.items())
        lines.append(
            f"Сейчас: {current.name} ({current.base or 'база неизвестна'}), "
            f"уровень {_level(current.required_level)}"
            + (f", защита: {defences}" if defences else "")
        )
    candidate = report.candidate
    candidate_defences = ", ".join(f"{key} {value:g}" for key, value in candidate.defences.items())
    lines.append(
        f"Кандидат: {candidate.name} ({candidate.base or 'база не указана'}), "
        f"уровень {_level(candidate.required_level)}, источник {candidate.source_format}"
        + (f", защита: {candidate_defences}" if candidate_defences else "")
    )
    if candidate.unknown_mods:
        lines.append(f"  UNKNOWN-модификаторов: {len(candidate.unknown_mods)}")
        for mod in candidate.unknown_mods:
            lines.append(f"    ? {mod.text}")

    lines.append("")
    lines.append("-- Можно ли надеть " + "-" * 59)
    for check in report.requirements.checks:
        marker = {"satisfied": "ok", "not_satisfied": "НЕТ", "unknown": "?"}[check.status]
        lines.append(f"  [{marker:>3}] {check.label}: {check.detail}")
    equippable = report.requirements.equippable
    lines.append(
        "  Итог: "
        + {
            True: "надеть можно",
            False: "надеть нельзя",
            None: "недостаточно данных, чтобы утверждать",
        }[equippable]
    )
    for check in report.cascade.checks:
        marker = {"satisfied": "ok", "not_satisfied": "НЕТ", "unknown": "?"}[check.status]
        lines.append(f"  [{marker:>3}] {check.label}: {check.detail}")

    lines.append("")
    lines.append("-- Изменения характеристик " + "-" * 51)
    if not report.deltas:
        lines.append("  нет данных")
    else:
        lines.append(f"  {'Характеристика':<32}{'до':>10}{'после':>10}{'изм.':>10}  статус")
        for delta in report.deltas:
            unit = stats.unit(delta.stat)
            label = stats.label(delta.stat)
            if len(label) > 30:
                label = label[:29] + ".."
            lines.append(
                f"  {label:<32}{_plain(delta.before, unit):>10}"
                f"{_plain(delta.after, unit):>10}{_number(delta.delta, unit):>10}"
                f"  {_STATUS_LABELS.get(delta.status, delta.status)} ({delta.basis})"
            )

    lines.append("")
    lines.append("-- Сопротивления " + "-" * 60)
    lines.append(f"  {'Стихия':<12}{'до капа':>18}{'после капа':>20}  изм. после капа")
    for change in report.resistances:
        before_uncapped = _plain(change.before_uncapped, "percent")
        after_uncapped = _plain(change.after_uncapped, "percent")
        before_capped = _plain(change.before_capped, "percent")
        after_capped = _plain(change.after_capped, "percent")
        lines.append(
            f"  {change.element:<12}{before_uncapped + ' -> ' + after_uncapped:>18}"
            f"{before_capped + ' -> ' + after_capped:>20}  "
            f"{_number(change.delta_capped, 'percent')}"
        )
    lines.append("  кап сопротивления: " + _cap_summary(report))
    lines.append(
        "  штраф сценария: "
        + str(report.scenario.config.get("resistancePenalty"))
        + " (поле resistancePenalty из конфигурации сценария)"
    )

    if report.metrics:
        lines.append("")
        lines.append("-- Метрики движка " + "-" * 58)
        for metric in report.metrics:
            percent = metric.delta_percent
            lines.append(
                f"  {metric.label}: {_plain(metric.before)} -> {_plain(metric.after)}"
                + (f" ({percent:+.2f}%)" if percent is not None else "")
            )

    lines.append("")
    lines.append("-- Что потеряно и что получено " + "-" * 45)
    if report.lost_mods:
        lines.append("  Потеряно:")
        for mod in report.lost_mods:
            lines.append(f"    - {mod}")
    else:
        lines.append("  Потеряно: ничего из объявленного")
    if report.gained_mods:
        lines.append("  Получено:")
        for mod in report.gained_mods:
            lines.append(f"    + {mod}")
    else:
        lines.append("  Получено: ничего нового из объявленного")
    if report.lost_defences or report.gained_defences:
        lines.append("  Локальная защита предмета (не суммируется с модификаторами):")
        for defence, value in sorted(report.lost_defences.items()):
            lines.append(f"    - {defence}: -{value:g}")
        for defence, value in sorted(report.gained_defences.items()):
            lines.append(f"    + {defence}: +{value:g}")

    rating = report.rating
    lines.append("")
    lines.append("-- Оценка " + "-" * 67)
    lines.append(
        f"  Балл {rating.score:+.2f} -> {VERDICT_LABELS[rating.verdict]}"
        + (
            f" (предварительно: {VERDICT_LABELS[rating.provisional_verdict]})"
            if rating.provisional_verdict
            else ""
        )
    )
    for item in rating.explanation:
        lines.append(f"    - {item}")

    if report.warnings:
        lines.append("")
        lines.append("-- Предупреждения " + "-" * 60)
        for warning in report.warnings:
            lines.append(f"  ! {warning}")

    lines.append("")
    lines.append("-- Ограничения " + "-" * 62)
    for limitation in report.limitations:
        lines.append(f"  - {limitation}")

    lines.append("")
    lines.append("-- Целостность исходного билда " + "-" * 46)
    integrity = report.integrity
    lines.append(f"  файл: {integrity.build_path}")
    lines.append(f"  sha256 до:    {integrity.sha256_before}")
    lines.append(f"  sha256 после: {integrity.sha256_after}")
    lines.append(
        "  исходный XML "
        + ("не изменён" if integrity.unchanged else "ИЗМЕНЁН — результат недостоверен")
    )
    if report.engine.sanity:
        lines.append("")
        lines.append("-- sanity_check движка " + "-" * 55)
        for message in report.engine.sanity:
            lines.append(f"  - {message}")
    return "\n".join(lines) + "\n"


def _cap_summary(report: AnalysisReport) -> str:
    """Предел сопротивления по стихиям: до -> после, или «не измерен»."""
    parts: list[str] = []
    for change in report.resistances:
        if change.cap_basis is None:
            parts.append(f"{change.element} неизвестен")
            continue
        before = _plain(change.before_cap, "percent")
        after = _plain(change.after_cap, "percent")
        if change.after_cap is not None and change.before_cap != change.after_cap:
            parts.append(f"{change.element} {before} -> {after}")
        else:
            parts.append(f"{change.element} {before}")
    if not parts:
        return "нет данных"
    return ", ".join(parts)


def write_json(report: AnalysisReport, path: str | Path) -> Path:
    target = Path(path)
    target.write_text(
        json.dumps(report.as_dict(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    return target


def dumps_json(report: AnalysisReport) -> str:
    return json.dumps(report.as_dict(), ensure_ascii=False, indent=1)
