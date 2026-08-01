from __future__ import annotations

import asyncio
from pathlib import Path

from bot.app.db import Database


def test_database_can_open_multiple_connections(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        db = Database(tmp_path / "test.db")
        await db.init()

        await db.upsert_user(
            telegram_id=1,
            username="tester",
            first_name="Test",
        )
        await db.log_referral_click(
            telegram_id=1,
            campaign="pytest",
        )

        run_id = await db.start_radar_run("pytest")
        await db.mark_source_started(
            "test-source",
            "https://example.com",
        )
        await db.mark_source_success(
            "test-source",
            "https://example.com",
            items_count=1,
            duration_ms=10,
        )
        await db.finish_radar_run(
            run_id,
            status="ok",
            drafts_created=0,
            error_count=0,
        )

        last_run = await db.get_last_radar_run()
        statuses = await db.list_source_statuses()

        assert last_run is not None
        assert last_run["status"] == "ok"
        assert len(statuses) == 1
        assert statuses[0]["status"] == "ok"

    asyncio.run(scenario())
