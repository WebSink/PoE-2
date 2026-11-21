# AGENTS.md — PoE 2 Control Center

Инструкции для любых AI-агентов и разработчиков, работающих в этом репозитории.

## Что это за проект

Локальный инструмент для анализа персонажей Path of Exile 2, сравнения экипировки,
рыночных фильтров и истории апгрейдов. Основа — проверяемые данные и реальный
движок Path of Building 2 (PoE2), без вымышленных расчётов.

Текущее состояние: **bootstrap-инфраструктура** (архитектура, интеграции, скиллы,
документация). Полноценное приложение ещё не реализовано.

## Главный персонаж

- `Sinkov`, Witchhunter (Охотник на ведьм), 45 уровень, лига Standard.
- Профиль: `data/characters/sinkov.json` (schema_version 1.0.0).
- Аудит: `docs/sinkov-build-audit.md`.

## Железные правила данных

1. **Не выдавать предположение за факт.** В JSON есть поле `verification` и
   `comparison_items_not_confirmed_equipped`. Нагрудник «Колючий кров» **не
   подтверждён как надетый**.
2. **Не выдумывать DPS и характеристики.** Числа берутся только из PoB2-движка
   (MCP `pob-mcp`) или из подтверждённого снимка. Отображаемый DPS разных умений
   в игре несопоставим напрямую.
3. **Источник + версия игры.** Для каждого игрового правила указывать источник и
   версию данных PoB2 (сейчас движок грузит tree data `0_5`).
4. **Sinkov не является PoB-билдом.** Полный расчёт возможен только после экспорта
   `.xml` из Path of Building 2. Частичный JSON-профиль не заменяет экспорт.
5. **Рынок — только вручную.** Никаких скраперов, недокументированных API, обхода
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
- `docs/integrations/mcp-status.md` — что реально подключено и проверено.
- `docs/integrations/skills-status.md` — скиллы и их регистрация.
- `docs/integrations/a6-model-routing.md` — FAST / ANALYZE / CODE.
- `skills/*/SKILL.md` — проектные скиллы.
