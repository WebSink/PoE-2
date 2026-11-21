# Импорт персонажа в PoB2: проверка и процедура

Дата проверки: **2026-11-21**.
PoB2: **v0.23.1** (`.tools/pob2`, portable, PoE2-форк).
Данные дерева: `0_5`.

## Вывод

Официальный импорт персонажа из аккаунта Path of Exile 2 **поддерживается**
в установленной сборке. Реализация — OAuth 2.0 Authorization Code + PKCE,
напрямую в коде PoB2, без сторонних сервисов.

Импортировать можно: класс/восхождение, дерево пассивных навыков, джевелы,
экипировку, камни умений и поддержки, квестовые награды.

## Доказательства (в исходниках `.tools/pob2`)

| Файл | Строки | Что подтверждает |
|---|---|---|
| `Classes/PoEAPI.lua` | 5–10 | `scopesOAuth` = `account:profile`, `account:leagues`, `account:characters`, `account:trade` |
| `Classes/PoEAPI.lua` | 92–97 | URL авторизации: `client_id=pob`, `response_type=code`, `code_challenge_method=S256` |
| `Classes/PoEAPI.lua` | 120–135 | Обмен кода на токен: `POST https://www.pathofexile.com/oauth/token` |
| `Classes/PoEAPI.lua` | 205–216 | Эндпоинты `/character[/realm][/name]` на `https://api.pathofexile.com` |
| `Classes/ImportTab.lua` | 428, 588, 638, 644, 650 | Загрузка списка персонажей, персонажа, дерева, предметов, квестовых наград |
| `LaunchServer.lua` | 11 | Loopback-редирект на `localhost`, порты 49082 → 49083 → 49084 |

Состояния UI-машины импорта (`ImportTab.lua`): `AUTHENTICATION` → `GETACCOUNTNAME`
→ `SELECTCHAR` → `IMPORTING`.

## Почему импорт не автоматизирован агентом

Две независимые причины, обе неустранимые без владельца:

1. **Авторизация — только владелец.** OAuth требует входа в аккаунт в браузере.
   Агент не запрашивает и не извлекает пароли, cookie и токены.
2. **UI PoB2 не принимает синтетический ввод.** Интерфейс отрисован кастомно
   через SimpleGraphic; AX-дерево содержит только нативную рамку окна, а
   программные клики по координатам не активируют внутренние контролы
   (проверено на v0.23.1: клики по вкладке `Import/Export Build` и по
   переключателю `Items` не дают эффекта, при этом нативные кнопки
   `Maximize`/`Restore` работают). Значит, GUI-автоматизация ненадёжна,
   а обход через глобальный ввод запрещён.

## Что НЕ используется

В `ImportTab.lua` есть legacy-ветка `GETSESSIONID` (строки 459, 463) — она
срабатывает при 401/403 и требует вставки `POESESSID` для приватных профилей.
**Не применять:** cookie — запрещённый секрет по правилам проекта. Если профиль
закрыт, безопасный путь — временно открыть профиль персонажей в настройках
аккаунта на pathofexile.com и использовать OAuth.

## Процедура (выполняет владелец)

1. Запустить `.tools/pob2/Path of Building-PoE2.exe`.
2. Открыть вкладку **Import/Export Build** (верхний левый ряд кнопок).
3. Нажать **Authorize with Path of Exile**. Откроется браузер на
   `pathofexile.com/oauth/authorize` с `client_id=pob` и четырьмя скоупами
   (профиль, лиги, персонажи, трейд).
4. Войти в аккаунт и подтвердить доступ. Браузер вернёт код на
   `http://localhost:49082` (или 49083/49084) — PoB2 слушает этот порт сам.
   После успеха кнопка меняется на `Logout from Path of Exile API`.
5. В блоке «To start importing a character…» выбрать realm **PC** (PoE2) и
   нажать **Start**.
6. В блоке «Choose character to import data from…» выбрать лигу **Standard**
   и персонажа **Sinkov** (Witchhunter).
7. Нажать **Passive Tree and Jewels** — импорт дерева, восхождения, джевелов.
8. Нажать **Items and Skills** — импорт экипировки и камней.
9. `Save As` → `C:\Projects\PoE-2\data\builds\sinkov-standard.xml`.
   (Альтернатива: сохранить в `.tools/pob2/Builds/` и скопировать оттуда.)

Каталог `data/builds/` уже создан. Файлы билдов исключены из Git.

## Что будет сделано после появления файла

Агент по `pob-mcp`:

1. `load_build` → `C:\Projects\PoE-2\data\builds\sinkov-standard.xml`
2. `get_stats`, `get_tree_state`, `get_skills`, `get_items`, `sanity_check`
3. Сравнение с `data/characters/sinkov.json`: здоровье, сопротивления,
   нагрудник (`comparison_items_not_confirmed_equipped`), дерево, камни.
4. Отчёт с расхождениями. Никаких догадок вместо отсутствующих значений.

## Ограничение pob-mcp

`pob-mcp` **не** интегрирует character API. В его собственном коде
(`src/pob_mcp/importers.py`, строки 45–47) прямо сказано: импорт живого профиля
персонажа не реализован, нужен официальный character API, которого в этой
версии нет. Поэтому цепочка такая: импорт в PoB2 GUI → `.xml` → `pob-mcp`.

## Безопасность

- Токены PoB2 хранит в своих настройках (`main.lastToken`, `main.lastRefreshToken`),
  не в репозитории. В Git и в промпты они не попадают.
- Импорт не меняет игровой аккаунт и не выполняет игровых действий.
- Скоуп `account:trade` PoB2 запрашивает всегда, но проект не использует
  trade-API: рынок — только вручную.
