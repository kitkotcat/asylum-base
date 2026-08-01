from __future__ import annotations

import asyncio
import sqlite3

from bot.app.config import load_settings
from bot.app.db import Database
from bot.app.services.content_db import init_content_schema


REQUIRED_TABLES = {
    "content_payloads",
    "publication_queue",
    "publication_log",
    "lootbar_package_assets",
    "scheduled_jobs",
    "promo_metadata",
}


async def main() -> None:
    settings = load_settings()
    db = Database(settings.db_path)
    await db.init()
    await init_content_schema(db)

    connection = sqlite3.connect(settings.db_path)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    finally:
        connection.close()

    missing = REQUIRED_TABLES - tables
    print("Database:", settings.db_path)
    print("Integrity:", integrity)
    print("Missing tables:", sorted(missing))
    if integrity != "ok" or missing:
        raise SystemExit(1)
    print("Asylum Base v0.3.0 schema: OK")


if __name__ == "__main__":
    asyncio.run(main())
