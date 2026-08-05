from __future__ import annotations

import asyncio

from bot.app.config import load_settings
from bot.app.db import Database
from bot.app.services.community_db import init_community_schema
from bot.app.services.content_db import init_content_schema

REQUIRED_TABLES = {
    "heroes",
    "squads",
    "game_events",
    "editorial_items",
    "content_suggestions",
    "message_reaction_users",
    "message_reaction_totals",
}


async def main() -> None:
    settings = load_settings()
    db = Database(settings.db_path)
    await db.init()
    await init_content_schema(db)
    await init_community_schema(db)

    async with db.connect() as connection:
        cursor = await connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        actual = {str(row["name"]) for row in await cursor.fetchall()}
        integrity_cursor = await connection.execute("PRAGMA integrity_check")
        integrity_row = await integrity_cursor.fetchone()

    missing = sorted(REQUIRED_TABLES - actual)
    if missing:
        raise SystemExit(f"Missing tables: {', '.join(missing)}")
    integrity = str(integrity_row[0] if integrity_row else "unknown")
    if integrity != "ok":
        raise SystemExit(f"SQLite integrity check failed: {integrity}")

    print("v0.4.4 schema: OK")
    print("SQLite integrity: OK")
    print("Editorial autopost:", settings.editorial_autopost_enabled)
    print("Editorial daily limit:", settings.editorial_max_posts_per_day)
    print("Editorial timezone offset:", settings.editorial_timezone_offset_hours)


if __name__ == "__main__":
    asyncio.run(main())
