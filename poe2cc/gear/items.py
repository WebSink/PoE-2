"""Модель предмета и три способа его получить.

Поддерживаются ровно три источника (по заданию S5.1):

* `poe2_text` — текст, скопированный из Path of Exile 2 (или из `<Item>` в PoB2);
* `structured_json` — ручной структурированный ввод владельца;
* `pob2_xml` — предмет, уже надетый в PoB2-экспорте (для «текущей» вещи).

Нормализованные свойства в JSON — это те же `mods`, но с `stat` + `value`
вместо `text`: их принимает `parse_item_json`.

Торговых скраперов и недокументированных API здесь нет и быть не может.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import modifiers, stats
from .modifiers import DeclaredProfile, ParsedMod, build_declared_profile

SOURCE_TEXT = "poe2_text"
SOURCE_JSON = "structured_json"
SOURCE_XML = "pob2_xml"

RARITIES = ("NORMAL", "MAGIC", "RARE", "UNIQUE")

#: Расширения файлов, которые считаются текстом предмета.
TEXT_SUFFIXES = frozenset({".txt", ".item", ".pob", ""})

#: Слоты, которые понимает PoB2. Регистр не важен, пробелы нормализуются.
KNOWN_SLOTS = (
    "Weapon 1",
    "Weapon 1 Swap",
    "Weapon 2",
    "Weapon 2 Swap",
    "Helmet",
    "Body Armour",
    "Gloves",
    "Boots",
    "Amulet",
    "Ring 1",
    "Ring 2",
    "Belt",
    "Charm 1",
    "Charm 2",
    "Charm 3",
    "Flask 1",
    "Flask 2",
    "Flask 3",
)

SLOT_ALIASES = {
    "boots": "Boots",
    "boot": "Boots",
    "shoes": "Boots",
    "helmet": "Helmet",
    "helm": "Helmet",
    "body armour": "Body Armour",
    "body armor": "Body Armour",
    "chest": "Body Armour",
    "gloves": "Gloves",
    "amulet": "Amulet",
    "belt": "Belt",
    "ring 1": "Ring 1",
    "ring1": "Ring 1",
    "ring 2": "Ring 2",
    "ring2": "Ring 2",
    "weapon 1": "Weapon 1",
    "weapon1": "Weapon 1",
    "weapon 2": "Weapon 2",
    "weapon2": "Weapon 2",
}

DEFENCE_KEYS = {
    "armour": "armour",
    "evasion": "evasion",
    "energy shield": "energy_shield",
    "ward": "ward",
}

_ATTRIBUTE_REQUIREMENT_KEYS = {
    "str": "strength",
    "strength": "strength",
    "dex": "dexterity",
    "dexterity": "dexterity",
    "int": "intelligence",
    "intelligence": "intelligence",
}


class ItemParseError(ValueError):
    """Предмет нельзя разобрать достоверно."""


def normalise_slot(slot: str | None) -> str | None:
    if slot is None:
        return None
    key = re.sub(r"\s+", " ", slot).strip().lower()
    if key in SLOT_ALIASES:
        return SLOT_ALIASES[key]
    for known in KNOWN_SLOTS:
        if known.lower() == key:
            return known
    return slot.strip()


@dataclass
class Item:
    """Предмет в нормализованном виде."""

    name: str
    slot: str | None = None
    base: str | None = None
    rarity: str | None = None
    item_class: str | None = None
    required_level: float | None = None
    item_level: float | None = None
    quality: float | None = None
    defences: dict[str, float] = field(default_factory=dict)
    #: True — в источнике перечислены все локальные защиты предмета, поэтому
    #: отсутствие ключа означает ноль, а не «неизвестно». Для текста из игры
    #: и XML это так по определению; в JSON полноту надо подтвердить явно.
    defences_complete: bool = False
    attribute_requirements: dict[str, float] = field(
        default_factory=lambda: {"strength": None, "dexterity": None, "intelligence": None}
    )
    mods: list[ParsedMod] = field(default_factory=list)
    declared_totals: dict[str, float] = field(default_factory=dict)
    runes: list[str] = field(default_factory=list)
    raw_text: str | None = None
    source_format: str = SOURCE_JSON
    provenance: dict[str, Any] = field(default_factory=dict)
    _declared: DeclaredProfile | None = field(default=None, repr=False, compare=False)

    # -- производные свойства ------------------------------------------------ #
    @property
    def declared(self) -> DeclaredProfile:
        if self._declared is None:
            self._declared = build_declared_profile(self.mods, self.declared_totals)
        return self._declared

    @property
    def unknown_mods(self) -> list[ParsedMod]:
        return self.declared.unknown_mods

    @property
    def engine_ready(self) -> bool:
        """Достаточно ли данных, чтобы воспроизвести предмет в движке."""
        return (
            self.source_format in (SOURCE_TEXT, SOURCE_XML)
            and bool(self.rarity)
            and bool(self.base)
            and bool(self.mods)
            and self.raw_text is not None
        )

    def engine_blockers(self) -> list[str]:
        blockers: list[str] = []
        if self.source_format not in (SOURCE_TEXT, SOURCE_XML):
            blockers.append(
                "предмет задан структурно, без текста PoB2: движок не сможет его разобрать"
            )
        if not self.base:
            blockers.append(
                "неизвестен базовый тип предмета: от него зависят требования атрибутов "
                "и локальная защита"
            )
        if not self.rarity:
            blockers.append("неизвестна редкость предмета")
        if not self.mods:
            blockers.append("нет ни одного модификатора")
        if self.raw_text is None:
            blockers.append("нет исходного текста предмета для PoB2")
        return blockers

    def item_text_for_engine(self) -> str:
        """Текст предмета для PoB2. Без модификаторов отдавать нечего."""
        if self.raw_text is None:
            raise ItemParseError("нет исходного текста предмета для PoB2")
        blockers = self.engine_blockers()
        if blockers:
            raise ItemParseError("предмет нельзя передать в PoB2: " + "; ".join(blockers))
        return self.raw_text

    def mods_summary(self) -> list[str]:
        return [mod.text for mod in self.mods]

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "slot": self.slot,
            "base": self.base,
            "rarity": self.rarity,
            "item_class": self.item_class,
            "required_level": self.required_level,
            "item_level": self.item_level,
            "quality": self.quality,
            "defences": dict(self.defences),
            "defences_complete": self.defences_complete,
            "attribute_requirements": dict(self.attribute_requirements),
            "runes": list(self.runes),
            "source_format": self.source_format,
            "engine_ready": self.engine_ready,
            "engine_blockers": self.engine_blockers(),
            "mods": [mod.as_dict() for mod in self.mods],
            "unknown_mods": [mod.text for mod in self.unknown_mods],
            "declared_totals": dict(self.declared_totals),
            "declared": {
                "contributions": [
                    contribution.as_dict() for contribution in self.declared.contributions.values()
                ],
                "warnings": list(self.declared.warnings),
            },
            "provenance": dict(self.provenance),
        }


# --------------------------------------------------------------------------- #
# Текст, скопированный из игры или из PoB2
# --------------------------------------------------------------------------- #
_SEPARATOR = re.compile(r"^-{3,}$")
_METADATA = (
    "unique id:",
    "item level:",
    "levelreq:",
    "quality:",
    "sockets:",
    "rune:",
    "soul core:",
    "charm slots:",
    "implicits:",
    "note:",
    "requires level",
    "requires:",
    "item class:",
    "stack size:",
    "limited to:",
)

_REQUIRES = re.compile(
    r"^requires(?:\s+level)?:?\s*(?:level\s*)?(?P<level>\d+)"
    r"(?P<rest>(?:\s*,\s*\d+\s*(?:str|dex|int|strength|dexterity|intelligence))*)",
    re.IGNORECASE,
)
_REQUIRES_ATTR = re.compile(r"(\d+)\s*(str|dex|int|strength|dexterity|intelligence)", re.IGNORECASE)
_DEFENCE_LINE = re.compile(
    r"^(armour|evasion|energy shield|ward):\s*(\d+(?:\.\d+)?)$", re.IGNORECASE
)


def parse_item_text(text: str, slot: str | None = None) -> Item:
    """Разбирает текст предмета PoE2 (или `<Item>`-блок PoB2)."""
    if not text or not text.strip():
        raise ItemParseError("пустой текст предмета")

    raw_lines = [line.rstrip() for line in text.replace("\r\n", "\n").split("\n")]
    lines = [line.strip() for line in raw_lines]
    header: list[str] = []
    body: list[str] = []

    rarity: str | None = None
    item_class: str | None = None
    required_level: float | None = None
    item_level: float | None = None
    quality: float | None = None
    defences: dict[str, float] = {}
    requirements = {"strength": None, "dexterity": None, "intelligence": None}
    runes: list[str] = []
    implicit_count = 0

    in_header = True
    for line in lines:
        if not line or _SEPARATOR.match(line):
            continue
        lowered = line.lower()

        if lowered.startswith("rarity:"):
            rarity = line.split(":", 1)[1].strip().upper()
            continue
        if lowered.startswith("item class:"):
            item_class = line.split(":", 1)[1].strip()
            continue
        if lowered.startswith("item level:"):
            item_level = _to_number(line.split(":", 1)[1])
            continue
        if lowered.startswith("levelreq:"):
            required_level = _to_number(line.split(":", 1)[1])
            continue
        if lowered.startswith("quality:"):
            quality = _to_number(line.split(":", 1)[1].replace("+", "").replace("%", ""))
            continue
        if lowered.startswith("rune:") or lowered.startswith("soul core:"):
            runes.append(line.split(":", 1)[1].strip())
            continue
        if lowered.startswith("implicits:"):
            implicit_count = int(_to_number(line.split(":", 1)[1]) or 0)
            in_header = False
            continue
        if lowered.startswith("charm slots:") or lowered.startswith("sockets:"):
            continue
        if lowered.startswith("unique id:") or lowered.startswith("note:"):
            continue
        if lowered.startswith("stack size:") or lowered.startswith("limited to:"):
            continue

        defence = _DEFENCE_LINE.match(line)
        if defence:
            defences[DEFENCE_KEYS[defence.group(1).lower()]] = float(defence.group(2))
            continue

        requires = _REQUIRES.match(line)
        if requires:
            if required_level is None:
                required_level = float(requires.group("level"))
            for amount, attribute in _REQUIRES_ATTR.findall(requires.group("rest") or ""):
                key = _ATTRIBUTE_REQUIREMENT_KEYS[attribute.lower()]
                requirements[key] = float(amount)
            continue

        if any(lowered.startswith(prefix) for prefix in _METADATA):
            continue

        if in_header:
            header.append(line)
            # название и базовый тип — первые две содержательные строки; всё,
            # что идёт дальше, — модификаторы (если нет явного «Implicits: N»)
            if len(header) >= 2:
                in_header = False
        else:
            body.append(line)

    if not header:
        raise ItemParseError("в тексте нет строки с названием предмета")

    name = header[0]
    base = header[1] if len(header) > 1 else None

    mods: list[ParsedMod] = []
    for index, line in enumerate(body):
        kind = "implicit" if index < implicit_count else "explicit"
        mods.append(modifiers.parse_mod(line, kind=kind))

    return Item(
        name=name,
        slot=normalise_slot(slot),
        base=base,
        rarity=rarity,
        item_class=item_class,
        required_level=required_level,
        item_level=item_level,
        quality=quality,
        defences=defences,
        defences_complete=True,
        attribute_requirements=requirements,
        mods=mods,
        runes=runes,
        raw_text=text.strip() + "\n",
        source_format=SOURCE_TEXT,
        provenance={"kind": "copied_item_text"},
    )


def _to_number(value: str) -> float | None:
    match = re.search(r"[+-]?\d+(?:\.\d+)?", value or "")
    return float(match.group(0)) if match else None


# --------------------------------------------------------------------------- #
# Ручной структурированный ввод / нормализованный JSON
# --------------------------------------------------------------------------- #
def parse_item_json(data: dict | str | Path) -> Item:
    """Принимает dict или путь к JSON-файлу с описанием предмета."""
    if isinstance(data, (str, Path)):
        path = Path(data)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ItemParseError(f"не читается JSON предмета {path}: {exc}") from exc
    else:
        payload = data
    if not isinstance(payload, dict):
        raise ItemParseError("JSON предмета должен быть объектом")

    name = payload.get("name")
    if not name:
        raise ItemParseError("в JSON предмета нет поля 'name'")

    mods: list[ParsedMod] = []
    for index, entry in enumerate(payload.get("mods") or []):
        if isinstance(entry, str):
            mods.append(modifiers.parse_mod(entry))
            continue
        if not isinstance(entry, dict):
            raise ItemParseError(f"mods[{index}]: ожидалась строка или объект")
        kind = entry.get("kind")
        if entry.get("stat"):
            stat = entry["stat"]
            if stat in stats.EXPANSIONS:
                effects = tuple(
                    (key, float(entry.get("value") or 0)) for key in stats.EXPANSIONS[stat]
                )
            elif stat in stats.STATS:
                effects = ((stat, float(entry.get("value") or 0)),)
            else:
                raise ItemParseError(f"mods[{index}]: неизвестная характеристика {stat!r}")
            mods.append(
                ParsedMod(
                    text=entry.get("text") or f"{stat} {entry.get('value')}",
                    kind=kind or "explicit",
                    effects=effects,
                    note="задано нормализованными свойствами",
                )
            )
            continue
        text = entry.get("text")
        if not text:
            raise ItemParseError(f"mods[{index}]: нужен 'text' или 'stat' + 'value'")
        mods.append(modifiers.parse_mod(text, kind=kind))

    declared_totals: dict[str, float] = {}
    for stat, value in (payload.get("declared_totals") or {}).items():
        if stat not in stats.STATS:
            raise ItemParseError(f"declared_totals: неизвестная характеристика {stat!r}")
        declared_totals[stat] = float(value)

    requirements = payload.get("attribute_requirements") or {}
    attribute_requirements = {
        "strength": _maybe_float(requirements.get("strength")),
        "dexterity": _maybe_float(requirements.get("dexterity")),
        "intelligence": _maybe_float(requirements.get("intelligence")),
    }

    defences = {
        DEFENCE_KEYS.get(str(key).lower(), str(key).lower()): float(value)
        for key, value in (payload.get("defences") or {}).items()
    }

    rarity = payload.get("rarity")
    if rarity is not None:
        rarity = str(rarity).upper()
        if rarity not in RARITIES:
            raise ItemParseError(f"неизвестная редкость {rarity!r}, ожидалось одно из {RARITIES}")

    return Item(
        name=str(name),
        slot=normalise_slot(payload.get("slot")),
        base=payload.get("base"),
        rarity=rarity,
        item_class=payload.get("item_class"),
        required_level=_maybe_float(payload.get("required_level")),
        item_level=_maybe_float(payload.get("item_level")),
        quality=_maybe_float(payload.get("quality")),
        defences=defences,
        defences_complete=bool(payload.get("defences_complete", False)),
        attribute_requirements=attribute_requirements,
        mods=mods,
        declared_totals=declared_totals,
        runes=list(payload.get("runes") or []),
        raw_text=payload.get("raw_text"),
        source_format=SOURCE_JSON,
        provenance=payload.get("provenance") or {"kind": "manual_structured_input"},
    )


def _maybe_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


# --------------------------------------------------------------------------- #
# Предмет из PoB2-экспорта
# --------------------------------------------------------------------------- #
@dataclass
class XmlItem:
    item_id: str
    slot: str
    item: Item


def items_from_xml(xml_text: str) -> dict[str, Item]:
    """Возвращает {слот: предмет} по активному набору предметов PoB2."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ItemParseError(f"PoB2-экспорт не разбирается как XML: {exc}") from exc

    raw_items: dict[str, str] = {}
    for element in root.iter("Item"):
        item_id = element.get("id")
        if item_id:
            raw_items[item_id] = element.text or ""

    slots: dict[str, str] = {}
    items_node = root.find(".//Items")
    item_set: ET.Element | None = None
    if items_node is not None:
        active = items_node.get("activeItemSet") or "1"
        for candidate in items_node.findall("ItemSet"):
            if candidate.get("id") == active:
                item_set = candidate
                break
        if item_set is None:
            item_set = items_node.find("ItemSet")
    if item_set is not None:
        for slot in item_set.findall("Slot"):
            slot_name = slot.get("name")
            item_id = slot.get("itemId")
            if slot_name and item_id and item_id != "0":
                slots[slot_name] = item_id

    result: dict[str, Item] = {}
    for slot_name, item_id in slots.items():
        text = raw_items.get(item_id)
        if not text:
            continue
        item = parse_item_text(text, slot=slot_name)
        item.source_format = SOURCE_XML
        item.provenance = {"kind": "pob2_xml", "item_id": item_id}
        result[normalise_slot(slot_name) or slot_name] = item
    return result


