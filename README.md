# PoE-2 🚀

Рабочий репозиторий для анализа билдов и подбора экипировки **Path of Exile 2**.

## Текущие данные

- [Профиль Sinkov (JSON)](data/characters/sinkov.json) — schema 2.0.0, построен из реального импорта PoB2:
  разделы `observed` / `imported` / `calculated` / `unverified`.
- [Схема профиля](docs/character-profile-schema.md) — модель достоверности и автоматические проверки.
- [Аудит Sinkov по движку PoB2](docs/sinkov-pob-audit.md) — актуальные числа, сценарии урона, разбор духа.
- [История наблюдений](docs/sinkov-build-audit.md) — более ранний аудит по скриншотам (устарел по числам).

Актуальные характеристики рассчитаны движком Path of Building 2 и привязаны к конфигурации
сценария (штраф сопротивлений, уровень и тип цели). Исторический снимок со скриншотов лежит
в `data/characters/history/`. Никаких торговых сделок или автоматического доступа к аккаунту
этот репозиторий не выполняет.

## Инфраструктура разработки

- [AGENTS.md](AGENTS.md) — правила для агентов и разработчиков.
- [Архитектура](docs/architecture.md) — модули и контракты данных.
- [MCP-статус](docs/integrations/mcp-status.md) — PoB2/pob-mcp и проверки.
- [Импорт персонажа в PoB2](docs/integrations/pob2-character-import.md) — OAuth-процедура и ограничения.
- [Скиллы](docs/integrations/skills-status.md) — проектные скиллы.
- [A6-модели](docs/integrations/a6-model-routing.md) — FAST / ANALYZE / CODE.

Проверка локального PoB2-движка и данных:

```bash
powershell -ExecutionPolicy Bypass -File scripts/check-pob.ps1
uv run python scripts/validate_data.py
uv run pytest tests/
```
