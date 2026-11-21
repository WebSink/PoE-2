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

### Проверка S4.6 → S4.7 (2026-11-21)

| Проверка | Результат |
|---|---|
| `%APPDATA%\CherryStudio\Data\Skills\poe2-*` | 4 каталога на месте |
| `…\Data\Agents\.claude\skills\poe2-*` | 4 каталога на месте |
| Таблица `agent_global_skill` | 4 записи `poe2-*`, `source=local`, `is_enabled=1`, описания в UTF-8 корректные |
| Таблица `agent_skill` (агент `06dc77f4…`, «A6 Dev») | 4 привязки `poe2-*`, `is_enabled=1` |
| Allowlist сессии S4.6 | скиллов `poe2-*` **не было** — только 8 встроенных |
| **Allowlist сессии S4.7** | **все 4 скилла `poe2-*` доступны** |
| **Реальный вызов `poe2-build-analysis`** | **PASS** — `SKILL.md` загружен, ошибки allowlist нет |

Расхождение S4.6/S4.7 объясняется тем, что список скиллов сессии фиксируется при
её старте: записи `poe2-*` в БД уже были, но в снапшот прошлой сессии не попали.
Новая сессия их видит — перезапуск Cherry Studio помог, как и предполагалось.

Статус: **AVAILABLE** — 4/4 скилла зарегистрированы, включены для агента и
вызываются в текущей сессии. База Cherry не редактировалась.

### Что сделать вручную

Ничего обязательного: скиллы доступны. Если после обновления Cherry Studio они
исчезнут из сессии — перезапустить приложение или открыть Settings → Skills.
Если скилл не находится и после этого: Settings → Skills → добавить скилл из
папки и указать `C:\Projects\PoE-2\skills\<name>`.

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
