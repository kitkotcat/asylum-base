from __future__ import annotations

import asyncio
from pathlib import Path

import aiosqlite

from bot.app.db import Database


def _packages() -> list[dict]:
    result = []

    for index in range(5):
        result.append(
            {
                "package_key": f"sku-{index}",
                "name": f"Package {index}",
                "regular_price_minor": 1000 + index,
                "promo_price_minor": 900 + index,
                "official_price_minor": 1200 + index,
                "savings_minor": 300,
                "currency": "USD",
                "discount_badge": "8%",
                "coupon_name": "New User Coupon",
                "sell_order_id": f"T-{index}",
            }
        )

    return result


def test_legacy_schema_is_preserved_and_migrated(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        path = tmp_path / "legacy.db"

        async with aiosqlite.connect(path) as db:
            await db.executescript(
                """
                CREATE TABLE lootbar_packages (
                    package_key TEXT PRIMARY KEY,
                    source_url TEXT NOT NULL,
                    name TEXT NOT NULL,
                    current_price_minor INTEGER NOT NULL,
                    original_price_minor INTEGER NOT NULL,
                    savings_minor INTEGER NOT NULL,
                    currency TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    missing_count INTEGER NOT NULL DEFAULT 0,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    last_changed_at TEXT NOT NULL
                );

                CREATE TABLE lootbar_price_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    package_key TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    name TEXT NOT NULL,
                    current_price_minor INTEGER NOT NULL,
                    original_price_minor INTEGER NOT NULL,
                    savings_minor INTEGER NOT NULL,
                    currency TEXT NOT NULL,
                    change_type TEXT NOT NULL,
                    observed_at TEXT NOT NULL
                );
                """
            )
            await db.commit()

        database = Database(path)
        await database.init()

        async with database.connect() as db:
            cursor = await db.execute(
                'PRAGMA table_info("lootbar_packages")'
            )
            columns = {
                str(row["name"])
                for row in await cursor.fetchall()
            }

            cursor = await db.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                  AND name LIKE 'lootbar_packages_legacy_%'
                """
            )
            legacy = await cursor.fetchone()

        assert "regular_price_minor" in columns
        assert "promo_price_minor" in columns
        assert "official_price_minor" in columns
        assert legacy is not None

        baseline, events = (
            await database.sync_lootbar_packages(
                "https://example.com/lootbar",
                _packages(),
            )
        )

        assert baseline is True
        assert events == []

        changed = _packages()
        changed[0]["promo_price_minor"] = 850
        changed[0]["savings_minor"] = 350

        baseline, events = (
            await database.sync_lootbar_packages(
                "https://example.com/lootbar",
                changed,
            )
        )

        assert baseline is False
        assert len(events) == 1
        assert events[0]["change_type"] == "price_changed"
        assert events[0]["old_promo_price_minor"] == 900
        assert events[0]["promo_price_minor"] == 850

    asyncio.run(scenario())
