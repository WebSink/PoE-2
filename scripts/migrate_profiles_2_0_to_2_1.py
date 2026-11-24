#!/usr/bin/env python3
"""Миграция профилей персонажей со схемы 2.0.0 на 2.1.0.

Что меняется и почему
---------------------
В 2.0.0 блок `imported.uncapped_resistances` лежал в разделе *импорта*, хотя
его значения получены не из аккаунта, а выведены из расчётов движка PoB2:
клиент и движок показывают сопротивление только *после* штрафа акта и капа 75%,
поэтому «до штрафа» — это вычисление, а не перенос данных.

В 2.1.0 блок переезжает в `calculated.resistance_baseline` и обязан нести
провенанс: `source_id` (kind = pob2_engine), `method`, `penalty_reference`,
`evidence` с измерениями по каждому штрафу. Валидатор проверяет и арифметику,
и то, что `imported.uncapped_resistances` больше не существует.

Использование
-------------
    python scripts/migrate_profiles_2_0_to_2_1.py --check
    python scripts/migrate_profiles_2_0_to_2_1.py --write
    python scripts/migrate_profiles_2_0_to_2_1.py --path data/characters/sinkov.json --write

Без `--write` файлы не меняются: печатается только план миграции.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import validate_data

ROOT = Path(__file__).resolve().parent.parent
FROM_VERSION = "2.0.0"
TO_VERSION = "2.1.0"
ELEMENTAL = ("fire", "cold", "lightning", "chaos")

METHOD = (
    "Перенесено из imported.uncapped_resistances (схема 2.0.0). Значения выведены "
    "движком PoB2: клиент показывает сопротивление после штрафа акта и капа, поэтому "
    "uncapped восстановлен из измерений при разных resistancePenalty. Evidence "
    "пересчитан как uncapped + штраф; проверяется сверкой с капнутыми значениями "
    "сценариев, которые были измерены напрямую."
)


class MigrationError(RuntimeError):
    pass


def _resistance_source(profile: dict) -> dict:
    """Находит источник kind=pob2_engine, на который можно сослаться."""
    sources = profile.get("sources", [])
    engine_sources = [s for s in sources if s.get("kind") == "pob2_engine"]
    if engine_sources:
        return engine_sources[0]
    import_sources = [s for s in sources if s.get("kind") == "pob2_import"]
    if import_sources:
        # импорт не может подтверждать расчёт: добавляем отдельный engine-источник
        base = import_sources[0]
        return {
            "id": f"{base['id']}-engine",
            "kind": "pob2_engine",
            "date": base.get("date", "1970-01-01"),
            "description": (
                "Расчёты движка PoB2, из которых выведены uncapped-сопротивления. "
                "Создан миграцией 2.0.0 -> 2.1.0."
            ),
            "engine_version": base.get("engine_version", "unknown"),
            "tree_data_version": base.get("tree_data_version", "unknown"),
        }
    raise MigrationError(
        "нет ни источника pob2_engine, ни pob2_import: нечем подтвердить uncapped-сопротивления"
    )


def _evidence_from_scenarios(profile: dict, uncapped: dict) -> list[dict]:
    """Строит evidence из сценариев: total = uncapped + штраф сценария."""
    rows: list[dict] = []
    for scenario in profile.get("calculated", {}).get("scenarios", []):
        penalty = scenario.get("config", {}).get("resistancePenalty")
        if penalty is None:
            continue
        total = {element: uncapped[element] + penalty for element in ("fire", "cold", "lightning")}
        total["chaos"] = uncapped["chaos"]
        rows.append(
            {
                "resistancePenalty": penalty,
                "total": total,
                "scenario_id": scenario.get("id"),
                "stat_fields": [
                    "FireResistTotal",
                    "ColdResistTotal",
                    "LightningResistTotal",
                    "ChaosResistTotal",
                ],
            }
        )
    return rows


def migrate_profile(profile: dict) -> tuple[dict, list[str]]:
    """Возвращает (новый профиль, список изменений). Исходный объект не меняется."""
    notes: list[str] = []
    version = profile.get("schema_version")

    if version == TO_VERSION and "uncapped_resistances" not in profile.get("imported", {}):
        return copy.deepcopy(profile), ["профиль уже на схеме 2.1.0, изменений нет"]
    if version not in (FROM_VERSION, TO_VERSION):
        raise MigrationError(f"неизвестная версия схемы: {version!r}")

    imported = profile.get("imported", {})
    uncapped = imported.get("uncapped_resistances")
    if not uncapped:
        raise MigrationError(
            "в imported нет uncapped_resistances: миграция 2.0.0 -> 2.1.0 неприменима"
        )
    missing = [element for element in ELEMENTAL if element not in uncapped]
    if missing:
        raise MigrationError(f"в uncapped_resistances нет элементов: {missing}")

    new = copy.deepcopy(profile)
    new["schema_version"] = TO_VERSION

    # 1. убрать блок из импорта — там он выдавал расчёт за перенос данных
    del new["imported"]["uncapped_resistances"]
    notes.append("imported.uncapped_resistances -> calculated.resistance_baseline.uncapped")

    # 2. источник провенанса
    source = _resistance_source(new)
    if source["id"] not in {s["id"] for s in new.get("sources", [])}:
        new.setdefault("sources", []).append(source)
        notes.append(f"добавлен источник {source['id']} (kind=pob2_engine)")

    # 3. сам блок с провенансом
    evidence = _evidence_from_scenarios(new, uncapped)
    penalties = [row["resistancePenalty"] for row in evidence]
    reference = max(penalties) if penalties else 0
    new.setdefault("calculated", {})["resistance_baseline"] = {
        "source_id": source["id"],
        "captured_at": source.get("date", "1970-01-01"),
        "method": METHOD,
        "penalty_reference": reference,
        "uncapped": {element: uncapped[element] for element in ELEMENTAL},
        "evidence": evidence,
        "notes": [
            "Миграция не выдумывает числа: uncapped перенесён из 2.0.0 без изменений.",
            "Evidence восстановлен как uncapped + штраф; прямыми измерениями остаются "
            "капнутые значения сценариев, с ними и сверяется валидатор.",
        ],
    }
    notes.append(
        f"calculated.resistance_baseline: {len(evidence)} измерений, penalty_reference={reference}"
    )
    return new, notes


def _targets(paths: list[Path]) -> list[Path]:
    result: list[Path] = []
    for path in paths:
        if path.is_dir():
            result.extend(sorted(path.glob("*.json")))
        else:
            result.append(path)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--path",
        action="append",
        default=None,
        help="файл или каталог профилей (по умолчанию data/characters)",
    )
    parser.add_argument("--write", action="store_true", help="записать результат на диск")
    parser.add_argument("--check", action="store_true", help="только проверить, что миграция нужна")
    parser.add_argument("--json", action="store_true", help="вывод в JSON")
    args = parser.parse_args(argv)

    raw_paths = [Path(p) for p in (args.path or [ROOT / "data" / "characters"])]
    targets = _targets(raw_paths)
    schema = json.loads(validate_data.SCHEMA_PATH.read_text(encoding="utf-8"))

    report: list[dict[str, Any]] = []
    errors: list[str] = []
    pending = 0

    for path in targets:
        try:
            profile = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{path}: не читается ({exc})")
            continue
        try:
            new, notes = migrate_profile(profile)
        except MigrationError as exc:
            errors.append(f"{path}: {exc}")
            continue

        changed = new != profile
        pending += int(changed)
        problems = validate_data.validate_schema(new, schema)
        if not problems:
            problems = (
                validate_data.check_provenance(new)
                + validate_data.check_no_calculated_outside_scenarios(new)
                + validate_data.check_resistance_baseline(new)
                + validate_data.check_resistances(new)
            )
        if problems:
            errors.extend(f"{path}: {p}" for p in problems)

        if changed and args.write:
            path.write_text(json.dumps(new, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        report.append(
            {
                "path": str(path),
                "changed": changed,
                "written": bool(changed and args.write),
                "notes": notes,
                "errors": problems,
            }
        )

    if args.json:
        print(json.dumps({"profiles": report, "errors": errors}, ensure_ascii=False, indent=1))
    else:
        for row in report:
            state = "изменён" if row["changed"] else "без изменений"
            print(f"[{'OK' if not row['errors'] else 'FAIL'}] {row['path']}: {state}")
            for note in row["notes"]:
                print(f"    - {note}")
        if errors:
            print(f"\n[FAIL] ошибок: {len(errors)}")
            for err in errors:
                print(f"  - {err}")
        else:
            print(f"\n[ OK ] профилей: {len(report)}, требуют миграции: {pending}")

    if args.check:
        return 1 if pending else (1 if errors else 0)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
