# data/builds/ — локальные PoB2-билды

Каталог для `.xml`-экспортов из Path of Building 2 (PoE2).

## Правила

- Файлы билдов **не коммитятся** (см. `.gitignore`) до проверки владельцем.
  Импортированный персонаж — это реальные данные аккаунта; публиковать их
  в публичный репозиторий без явного разрешения нельзя.
- В Git попадает только этот README.
- Никаких токенов, cookie и `POESESSID` здесь быть не может. OAuth-токены PoB2
  хранит в своих настройках, не в этом каталоге.

## Соглашение об именах

```
data/builds/<character>-<league>.xml      # пример: sinkov-standard.xml
data/builds/<character>-<league>.stats.json   # снимок get_stats (по желанию)
```

## Как получить файл

См. [docs/integrations/pob2-character-import.md](../../docs/integrations/pob2-character-import.md).

## Что лежит локально (2026-11-21)

| Файл | Что это |
|---|---|
| `sinkov-standard.xml` | импорт Sinkov через официальный OAuth PoB2, 46 ур., Witchhunter, Standard (sha256 `1524af5e…`) |
| `sinkov-standard.stats.json` | снимок движка: `get_stats` / `get_tree_state` / `get_skills` / `get_items` / `sanity_check` / `get_config` |

Оба файла в Git не попадают. Разбор: [docs/sinkov-pob-audit.md](../../docs/sinkov-pob-audit.md).
Машиночитаемый профиль персонажа (schema 2.0.0, в Git входит):
[data/characters/sinkov.json](../characters/sinkov.json).
