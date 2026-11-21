"""Тестовые двойники движка PoB2.

Здесь нет «второго PoB2»: это маленькая детерминированная заглушка, которая
повторяет протокол `PobEngine` и умеет ровно то, что нужно тестам — применить
объявленные эффекты предмета к заранее заданным базовым числам. Реальные числа
проверяются отдельными интеграционными тестами на настоящем `pob-mcp`.
"""

from __future__ import annotations

import re
from typing import Any

from poe2cc.gear.engine import EngineCalculationError, EngineInfo, EngineUnavailable

#: Ботинки, которые «уже надеты» в тестовом билде: их сопротивление входит в базу.
CURRENT_BOOTS_TEXT = """Rarity: RARE
Victory League
Silk Slippers
LevelReq: 36
+13% to Fire Resistance
+19% to Cold Resistance
"""

_RESIST_LINE = re.compile(r"([+-]\d+)% to (Fire|Cold|Lightning|Chaos) Resistance", re.IGNORECASE)
_RESIST_FIELDS = {
    "fire": ("FireResist", "FireResistTotal"),
    "cold": ("ColdResist", "ColdResistTotal"),
    "lightning": ("LightningResist", "LightningResistTotal"),
    "chaos": ("ChaosResist", "ChaosResistTotal"),
}


def resistances_of(item_text: str) -> dict[str, float]:
    result: dict[str, float] = {}
    for amount, element in _RESIST_LINE.findall(item_text or ""):
        key = element.lower()
        result[key] = result.get(key, 0.0) + float(amount)
    return result


class FakeEngine:
    """Детерминированный двойник движка.

    `base_stats` — «числа персонажа до замены». При `equip_item` к ним
    добавляются аддитивные эффекты, найденные в тексте предмета по таблице
    `effects` (ключ — название предмета в первой содержательной строке).
    """

    def __init__(
        self,
        base_stats: dict[str, Any] | None = None,
        effects: dict[str, dict[str, float]] | None = None,
        *,
        unavailable: bool = False,
        fail_on_equip: str | None = None,
        info: EngineInfo | None = None,
        current_item_text: str | None = CURRENT_BOOTS_TEXT,
    ) -> None:
        self.base_stats = dict(base_stats or DEFAULT_BASE_STATS)
        self.effects = effects or {}
        self.unavailable = unavailable
        self.fail_on_equip = fail_on_equip
        self.info = info or EngineInfo(
            command="fake-pob-mcp",
            transport="test double",
            pob2_version="0.23.1-test",
            tree_data_version="0_5",
        )
        self.config_calls: list[tuple[str, Any]] = []
        self.loaded_build: str | None = None
        self.equipped: list[tuple[str, str | None]] = []
        self.closed = False
        self.started = False
        self._current = dict(self.base_stats)
        self._config: dict[str, Any] = {}
        self.current_item_text = current_item_text
        self._slot_resistances = resistances_of(current_item_text or "")

    # -- жизненный цикл ----------------------------------------------------- #
    def start(self) -> None:
        self.started = True

    def close(self) -> None:
        self.closed = True

    # -- протокол движка ---------------------------------------------------- #
    def load_build(self, source: str) -> dict:
        if self.unavailable:
            raise EngineUnavailable("pob-mcp не найден (тестовый двойник)")
        self.loaded_build = source
        self._current = dict(self.base_stats)
        self._slot_resistances = resistances_of(self.current_item_text or "")
        return {"loaded": True}

    def set_config(self, var: str, value: Any) -> None:
        self.config_calls.append((var, value))
        self._config[var] = value

    def get_stats(self, fields: list[str] | None = None) -> dict[str, Any]:
        if fields is None:
            return dict(self._current)
        return {field: self._current[field] for field in fields if field in self._current}

    def get_skills(self) -> dict:
        return {
            "mainSocketGroup": 1,
            "socketGroups": [
                {
                    "index": 1,
                    "isMainSkill": True,
                    "gems": [{"nameSpec": "Fragmentation Rounds", "level": 12}],
                }
            ],
        }

    def get_items(self) -> dict:
        return {"slots": []}

    def equip_item(self, item_text: str, slot: str | None = None) -> dict:
        if self.fail_on_equip and self.fail_on_equip in item_text:
            raise EngineCalculationError(
                "Item.lua:1406: attempt to concatenate field 'baseName' (a nil value)"
            )
        self.equipped.append((item_text, slot))
        name = _item_name(item_text)
        for field, delta in self.effects.get(name, {}).items():
            self._current[field] = self._current.get(field, 0.0) + delta
        self._apply_resistances(item_text)
        self._recompute_derived()
        return {"slot": slot, "itemName": name}

    def unequip_item(self, slot: str) -> dict:
        self._current = dict(self.base_stats)
        return {"slot": slot}

    def sanity_check(self) -> list[str]:
        return []

    # -- вспомогательное ---------------------------------------------------- #
    def _apply_resistances(self, item_text: str) -> None:
        """Меняет сопротивления на разницу между старым и новым предметом в слоте."""
        new = resistances_of(item_text)
        for element, (capped_field, total_field) in _RESIST_FIELDS.items():
            delta = new.get(element, 0.0) - self._slot_resistances.get(element, 0.0)
            if not delta:
                continue
            total = float(self._current.get(total_field, 0.0)) + delta
            self._current[total_field] = total
            self._current[capped_field] = min(total, 75.0)
        self._slot_resistances = new

    def _recompute_derived(self) -> None:
        """Держит производные числа согласованными, как это делает PoB2."""
        life = self._current.get("Life")
        if life is not None:
            # EHP пропорционален пулу здоровья: этого достаточно для проверки
            # того, что анализатор берёт EHP из движка, а не считает сам
            self._current["TotalEHP"] = round(float(life) * 2.35, 2)


def _item_name(item_text: str) -> str:
    lines = [line.strip() for line in item_text.splitlines() if line.strip()]
    if len(lines) >= 2 and lines[0].lower().startswith("rarity:"):
        return lines[1]
    return lines[0] if lines else ""


DEFAULT_BASE_STATS: dict[str, Any] = {
    "Life": 947.0,
    "Mana": 412.0,
    "EnergyShield": 238.0,
    "Armour": 300.0,
    "Evasion": 235.0,
    "StunThreshold": 1007.0,
    "SpiritUnreserved": -40.0,
    "Str": 67.0,
    "Dex": 97.0,
    "Int": 46.0,
    "ReqStr": 41.0,
    "ReqDex": 65.0,
    "ReqInt": 38.0,
    "FireResist": 75.0,
    "ColdResist": 46.0,
    "LightningResist": 35.0,
    "ChaosResist": 0.0,
    "FireResistTotal": 89.0,
    "ColdResistTotal": 46.0,
    "LightningResistTotal": 35.0,
    "ChaosResistTotal": 0.0,
    "MovementSpeedMod": 0.96,
    "TotalDPS": 67.01,
    "TotalEHP": 2227.91,
}


class FailingEngine(FakeEngine):
    """Движок, который падает на любом вызове: проверка деградации."""

    def load_build(self, source: str) -> dict:
        raise EngineCalculationError("движок вернул некорректный ответ (тестовый двойник)")
