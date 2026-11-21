#!/usr/bin/env python3
"""Валидатор данных PoE 2 Control Center.

Проверяет профили персонажей против `data/schemas/character-profile.schema.json`
и дополнительно — доменные правила целостности, которые схема выразить не может:

* каждый `source_id` существует в `sources[]`;
* `calculated.resistance_baseline` действительно выведен движком (kind=pob2_engine)
  и воспроизводится из своих же измерений; в `imported` его быть не может;
* сопротивления в каждом сценарии пересчитываются из неcapped-значений и штрафа;
* арифметика духа: максимум − резервы = свободный дух, комбинации согласованы;
* расчётные величины не существуют вне сценария (нет DPS/EHP на верхнем уровне);
* нет секретов, OAuth-данных и сырого XML;
* история профилей сохранена и разбирается как JSON.

Запуск (без внешних зависимостей):

    python scripts/validate_data.py
    python scripts/validate_data.py --json

Код возврата 0 — всё в порядке, 1 — есть ошибки.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "data" / "schemas" / "character-profile.schema.json"
CHARACTERS_DIR = ROOT / "data" / "characters"
HISTORY_DIR = CHARACTERS_DIR / "history"

RESIST_CAP = 75.0
ELEMENTAL = ("fire", "cold", "lightning")

# Поля, которых не должно быть на верхнем уровне профиля: расчёты живут
# только внутри calculated.scenarios[*], иначе теряется конфигурация.
FORBIDDEN_TOP_LEVEL = {
    "dps",
    "total_dps",
    "ehp",
    "total_ehp",
    "life",
    "energy_shield",
    "armour",
    "evasion",
    "resistances",
    "stats",
    "stats_snapshot",
}

SECRET_PATTERNS = (
    re.compile(r"poesessid", re.IGNORECASE),
    re.compile(r"refresh_?token", re.IGNORECASE),
    re.compile(r"access_?token", re.IGNORECASE),
    re.compile(r"client_?secret", re.IGNORECASE),
    re.compile(r"\bbearer\s", re.IGNORECASE),
)

# Имена полей, которых в профиле быть не должно вообще.
SECRET_KEYS = re.compile(
    r"^(token|access_token|refresh_token|lasttoken|lastrefreshtoken|sessionid|poesessid|"
    r"cookie|cookies|password|passwd|secret|client_secret|api_key|apikey|oauth_token)$",
    re.IGNORECASE,
)

# Длинные hex-строки — так выглядят токены. Исключение: явные sha256 артефактов.
HEX_BLOB = re.compile(r"\b[0-9a-f]{32,}\b", re.IGNORECASE)
SHA256_FIELDS = {"artifact_sha256", "sha256"}

XML_MARKERS = ("<PathOfBuilding2", "<Build ", "Rarity:")


# --------------------------------------------------------------------------- #
# Минимальный валидатор подмножества JSON Schema (draft 2020-12)
# --------------------------------------------------------------------------- #
class SchemaError(Exception):
    pass


def _type_ok(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    raise SchemaError(f"неизвестный тип в схеме: {expected}")


def validate_schema(value: Any, schema: dict, path: str = "$") -> list[str]:
    """Проверяет значение против подмножества JSON Schema, возвращает ошибки."""
    errors: list[str] = []

    if "type" in schema:
        expected = schema["type"]
        options = expected if isinstance(expected, list) else [expected]
        if not any(_type_ok(value, opt) for opt in options):
            return [f"{path}: ожидался тип {expected}, получено {type(value).__name__}"]

    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} не из {schema['enum']}")

    if isinstance(value, str):
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(f"{path}: {value!r} не соответствует {schema['pattern']}")
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{path}: короче {schema['minLength']}")
        if schema.get("format") == "date" and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            errors.append(f"{path}: {value!r} не ISO-дата YYYY-MM-DD")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: {value} меньше {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: {value} больше {schema['maximum']}")

    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: отсутствует обязательное поле {key!r}")
        props = schema.get("properties", {})
        for key, sub in props.items():
            if key in value:
                errors.extend(validate_schema(value[key], sub, f"{path}.{key}"))
        extra = schema.get("additionalProperties")
        for key, sub in value.items():
            if key in props:
                continue
            if extra is False:
                errors.append(f"{path}: лишнее поле {key!r}")
            elif isinstance(extra, dict):
                errors.extend(validate_schema(sub, extra, f"{path}.{key}"))

    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{path}: меньше {schema['minItems']} элементов")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for i, item in enumerate(value):
                errors.extend(validate_schema(item, item_schema, f"{path}[{i}]"))

    return errors


# --------------------------------------------------------------------------- #
# Доменные проверки
# --------------------------------------------------------------------------- #
def _walk(value: Any, path: str = "$"):
    yield path, value
    if isinstance(value, dict):
        for k, v in value.items():
            yield from _walk(v, f"{path}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _walk(v, f"{path}[{i}]")


def check_provenance(profile: dict) -> list[str]:
    errors = []
    sources = {s["id"] for s in profile.get("sources", [])}
    if len(sources) != len(profile.get("sources", [])):
        errors.append("sources: повторяющиеся id")

    refs = [
        ("character.source_id", profile.get("character", {}).get("source_id")),
        ("observed.source_id", profile.get("observed", {}).get("source_id")),
        ("imported.source_id", profile.get("imported", {}).get("source_id")),
    ]
    for path, ref in refs:
        if ref is not None and ref not in sources:
            errors.append(f"{path}: ссылка на неизвестный источник {ref!r}")

    for i, sc in enumerate(profile.get("calculated", {}).get("scenarios", [])):
        ref = sc.get("source_id")
        if ref not in sources:
            errors.append(f"calculated.scenarios[{i}].source_id: неизвестный источник {ref!r}")

    # config_rationale должен покрывать все ключи конфигурации
    for i, sc in enumerate(profile.get("calculated", {}).get("scenarios", [])):
        cfg = sc.get("config", {})
        rationale = sc.get("config_rationale", {})
        missing = sorted(set(cfg) - set(rationale))
        if missing:
            errors.append(
                f"calculated.scenarios[{i}].config_rationale: нет обоснования для {missing}"
            )
    return errors


def check_no_calculated_outside_scenarios(profile: dict) -> list[str]:
    errors = []
    for key in profile:
        if key.lower() in FORBIDDEN_TOP_LEVEL:
            errors.append(f"${key}: расчётные данные вне calculated.scenarios")
    return errors


def check_resistances(profile: dict) -> list[str]:
    """Пересчитывает сопротивления каждого сценария из неcapped-значений."""
    errors = []
    baseline = profile.get("calculated", {}).get("resistance_baseline", {})
    uncapped = baseline.get("uncapped")
    if not uncapped:
        return ["calculated.resistance_baseline.uncapped: отсутствует, сопротивления не проверить"]

    for sc in profile.get("calculated", {}).get("scenarios", []):
        sid = sc.get("id", "?")
        penalty = sc.get("config", {}).get("resistancePenalty")
        if penalty is None:
            errors.append(f"{sid}: нет resistancePenalty в конфигурации")
            continue
        got = sc.get("defence", {}).get("resistances", {})
        for element in ELEMENTAL:
            raw = uncapped.get(element)
            if raw is None:
                errors.append(f"calculated.resistance_baseline.uncapped.{element}: отсутствует")
                continue
            expected = min(raw + penalty, RESIST_CAP)
            actual = got.get(element)
            if actual is None:
                errors.append(f"{sid}: нет сопротивления {element}")
            elif abs(expected - actual) > 0.5:
                errors.append(
                    f"{sid}: {element} = {actual}, ожидалось {expected:.0f} "
                    f"(uncapped {raw} + штраф {penalty}, кап {RESIST_CAP:.0f})"
                )
        chaos_expected = uncapped.get("chaos")
        if chaos_expected is not None and abs(got.get("chaos", -999) - chaos_expected) > 0.5:
            errors.append(f"{sid}: chaos = {got.get('chaos')}, ожидалось {chaos_expected}")
    return errors


def check_resistance_baseline(profile: dict) -> list[str]:
    """Проверяет происхождение и арифметику `calculated.resistance_baseline`.

    uncapped-сопротивления нельзя хранить в `imported`: клиент и движок показывают
    только значение после штрафа и капа. Значит, это выход движка, и он обязан
    лежать в `calculated` с источником kind=pob2_engine и с измерениями, из которых
    выведен.
    """
    errors: list[str] = []
    baseline = profile.get("calculated", {}).get("resistance_baseline")
    if not baseline:
        return [
            "calculated.resistance_baseline: отсутствует — происхождение "
            "uncapped-сопротивлений не зафиксировано"
        ]

    imported = profile.get("imported", {})
    if "uncapped_resistances" in imported:
        errors.append(
            "imported.uncapped_resistances: значения движка нельзя держать в разделе импорта; "
            "перенесите их в calculated.resistance_baseline"
        )

    sources = {s["id"]: s for s in profile.get("sources", [])}
    source_id = baseline.get("source_id")
    source = sources.get(source_id)
    if source is None:
        errors.append(
            f"calculated.resistance_baseline.source_id: неизвестный источник {source_id!r}"
        )
    elif source.get("kind") != "pob2_engine":
        errors.append(
            f"calculated.resistance_baseline.source_id: источник {source_id!r} имеет kind="
            f"{source.get('kind')!r}, а uncapped-значения выводятся только из расчётов движка"
        )

    uncapped = baseline.get("uncapped", {})
    scenarios = {sc.get("id"): sc for sc in profile.get("calculated", {}).get("scenarios", [])}
    penalties = []
    for i, row in enumerate(baseline.get("evidence", [])):
        penalty = row.get("resistancePenalty")
        total = row.get("total", {})
        penalties.append(penalty)
        if penalty is None:
            errors.append(f"calculated.resistance_baseline.evidence[{i}]: нет resistancePenalty")
            continue
        for element in ELEMENTAL:
            raw = uncapped.get(element)
            if raw is None:
                errors.append(f"calculated.resistance_baseline.uncapped.{element}: отсутствует")
                continue
            expected = raw + penalty
            actual = total.get(element)
            if actual is None:
                errors.append(
                    f"calculated.resistance_baseline.evidence[{i}].total.{element}: отсутствует"
                )
            elif abs(expected - actual) > 0.5:
                errors.append(
                    f"calculated.resistance_baseline.evidence[{i}]: {element} = {actual}, "
                    f"ожидалось {expected:.0f} (uncapped {raw} + штраф {penalty})"
                )
        chaos = uncapped.get("chaos")
        if chaos is not None and abs(total.get("chaos", -999) - chaos) > 0.5:
            errors.append(
                f"calculated.resistance_baseline.evidence[{i}]: chaos = {total.get('chaos')}, "
                f"ожидалось {chaos} (штраф акта не меняет хаос)"
            )
        scenario_id = row.get("scenario_id")
        if scenario_id is not None:
            scenario = scenarios.get(scenario_id)
            if scenario is None:
                errors.append(
                    f"calculated.resistance_baseline.evidence[{i}].scenario_id: "
                    f"неизвестный сценарий {scenario_id!r}"
                )
            else:
                if scenario.get("config", {}).get("resistancePenalty") != penalty:
                    errors.append(
                        f"calculated.resistance_baseline.evidence[{i}]: штраф {penalty} не совпадает "
                        f"со штрафом сценария {scenario_id!r}"
                    )
                got = scenario.get("defence", {}).get("resistances", {})
                for element in ELEMENTAL + ("chaos",):
                    expected = min(total.get(element, -999), RESIST_CAP)
                    if abs(got.get(element, -999) - expected) > 0.5:
                        errors.append(
                            f"calculated.resistance_baseline.evidence[{i}]: сценарий {scenario_id!r} "
                            f"показывает {element} = {got.get(element)}, ожидалось {expected:.0f} "
                            f"(total {total.get(element)} после капа {RESIST_CAP:.0f})"
                        )

    reference = baseline.get("penalty_reference")
    if reference is not None and reference not in penalties:
        errors.append(
            "calculated.resistance_baseline.penalty_reference: нет измерения с этим штрафом "
            f"({reference}) в evidence"
        )
    return errors


def check_spirit(profile: dict) -> list[str]:
    errors = []
    spirit = profile.get("imported", {}).get("spirit_reservations")
    if not spirit:
        return ["imported.spirit_reservations: отсутствует"]

    maximum = spirit.get("maximum")
    free = spirit.get("free")
    total = spirit.get("total_reserved")
    entries = spirit.get("entries", [])

    if maximum is None or free is None or total is None:
        return ["imported.spirit_reservations: неполные maximum/free/total_reserved"]

    if abs((maximum - total) - free) > 0.01:
        errors.append(
            f"дух: максимум {maximum} - резерв {total} = {maximum - total}, но free = {free}"
        )

    summed = sum(e.get("spirit", 0) for e in entries)
    if abs(summed - total) > 0.01:
        errors.append(f"дух: сумма резервов по способностям {summed} != total_reserved {total}")

    by_name = {e["ability"]: e for e in entries}
    for combo in spirit.get("simultaneous_combinations", []):
        names = combo.get("combination", [])
        used = 0.0
        for name in names:
            entry = by_name.get(name)
            if entry is None:
                errors.append(f"дух: комбинация ссылается на неизвестную способность {name!r}")
                continue
            gate = entry.get("conditional_on")
            if gate is None or gate in names:
                used += entry.get("spirit", 0)
        if abs(used - combo.get("spirit_used", -1)) > 0.01:
            errors.append(
                f"дух: комбинация {names} = {combo.get('spirit_used')}, по способностям {used}"
            )
        if combo.get("fits") != (used <= maximum):
            errors.append(
                f"дух: комбинация {names} помечена fits={combo.get('fits')}, "
                f"но {used} <= {maximum} = {used <= maximum}"
            )
    return errors


def check_scenario_skills(profile: dict) -> list[str]:
    errors = []
    groups = {g["group"] for g in profile.get("imported", {}).get("skill_gems", [])}
    for sc in profile.get("calculated", {}).get("scenarios", []):
        sid = sc.get("id", "?")
        seen = set()
        for row in sc.get("skills", []):
            group = row.get("group")
            if group not in groups:
                errors.append(f"{sid}: группа умений {group} отсутствует в imported.skill_gems")
            if group in seen:
                errors.append(f"{sid}: группа {group} указана дважды")
            seen.add(group)
            if row.get("total_dps", 0) < 0 or row.get("average_hit", 0) < 0:
                errors.append(f"{sid}: отрицательный урон в группе {group}")
    return errors


def check_equipment(profile: dict) -> list[str]:
    errors = []
    slots = [e["slot"] for e in profile.get("imported", {}).get("equipment", [])]
    if len(slots) != len(set(slots)):
        dupes = sorted({s for s in slots if slots.count(s) > 1})
        errors.append(f"imported.equipment: повторяющиеся слоты {dupes}")
    return errors


def check_secrets_and_xml(profile: dict, name: str) -> list[str]:
    errors = []
    for path, value in _walk(profile):
        leaf_key = re.sub(r"\[\d+\]$", "", path.rsplit(".", 1)[-1])
        if SECRET_KEYS.match(leaf_key):
            errors.append(f"{name}:{path}: запрещённое поле {leaf_key!r}")
        if not isinstance(value, str):
            continue
        for pattern in SECRET_PATTERNS:
            if pattern.search(value):
                errors.append(f"{name}:{path}: похоже на секрет ({pattern.pattern})")
        if leaf_key not in SHA256_FIELDS and HEX_BLOB.search(value):
            errors.append(f"{name}:{path}: длинная hex-строка вне поля sha256")
        for marker in XML_MARKERS:
            if marker in value:
                errors.append(f"{name}:{path}: встроенный сырой XML/текст предмета")
    return errors


def check_history() -> list[str]:
    errors = []
    if not HISTORY_DIR.is_dir():
        return [f"{HISTORY_DIR.relative_to(ROOT)}: каталог истории отсутствует"]
    for path in sorted(HISTORY_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"{path.relative_to(ROOT)}: невалидный JSON ({exc})")
            continue
        if "schema_version" not in data:
            errors.append(f"{path.relative_to(ROOT)}: нет schema_version")
    return errors


def validate_profile(path: Path, schema: dict) -> list[str]:
    name = path.relative_to(ROOT).as_posix()
    try:
        profile = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"{name}: невалидный JSON ({exc})"]

    errors = [f"{name}: {e}" for e in validate_schema(profile, schema)]
    if errors:
        # структурные ошибки делают доменные проверки бессмысленными
        return errors

    for check in (
        check_provenance,
        check_no_calculated_outside_scenarios,
        check_resistance_baseline,
        check_resistances,
        check_spirit,
        check_scenario_skills,
        check_equipment,
    ):
        errors.extend(f"{name}: {e}" for e in check(profile))
    errors.extend(check_secrets_and_xml(profile, name))
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="вывод в JSON")
    args = parser.parse_args(argv)

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    profiles = sorted(p for p in CHARACTERS_DIR.glob("*.json"))

    errors: list[str] = []
    checked: list[str] = []
    if not profiles:
        errors.append("data/characters: не найдено ни одного профиля")
    for path in profiles:
        checked.append(path.relative_to(ROOT).as_posix())
        errors.extend(validate_profile(path, schema))
    errors.extend(check_history())

    if args.json:
        print(json.dumps({"checked": checked, "errors": errors}, ensure_ascii=False, indent=1))
    else:
        for item in checked:
            print(f"[ OK ] профиль найден: {item}")
        if errors:
            print(f"\n[FAIL] ошибок: {len(errors)}")
            for err in errors:
                print(f"  - {err}")
        else:
            print(f"\n[ OK ] ошибок нет, проверено профилей: {len(checked)}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