def item_in_slot(xml_text: str, slot: str) -> Item | None:
    return items_from_xml(xml_text).get(normalise_slot(slot) or slot)


# --------------------------------------------------------------------------- #
# Единая точка входа
# --------------------------------------------------------------------------- #
def load_candidate(source: str | Path | dict, slot: str | None = None) -> Item:
    """Определяет формат по содержимому: JSON-файл, текст предмета или dict."""
    if isinstance(source, dict):
        item = parse_item_json(source)
        item.slot = normalise_slot(slot) or item.slot
        return item

    path = Path(source)
    if path.exists():
        text = path.read_text(encoding="utf-8")
        if path.suffix.lower() == ".json" or text.lstrip().startswith("{"):
            item = parse_item_json(path)
            item.slot = normalise_slot(slot) or item.slot
            return item
        if path.suffix.lower() not in TEXT_SUFFIXES:
            raise ItemParseError(
                f"неизвестный формат файла {path.name!r}: ожидался .json или текст предмета "
                f"({', '.join(sorted(TEXT_SUFFIXES))})"
            )
        return parse_item_text(text, slot=slot)

    return parse_item_text(str(source), slot=slot)


def format_mods(mods: Iterable[ParsedMod]) -> list[str]:
    return [mod.text for mod in mods]
