from __future__ import annotations

import asyncio

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.app.config import load_settings
from bot.app.db import Database
from bot.app.services.community_db import (
    init_community_schema,
    mark_editorial_dispatched,
)
from bot.app.services.content_db import init_content_schema, save_draft_payload
from bot.app.services.publisher import publish_draft


BOOTSTRAP_KINDS = ("guide", "hero", "squad", "alliance")


async def _next_item(db: Database, kind: str):
    async with db.connect() as connection:
        cursor = await connection.execute(
            """
            SELECT *
            FROM editorial_items
            WHERE status = 'approved' AND kind = ?
            ORDER BY next_publish_at, id
            LIMIT 1
            """,
            (kind,),
        )
        return await cursor.fetchone()


async def _existing_draft_id(
    db: Database,
    *,
    source_url: str,
    item_uid: str,
) -> int | None:
    async with db.connect() as connection:
        cursor = await connection.execute(
            """
            SELECT id
            FROM content_drafts
            WHERE source_url = ? AND item_uid = ?
            LIMIT 1
            """,
            (source_url, item_uid),
        )
        row = await cursor.fetchone()
    return int(row["id"]) if row else None


async def main() -> None:
    settings = load_settings()
    db = Database(settings.db_path)
    await db.init()
    await init_content_schema(db)
    await init_community_schema(db)

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    published = 0
    try:
        for kind in BOOTSTRAP_KINDS:
            item = await _next_item(db, kind)
            if item is None:
                print(f"SKIP {kind}: no approved editorial item")
                continue

            editorial_id = int(item["id"])
            source_url = f"internal://bootstrap/v0.4.5/{editorial_id}"
            item_uid = f"bootstrap:{editorial_id}"
            draft_id = await _existing_draft_id(
                db,
                source_url=source_url,
                item_uid=item_uid,
            )
            if draft_id is None:
                draft_id = await db.create_draft(
                    kind=kind,
                    source_url=source_url,
                    item_uid=item_uid,
                    title=str(item["title"]),
                    link=str(item["source_url"] or ""),
                    summary=str(item["body"]),
                )
            if draft_id is None:
                raise RuntimeError(f"Cannot create bootstrap draft for {kind}")

            await save_draft_payload(
                db,
                draft_id,
                image_url=str(item["image_file_id"] or ""),
                entity_key=str(item["entity_key"] or f"editorial:{editorial_id}"),
                metadata={
                    "editorial_id": editorial_id,
                    "bootstrap_release": "v0.4.5",
                    "auto_eligible": False,
                },
            )
            result = await publish_draft(
                bot,
                settings,
                db,
                draft_id,
                auto_published=False,
            )
            await mark_editorial_dispatched(db, editorial_id)
            if result is not None:
                published += 1
            print(f"BOOTSTRAP {kind}: editorial #{editorial_id}")
    finally:
        await bot.session.close()

    print(f"Topic bootstrap publications: {published}")


if __name__ == "__main__":
    asyncio.run(main())
