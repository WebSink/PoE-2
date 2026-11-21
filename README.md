# PoE-2 🚀

Рабочий репозиторий для анализа билдов и подбора экипировки **Path of Exile 2**.

## Текущие данные

- [Профиль Sinkov (JSON)](data/characters/sinkov.json) — данные для будущего market scanner / агента.
- [Аудит Sinkov (Markdown)](docs/sinkov-build-audit.md) — человеческое резюме, известные слабые места и задачи.

Профиль составлен по пользовательским скриншотам. Неподтверждённые значения явно обозначены. Никаких торговых сделок или автоматического доступа к аккаунту этот репозиторий не выполняет.

## Инфраструктура разработки

- [AGENTS.md](AGENTS.md) — правила для агентов и разработчиков.
- [Архитектура](docs/architecture.md) — модули и контракты данных.
- [MCP-статус](docs/integrations/mcp-status.md) — PoB2/pob-mcp и проверки.
- [Скиллы](docs/integrations/skills-status.md) — проектные скиллы.
- [A6-модели](docs/integrations/a6-model-routing.md) — FAST / ANALYZE / CODE.

Проверка локального PoB2-движка:

```bash
powershell -ExecutionPolicy Bypass -File scripts/check-pob.ps1
```
