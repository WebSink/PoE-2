"""Разбор предметов: текст из игры, структурированный JSON, PoB2-XML."""

from __future__ import annotations

import json

import pytest

from poe2cc.gear import (
    ItemParseError,
    items_from_xml,
    load_candidate,
    parse_item_json,
    parse_item_text,
)


def test_parse_copied_text_keeps_header_and_mods(boots_text):
    item = parse_item_text(boots_text, slot="boots")

    assert item.name == "Victory League"
    assert item.base == "Silk Slippers"
    assert item.rarity == "RARE"
    assert item.slot == "Boots"  # слот нормализован
    assert item.required_level == 36
    assert item.item_level == 60
    assert item.defences == {"energy_shield": 79.0}
    assert len(item.mods) == 6
    assert all(mod.status == "resolved" for mod in item.mods)
    assert item.engine_ready
    assert item.engine_blockers() == []


def test_parse_text_splits_implicits(boots_text):
    text = boots_text.replace("LevelReq: 36", "LevelReq: 36\nImplicits: 1\n+10 to Strength")
    item = parse_item_text(text, slot="Boots")

    kinds = [mod.kind for mod in item.mods]
    assert kinds[0] == "implicit"
    assert set(kinds[1:]) == {"explicit"}


def test_parse_text_requires_level_and_attributes():
    text = """Rarity: RARE
Iron Guard
Plated Vest
Item Level: 60
LevelReq: 40
Requires: Level 40, 35 Str, 20 Dex
Armour: 300
+70 to maximum Life
"""
    item = parse_item_text(text, slot="Body Armour")

    assert item.required_level == 40
    assert item.attribute_requirements == {
        "strength": 35.0,
        "dexterity": 20.0,
        # строка Requires перечисляет все требования: нет интеллекта — нет требования
        "intelligence": 0.0,
    }
    assert item.defences == {"armour": 300.0}


def test_parse_text_rejects_empty_input():
    with pytest.raises(ItemParseError):
        parse_item_text("   \n  ")


def test_parse_text_keeps_unknown_mods_verbatim():
    text = """Rarity: RARE
Strange Boots
Silk Slippers
LevelReq: 36
+5 to Level of all Fire Skills
"""
    item = parse_item_text(text, slot="Boots")

    assert len(item.unknown_mods) == 1
    assert item.unknown_mods[0].text == "+5 to Level of all Fire Skills"
    assert item.unknown_mods[0].status == "unknown"
    # сырой текст сохраняется целиком, чтобы ничего не потерялось
    assert "+5 to Level of all Fire Skills" in item.raw_text


def test_item_without_mods_is_not_engine_ready():
    text = """Rarity: RARE
Broken
Silk Slippers
"""
    item = parse_item_text(text, slot="Boots")

    assert not item.engine_ready
    assert item.engine_blockers() == ["нет ни одного модификатора"]
    with pytest.raises(ItemParseError):
        item.item_text_for_engine()


def test_parse_json_with_normalised_stats():
    item = parse_item_json(
        {
            "name": "Test Boots",
            "slot": "Boots",
            "required_level": 45,
            "defences": {"armour": 115, "energy_shield": 34},
            "mods": [
                {"stat": "life", "value": 83},
                {"text": "20% increased Movement Speed"},
            ],
            "declared_totals": {"life": 83},
        }
    )

    assert item.source_format == "structured_json"
    assert item.declared.value("life") == 83.0
    assert item.defences == {"armour": 115.0, "energy_shield": 34.0}
    assert any(mod.effects == (("movement_speed", 20.0),) for mod in item.mods)


def test_parse_json_rejects_unknown_stat():
    with pytest.raises(ItemParseError, match="неизвестная характеристика"):
        parse_item_json({"name": "X", "mods": [{"stat": "dps", "value": 10}]})


def test_parse_json_rejects_bad_rarity():
    with pytest.raises(ItemParseError, match="редкость"):
        parse_item_json({"name": "X", "rarity": "MYTHIC"})


def test_load_candidate_autodetects_formats(tmp_path, boots_text):
    text_file = tmp_path / "item.txt"
    text_file.write_text(boots_text, encoding="utf-8")
    json_file = tmp_path / "item.json"
    json_file.write_text(
        json.dumps({"name": "Json Boots", "slot": "Boots", "mods": []}), encoding="utf-8"
    )

    assert load_candidate(text_file, slot="Boots").source_format == "poe2_text"
    assert load_candidate(json_file, slot="Boots").source_format == "structured_json"
    assert load_candidate({"name": "Dict", "mods": []}, slot="Boots").name == "Dict"


def test_load_candidate_unknown_extension(tmp_path):
    path = tmp_path / "item.yaml"
    path.write_text("name: x", encoding="utf-8")
    with pytest.raises(ItemParseError):
        load_candidate(path, slot="Boots")


def test_items_from_xml_reads_active_item_set(fixture_build):
    items = items_from_xml(fixture_build.read_text(encoding="utf-8"))

    assert set(items) == {"Boots", "Body Armour"}
    assert items["Boots"].provenance == {"kind": "pob2_xml", "item_id": "13"}
    assert items["Boots"].defences == {"energy_shield": 79.0}
    assert items["Body Armour"].attribute_requirements["strength"] == 35.0


def test_items_from_xml_rejects_broken_xml():
    with pytest.raises(ItemParseError, match="XML"):
        items_from_xml("<PathOfBuilding2><Items>")


# --------------------------------------------------------------------------- #
# Полнота списка локальной защиты (review S5.1.1, пункт 3)
# --------------------------------------------------------------------------- #


def test_text_item_defences_are_complete(boots_text):
    """В тексте из игры перечислены все защиты: отсутствие строки = ноль."""
    item = parse_item_text(boots_text)

    assert item.defences_complete is True
    assert item.defences == {"energy_shield": 79.0}
    assert item.as_dict()["defences_complete"] is True


def test_json_item_defences_are_incomplete_by_default():
    item = parse_item_json({"name": "Manual", "mods": [{"text": "+10 to maximum Life"}]})

    assert item.defences_complete is False


def test_json_item_can_declare_defences_complete():
    item = parse_item_json(
        {
            "name": "Manual",
            "mods": [{"text": "+10 to maximum Life"}],
            "defences": {"armour": 115},
            "defences_complete": True,
        }
    )

    assert item.defences_complete is True
    assert item.defences == {"armour": 115.0}


def test_xml_item_defences_are_complete(fixture_build):
    items = items_from_xml(fixture_build.read_text(encoding="utf-8"))

    assert items["Boots"].defences_complete is True
