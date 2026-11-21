# data/characters/ — профили персонажей

Схема: [`data/schemas/character-profile.schema.json`](../schemas/character-profile.schema.json)
(schema_version **2.0.0**). Модель описана в
[docs/character-profile-schema.md](../../docs/character-profile-schema.md).

## Файлы

| Файл | Что это |
|---|---|
| `sinkov.json` | Актуальный профиль Sinkov (46 ур., Witchhunter, Standard), построен из импорта PoB2 |
| `history/sinkov-2026-11-21-screenshots-v1.json` | Исторический снимок со скриншотов (45 ур., schema 1.0.0) — сохранён без изменений |

## Правила

- **У каждого факта один уровень достоверности.** `observed` — подтверждено в игре,
  `imported` — перенесено импортом PoB2, `calculated` — посчитано движком под
  конкретной конфигурацией, `unverified` — требует проверки.
- **Нет расчёта без конфигурации.** Любой DPS/EHP живёт только внутри
  `calculated.scenarios[*]` с `config`, `config_rationale`, `captured_at` и `source_id`.
- **Никаких секретов и сырого XML.** Ни токенов, ни `POESESSID`, ни текста билда.
- **Не перезаписывать историю.** Новый снимок — новый файл, старый уезжает в `history/`.

## Проверка

```bash
uv run python scripts/validate_data.py
uv run pytest tests/
```

Обе команды должны завершиться без ошибок перед коммитом.
