#!/usr/bin/env python3
"""CLI: проверка одного предмета-кандидата на движке PoB2.

Примеры
-------
Текст, скопированный из игры::

    uv run python scripts/gear_analyze.py --slot Boots --item-text candidate.txt

Структурированный JSON (когда текст неполный)::

    uv run python scripts/gear_analyze.py --slot Boots \\
        --item-json data/candidates/sinkov-boots-windrush-partial.json

Без движка (только объявленные свойства и проекция сопротивлений)::

    uv run python scripts/gear_analyze.py --slot Boots --item-json cand.json --no-engine

Коды возврата
-------------
0 — отчёт построен (движком или только по объявленным свойствам);
1 — ошибка входных данных;
2 — движок недоступен или вернул ошибку расчёта;
3 — предмет нельзя надеть по требованиям.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from poe2cc.gear import (  # noqa: E402  (путь к пакету добавляется выше)
    ENGINE_STATUS_ERROR,
    ENGINE_STATUS_UNAVAILABLE,
    AnalysisError,
    GearAnalyzer,
    ItemParseError,
    ProfileError,
    load_candidate,
    load_context,
    render_text,
    write_json,
)

DEFAULT_PROFILE = ROOT / "data" / "characters" / "sinkov.json"
DEFAULT_BUILD = ROOT / "data" / "builds" / "sinkov-standard.xml"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Сравнить надетый предмет с кандидатом на движке PoB2",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Примеры")[-1],
    )
    parser.add_argument("--slot", required=True, help="слот экипировки, например Boots")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--item-text", help="файл с текстом предмета, скопированным из PoE2")
    source.add_argument("--item-json", help="JSON с описанием предмета (структурированный ввод)")
    parser.add_argument("--build", default=str(DEFAULT_BUILD), help="PoB2-экспорт персонажа")
    parser.add_argument("--profile", default=str(DEFAULT_PROFILE), help="профиль персонажа")
    parser.add_argument(
        "--scenario",
        default=None,
        help="id сценария профиля (по умолчанию первый, для Sinkov — campaign-act3-normal)",
    )
    parser.add_argument("--no-engine", action="store_true", help="не запускать pob-mcp")
    parser.add_argument("--json", dest="json_out", help="записать отчёт в JSON-файл")
    parser.add_argument("--quiet", action="store_true", help="не печатать текстовый отчёт")
    parser.add_argument(
        "--timeout", type=float, default=120.0, help="таймаут вызова движка, секунды"
    )
    parser.add_argument(
        "--engine-command", default=None, help="путь к pob-mcp (иначе автоопределение)"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    # Консоль Windows может быть в cp866/cp1251: отчёт содержит кириллицу
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")

    args = build_parser().parse_args(argv)

    try:
        context = load_context(args.profile, args.scenario)
    except ProfileError as exc:
        print(f"[FAIL] профиль: {exc}", file=sys.stderr)
        return 1

    source = args.item_json or args.item_text
    try:
        candidate = load_candidate(source, slot=args.slot)
    except ItemParseError as exc:
        print(f"[FAIL] предмет: {exc}", file=sys.stderr)
        return 1

    analyzer = GearAnalyzer(engine_command=args.engine_command, timeout=args.timeout)
    try:
        report = analyzer.analyze(
            build_path=args.build,
            candidate=candidate,
            slot=args.slot,
            context=context,
            use_engine=not args.no_engine,
        )
    except AnalysisError as exc:
        print(f"[FAIL] анализ: {exc}", file=sys.stderr)
        return 1

    if not args.quiet:
        print(render_text(report), end="")

    if args.json_out:
        target = write_json(report, args.json_out)
        print(f"\n[ OK ] JSON-отчёт: {target}", file=sys.stderr)

    if report.engine.status in (ENGINE_STATUS_UNAVAILABLE, ENGINE_STATUS_ERROR):
        return 2
    if report.requirements.equippable is False:
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
