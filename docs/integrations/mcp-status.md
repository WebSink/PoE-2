# MCP и инструменты: статус

Дата проверки: **2026-11-21**. Всё, что отмечено PASS, проверено реальным вызовом,
а не только наличием в конфигурации.

## Сводка

| Компонент | Тип | Статус | Проверка |
|---|---|---|---|
| Filesystem / terminal | встроенные tools | PASS | Чтение/запись файлов, `git`, `curl`, `uv`, `gh` |
| Git | CLI 2.55.0 | PASS | `git remote -v`, ветка `chore/agent-bootstrap` |
| GitHub | `gh` CLI 2.102.0 | PASS | `gh auth status`: аккаунт `WebSink`, scopes `repo`, `workflow`, `read:org`, `gist` |
| GitHub MCP | — | NOT INSTALLED | Не нужен: `gh` покрывает ветки/коммиты/PR/CI. Дубликат не ставился |
| Filesystem MCP | — | NOT INSTALLED | Не нужен: встроенные file tools + shell |
| Web research | `web_search` / `web_fetch` | PASS | Использованы для README/лицензий pob-mcp и PoB2 |
| Cherry tools | `mcp__cherry-tools__*` | PASS | `config`/`install_mcp_server`/`web_fetch` |
| Agent memory | `agent-memory` | UNVERIFIED | Сервер объявлен, в этой сессии не вызывался |
| **pob-mcp** | stdio MCP | **PASS** | Активен и доверен; 44 инструмента; реальные вызовы; **Sinkov загружен** (см. ниже) |
| Path of Building 2 | release v0.23.1 | PASS | Headless-запуск, tree data `0_5` |
| LuaJIT | 2.1 portable | PASS | `luajit -v` → `LuaJIT 2.1.1720049189` |
| Docker | 29.9.1 | NOT USED | Демон не запущен; проекту не нужен |
| Trade-интеграции | — | NOT INSTALLED | Запрещены скрапинг/недокументированные API |

## pob-mcp: детали

- Источник: <https://github.com/juddisjudd/pob-mcp>, лицензия **MIT** (`LICENSE.md`).
- Локально: `C:\Projects\PoE-2\.tools\pob-mcp` (в Git не входит).
- Запуск: `C:\Projects\PoE-2\.tools\pob-mcp\.venv\Scripts\pob-mcp.exe`.
- Env: `POB_MCP_INSTALL_DIR=C:\Projects\PoE-2\.tools\pob2`,
  `POB_MCP_LUAJIT=C:\Projects\PoE-2\.tools\luajit\bin\luajit.exe`.
- Зарегистрирован в Cherry Studio: имя `pob-mcp`, id `98e74ae3-6c2a-4809-8602-52606a1d1982`,
  `is_active=1`, `is_trusted=1`, привязан к агенту `3e78272c-…`.
- Секретов в конфигурации нет.

### Что проверено

1. Прямой запуск моста:
   `luajit pob_bridge.lua` + JSON-RPC → `new_build` = `{"ok":true}`,
   `get_stats` вернул реальные значения движка.
2. Интеграционные тесты: `uv run pytest tests/test_bridge_protocol.py -q`
   → **12 passed in 31.87s**.
3. MCP over stdio (реальный клиент):
   - `initialize` → `pob-mcp`;
   - `tools/list` → **44 инструмента** (`load_build`, `get_stats`, `equip_item_raw`,
     `optimize_build`, `compare_builds`, `export_build`, …);
   - `new_build` → ok;
   - `get_stats` → `Life 65`, `Mana 50`, `FireResist -50`, `Evasion 7` (пустой билд);
   - `list_classes` → реальный список классов/возвышений PoE2.
4. **S4.6 — реальный билд Sinkov (2026-11-21).**
   `load_build` на `data/builds/sinkov-standard.xml` → `Mercenary` / `Witchhunter`, уровень 46.
   `get_stats` / `get_tree_state` (60 узлов) / `get_skills` (11 групп) / `get_items` (13 слотов) /
   `sanity_check` (3 предупреждения) — все вызовы без ошибок.
5. **S4.7 — сценарии и механические пробы (2026-11-21).**
   Инструменты `pob-mcp` объявлены в сессии напрямую (не через отдельный клиент).
   Выполнены: `set_config` (resistancePenalty −60/−20/0, enemyLevel, enemyArmour, enemyIsBoss),
   `set_main_skill` (7 групп), `set_gem` (включение/выключение вестников), `dealloc_node` (29514, 17882).
   Результаты: `docs/sinkov-pob-audit.md`, машинночитаемо — `data/characters/sinkov.json`.
   Выявлено ограничение движка: `TotalDPS` не реагирует на число снарядов и время детонации гранат,
   но `DetonationTime` и `ProjectileCount` доступны отдельными полями `get_stats`.

### Ограничения

- **Абсолютные цифры PoB2 зависят от конфига импорта.** Файл приходит с дефолтами
  `resistancePenalty=-60` (Endgame), `enemyLevel=82`, `enemyArmour=8063`. Для персонажа
  в акте III корректный штраф — `-20`; перед сравнением с игрой выставлять его явно.
- Отображаемый в игре DPS не сопоставим с `TotalDPS` движка (разные цели и допущения).
- PoB2 v0.23.1 грузит данные `0_5`. Совпадение с точным патчем игры пользователя
  не проверялось.
- `optimize_build` — жадный поиск, не полный решатель; цены не учитывает.
- Живой импорт профиля poe.ninja не поддерживается (только pob-link).

## Почему не установлены другие MCP

- **GitHub MCP**: `gh` уже авторизован и покрывает нужные операции; установка
  потребовала бы отдельного токена и дублировала бы доступ.
- **Filesystem MCP**: встроенные tools уже ограничены рабочими каталогами.
- **Trade/скраперы**: прямо запрещены правилами проекта.
- **pob2-mcp (zgrummons)**: GPL-3.0, TypeScript, дублирует функциональность;
  выбран один сервер — MIT `pob-mcp`.

## Ручные действия

Ничего не требуется для `pob-mcp`: сервер активен. Если Cherry Studio попросит
подтвердить доверие после перезапуска — разрешить `pob-mcp` в Settings → MCP.

Для полного анализа Sinkov больше ничего не нужно: `.xml` лежит в `data/builds/sinkov-standard.xml`
(каталог в Git не попадает), аудит — `docs/sinkov-pob-audit.md`. Повторный экспорт нужен только
после смены экипировки или камней в игре.
