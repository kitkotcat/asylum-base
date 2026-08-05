# Deploy v0.4.4

## Новые переменные

```dotenv
EDITORIAL_AUTOPOST_ENABLED=false
EDITORIAL_MAX_POSTS_PER_DAY=1
EDITORIAL_TIMEZONE_OFFSET_HOURS=5
```

Сначала деплой выполняется с `EDITORIAL_AUTOPOST_ENABLED=false`.
После миграции и проверки команд флаг можно включить.

## Проверка схемы

```bash
.venv/bin/python - <<'PY'
import asyncio
from bot.app.config import load_settings
from bot.app.db import Database
from bot.app.services.community_db import init_community_schema
from bot.app.services.content_db import init_content_schema

async def main():
    settings = load_settings()
    db = Database(settings.db_path)
    await db.init()
    await init_content_schema(db)
    await init_community_schema(db)
    print("v0.4.4 schema: OK")

asyncio.run(main())
PY
```

## Приёмка

1. `/heroes`, `/squads`, `/events` отвечают без ошибок.
2. `/suggest` создаёт предложение.
3. `/suggestions` показывает его администратору.
4. Одобрение создаёт обычный черновик.
5. `/content_add` создаёт запись в очереди.
6. `/content_pause` и `/content_resume` меняют состояние.
7. `/analytics` показывает агрегаты.
8. После включения автопостинга за день публикуется не более установленного лимита.
