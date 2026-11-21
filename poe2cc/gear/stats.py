"""Канонические ключи характеристик и их свойства.

Здесь нет игровой математики: только словарь «как называть величину» и то, можно
ли её складывать из текста предмета. Любая величина, которую нельзя получить
сложением объявленных модификаторов, помечается `additive=False` — её считает
только движок PoB2.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StatMeta:
    key: str
    label: str
    unit: str
    #: можно ли получить изменение простой суммой объявленных модификаторов
    additive: bool
    #: влияет ли величина на итоговую оценку предмета
    material: bool
    #: вес в оценке на одну единицу (для процентов — на один процентный пункт)
    weight: float = 0.0


_STATS = (
    StatMeta("life", "Здоровье", "flat", additive=True, material=True, weight=0.5),
    StatMeta("mana", "Мана", "flat", additive=True, material=True, weight=0.1),
    StatMeta(
        "energy_shield", "Энергетический щит", "flat", additive=False, material=True, weight=0.35
    ),
    StatMeta("armour", "Броня", "flat", additive=False, material=True, weight=0.08),
    StatMeta("evasion", "Уклонение", "flat", additive=False, material=True, weight=0.08),
    StatMeta(
        "stun_threshold", "Порог оглушения", "flat", additive=True, material=False, weight=0.02
    ),
    StatMeta("spirit", "Дух", "flat", additive=True, material=False, weight=0.4),
    StatMeta("strength", "Сила", "flat", additive=True, material=False, weight=0.1),
    StatMeta("dexterity", "Ловкость", "flat", additive=True, material=False, weight=0.1),
    StatMeta("intelligence", "Интеллект", "flat", additive=True, material=False, weight=0.1),
    StatMeta(
        "fire_resistance", "Сопротивление огню", "percent", additive=True, material=True, weight=3.0
    ),
    StatMeta(
        "cold_resistance",
        "Сопротивление холоду",
        "percent",
        additive=True,
        material=True,
        weight=3.0,
    ),
    StatMeta(
        "lightning_resistance",
        "Сопротивление молнии",
        "percent",
        additive=True,
        material=True,
        weight=3.0,
    ),
    StatMeta(
        "chaos_resistance",
        "Сопротивление хаосу",
        "percent",
        additive=True,
        material=True,
        weight=3.0,
    ),
    StatMeta(
        "movement_speed",
        "Скорость передвижения",
        "percent",
        additive=False,
        material=True,
        weight=0.6,
    ),
    StatMeta("life_percent", "Здоровье (%)", "percent", additive=False, material=False),
    StatMeta("mana_percent", "Мана (%)", "percent", additive=False, material=False),
    StatMeta(
        "energy_shield_percent", "Энергетический щит (%)", "percent", additive=False, material=False
    ),
    StatMeta("armour_percent", "Броня (%)", "percent", additive=False, material=False),
    StatMeta("evasion_percent", "Уклонение (%)", "percent", additive=False, material=False),
)

STATS: dict[str, StatMeta] = {meta.key: meta for meta in _STATS}

#: Модификаторы с этими ключами расширяются в несколько характеристик.
EXPANSIONS: dict[str, tuple[str, ...]] = {
    "all_attributes": ("strength", "dexterity", "intelligence"),
    "all_elemental_resistance": ("fire_resistance", "cold_resistance", "lightning_resistance"),
}

ELEMENTAL_RESISTANCES = ("fire_resistance", "cold_resistance", "lightning_resistance")
RESISTANCES = ELEMENTAL_RESISTANCES + ("chaos_resistance",)

#: Соответствие ключей характеристик полям `get_stats` движка.
ENGINE_FIELDS: dict[str, str] = {
    "life": "Life",
    "mana": "Mana",
    "energy_shield": "EnergyShield",
    "armour": "Armour",
    "evasion": "Evasion",
    "stun_threshold": "StunThreshold",
    "spirit": "SpiritUnreserved",
    "strength": "Str",
    "dexterity": "Dex",
    "intelligence": "Int",
    "fire_resistance": "FireResist",
    "cold_resistance": "ColdResist",
    "lightning_resistance": "LightningResist",
    "chaos_resistance": "ChaosResist",
    "movement_speed": "MovementSpeedMod",
}

#: Сопротивления до капа (после штрафа акта) — отдельные поля движка.
ENGINE_UNCAPPED_FIELDS: dict[str, str] = {
    "fire_resistance": "FireResistTotal",
    "cold_resistance": "ColdResistTotal",
    "lightning_resistance": "LightningResistTotal",
    "chaos_resistance": "ChaosResistTotal",
}

ENGINE_ATTRIBUTE_REQUIREMENTS = {
    "strength": "ReqStr",
    "dexterity": "ReqDex",
    "intelligence": "ReqInt",
}


def label(key: str) -> str:
    meta = STATS.get(key)
    return meta.label if meta else key


def unit(key: str) -> str:
    meta = STATS.get(key)
    return meta.unit if meta else "flat"


def is_material(key: str) -> bool:
    meta = STATS.get(key)
    return bool(meta and meta.material)


def is_additive(key: str) -> bool:
    meta = STATS.get(key)
    return bool(meta and meta.additive)


def weight(key: str) -> float:
    meta = STATS.get(key)
    return meta.weight if meta else 0.0
