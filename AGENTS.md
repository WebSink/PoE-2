# AGENTS.md — PoE 2 Control Center

Инструкции для любых AI-агентов и разработчиков, работающих в этом репозитории.

## Что это за проект

Локальный инструмент для анализа персонажей Path of Exile 2, сравнения экипировки,
рыночных фильтров и истории апгрейдов. Основа — проверяемые данные и реальный
движок Path of Building 2 (PoE2), без вымышленных расчётов.

Текущее состояние: **bootstrap-инфраструктура** (архитектура, интеграции, скиллы,
документация). Полноценное приложение ещё не реализовано.

## Главный персонаж

- `Sinkov`, Witchhunter (Охотник на ведьм), 46 уровень, лига Standard.
- Актуальный профиль: `data/characters/sinkov.json` (**schema_version 2.1.0**) — построен из импорта PoB2.
  Сопротивления до капа живут в `calculated.resistance_baseline` (вывод движка, не импорт),
  там же `maximum` / `maximum_method` — измеренный кап (по умолчанию 75): отдельного поля
  максимума PoB2 не отдаёт, он выводится насыщением;
  миграция со схемы 2.0.0 — `scripts/migrate_profiles_2_0_to_2_1.py`.
  Разделы `observed` / `imported` / `calculated` / `unverified`; схема — `data/schemas/character-profile.schema.json`,
  описание — `docs/character-profile-schema.md`.
- Исторический снимок со скриншотов (уровень 45): `data/characters/history/sinkov-2026-11-21-screenshots-v1.json`.
- PoB2-экспорт: `data/builds/sinkov-standard.xml` (локальный, в Git не входит).
- Аудит по движку PoB2: `docs/sinkov-pob-audit.md`; история наблюдений — `docs/sinkov-build-audit.md`.

## Железные правила данных

1. **У каждого факта один уровень достоверности.** `observed` (в игре) / `imported` (импорт PoB2) /
   `calculated` (движок) / `unverified` (требует проверки). Не смешивать разделы и не переносить
   числа из одного в другой без источника. Нагрудник «Колючий кров» подтверждён как надетый
   (Bramble Shelter / Sacrificial Mantle в импорте).
2. **Не выдумывать DPS и характеристики.** Числа берутся только из PoB2-движка
   (MCP `pob-mcp`) или из подтверждённого снимка. Отображаемый DPS разных умений
   в игре несопоставим напрямую. Разовый урон и DPS — разные величины.
3. **Нет расчёта без конфигурации.** Любой DPS/EHP живёт только внутри
   `calculated.scenarios[*]` с `config`, `config_rationale`, `captured_at` и `source_id`.
   Голых DPS/EHP на верхнем уровне профиля быть не должно.
4. **Источник + версия игры.** Для каждого игрового правила указывать источник и
   версию данных PoB2 (сейчас движок грузит tree data `0_5`).
5. **Импорт приходит с эндгейм-дефолтами.** В XML `resistancePenalty=-60`, `enemyLevel=82`,
   `enemyArmour=8063`, `enemyIsBoss=Pinnacle`. Для кампании акта III корректно `-20`,
   `enemyLevel=46`, `enemyArmour=624`. Никогда не смешивать столбцы разных штрафов.
6. **Рынок — только вручную.** Никаких скраперов, недокументированных API, обхода
   защиты trade-сайта, автоматических сделок и сообщений продавцам.

## Безопасность

Запрещено:

- передавать POESESSID, cookie, пароли, API-ключи и OAuth-токены в промпты, логи, Git;
- менять игровой аккаунт или запускать игровую автоматизацию;
- выполнять `git push --force`, `reset --hard`, `clean`, удалять чужие изменения;
- коммитить в `main` напрямую и делать merge без разрешения владельца;
- запускать непроверенные install-скрипты и подключать неизвестные удалённые MCP;
- удалять пользовательские файлы и данные.

Секреты хранятся только в менеджере секретов Cherry Studio / gh CLI keyring.

## Окружение (эта машина)

| Компонент | Путь / версия |
|---|---|
| Project root | `C:\Projects\PoE-2` |
| Node.js | v24.20.0 |
| Python | через `uv` (CPython 3.14.5 локально; pob-mcp использует 3.12+) |
| uv | 0.13.6 |
| Git | 2.55.0 |
| gh CLI | 2.102.0, аккаунт `WebSink`, scopes: repo, workflow, read:org, gist |
| LuaJIT | `.tools/luajit/bin/luajit.exe` (2.1, portable) |
| PoB2 | `.tools/pob2` (release v0.23.1, portable) |
| pob-mcp | `.tools/pob-mcp` (venv + MIT) |
| Docker | установлен, демон не запущен; проекту не нужен |

`.tools/` и `.tmp-bootstrap/` — локальные, в Git не попадают.

## Команды

```bash
# Проверить PoB2 + pob-mcp end-to-end
powershell -ExecutionPolicy Bypass -File scripts/check-pob.ps1

# Проверить целостность профилей персонажей (схема + доменные правила, без внешних зависимостей)
uv run python scripts/validate_data.py

# Тесты валидатора, профиля и анализатора экипировки (160 тестов, включая негативные кейсы)
uv run pytest tests/

# Тесты с настоящим PoB2 (8 тестов, ~2-4 с на загрузку билда)
uv run pytest tests/ -m integration

# Сравнить предмет с надетым (движок PoB2, временная копия билда)
uv run python scripts/gear_analyze.py --slot Boots --item-json data/candidates/sinkov-boots-windrush-partial.json

# Интеграционные тесты pob-mcp (12 тестов, реальный Lua-мост)
cd .tools/pob-mcp
POB_MCP_INSTALL_DIR='C:\Projects\PoE-2\.tools\pob2' \
POB_MCP_LUAJIT='C:\Projects\PoE-2\.tools\luajit\bin\luajit.exe' \
uv run pytest tests/test_bridge_protocol.py -q
```

## Git workflow

- Ветка под задачу: `chore/...`, `feat/...`, `fix/...`, `docs/...`.
- Коммиты — только проверенные изменения, Conventional Commits.
- PR — Draft, merge выполняет владелец.
- Перед коммитом: `git status`, проверка diff, отсутствие секретов и `.tools/`.

## Модели A6

Маршрутизация и подтверждённые ID — `docs/integrations/a6-model-routing.md`.
Не придумывать идентификаторы моделей. Текущая проверенная модель с tool calling:
`deepseek-v4.1-flash`.

## Документация

- `docs/architecture.md` — модули и потоки данных.
- `docs/character-profile-schema.md` — модель профиля и автоматические проверки.
- `docs/gear-analyzer.md` — модуль сравнения экипировки (`poe2cc/gear/`) и CLI.
- `docs/pob2-limitations.md` — что PoB2 не проверяет и какие числа без него недоступны.
- `docs/examples/sinkov-boots-comparison.md` — реальный пример сравнения ботинок.
- `docs/sinkov-pob-audit.md` — аудит Sinkov по движку PoB2 (актуальные числа).
- `docs/integrations/mcp-status.md` — что реально подключено и проверено.
- `docs/integrations/skills-status.md` — скиллы и их регистрация.
- `docs/integrations/a6-model-routing.md` — FAST / ANALYZE / CODE.
- `skills/*/SKILL.md` — проектные скиллы.
