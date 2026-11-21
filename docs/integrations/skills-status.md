# Проектные скиллы: статус

Дата: **2026-11-21**.

## Что создано

| Скилл | Назначение | Файл |
|---|---|---|
| `poe2-build-analysis` | Анализ персонажа, защита, дерево, камни | `skills/poe2-build-analysis/SKILL.md` |
| `poe2-gear-optimizer` | Сравнение предметов, дельты, требования | `skills/poe2-gear-optimizer/SKILL.md` |
| `poe2-market-research` | Фильтры и разбор объявлений вручную | `skills/poe2-market-research/SKILL.md` |
| `poe2-development` | TypeScript/Python, тесты, git, PR | `skills/poe2-development/SKILL.md` |

Все четыре написаны с нуля для этого проекта. Проверено: `name:` в frontmatter
совпадает с именем папки, формат — lowercase-hyphen, у каждого есть условия
применения и выходной формат.

## Регистрация в Cherry Studio

Штатный механизм (из встроенного `skill-creator`): Cherry синхронизирует
управляемый каталог `%APPDATA%\CherryStudio\Data\Skills` с каталогом скиллов,
отдельного register-tool нет.

Сделано:

1. Скиллы созданы в `skills/` репозитория (источник истины).
2. Скопированы в `C:\Users\tukim\AppData\Roaming\CherryStudio\Data\Skills\poe2-*`.
3. Проверка каталога Cherry: **регистрация ещё не произошла** — в таблице
   `agent_global_skill` записей `poe2-*` нет (проверено дважды, ~2 минуты после
   копирования). Синхронизация, вероятно, выполняется при старте приложения или
   при открытии раздела Skills.

Статус: **PARTIAL** — файлы на месте, автокаталог Cherry ещё не подхватил.

### Проверка 2026-11-21 (повторная)

Файлы присутствуют в двух каталогах, по 13 записей в каждом (9 встроенных + 4 `poe2-*`):

- `%APPDATA%\CherryStudio\Data\Skills\poe2-{build-analysis,development,gear-optimizer,market-research}`
- `%APPDATA%\CherryStudio\Data\Agents\.claude\skills\poe2-*`

Прямой тест вызова скилла вернул:

```
Skill poe2-build-analysis is not in this session's skills allowlist
```

Причина: список доступных скиллов фиксируется при старте сессии, а Cherry
не просканировал каталог за время её работы. Это не ошибка содержимого скилла —
frontmatter и пути корректны. Требуется перезапуск Cherry Studio.

### Что сделать вручную

1. Перезапустить Cherry Studio **или** открыть Settings → Skills и обновить список.
2. Убедиться, что появились 4 скилла `poe2-*`.
3. Включить их для агента `HEAD` (и при необходимости для `BUILDER`/`REVIEWER`).
4. Проверка: спросить агента «разбери билд Sinkov» — должен сработать
   `poe2-build-analysis`.

Если после перезапуска скиллы не появились: Settings → Skills → добавить скилл
из папки и указать `C:\Projects\PoE-2\skills\<name>`. Точные подписи кнопок
зависят от версии Cherry; каталог `Data\Skills` — гарантированно поддерживаемый
путь.

## Чужие скиллы и лицензии

- `lornedauterman/agent-of-exile` — **лицензия не указана** (`license: null`).
  Код и тексты не копировались. Использованы только общие идеи структуры
  (build/gear/market/development), реализация — самостоятельная.
- `Sidekick-Poe/Sidekick` — MIT, но это отдельное приложение; в проект не
  встраивалось.
- `cboyd421-max/poe2-forge` — без лицензии, не использовался.
- `pob-mcp` — MIT; используется как внешний MCP, не как текст скилла.

## Ограничения скиллов

- `poe2-build-analysis` не считает DPS без PoB-экспорта.
- `poe2-gear-optimizer` не покупает и не ищет предметы.
- `poe2-market-research` работает только с предоставленными вручную данными.
- `poe2-development` не разрешает merge в `main` и force-push.
