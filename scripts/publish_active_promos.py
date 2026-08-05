from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.app.config import load_settings
from bot.app.db import Database
from bot.app.services.content_db import count_auto_promos_today, init_content_schema
from bot.app.services.publisher import publish_draft
from bot.app.services.scheduler import create_active_promo_drafts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Publish verified active promo codes with duplicate protection."
    )
    parser.add_argument("--limit", type=int, default=2)
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    if args.limit < 1 or args.limit > 10:
        raise SystemExit("--limit must be between 1 and 10")

    settings = load_settings()
    settings = replace(
        settings,
        auto_publish_promos=True,
        promo_max_posts_per_day=args.limit,
    )
    db = Database(settings.db_path)
    await db.init()
    await init_content_schema(db)

    published_today = await count_auto_promos_today(
        db,
        offset_hours=settings.editorial_timezone_offset_hours,
    )
    remaining = max(0, args.limit - published_today)
    draft_ids = await create_active_promo_drafts(
        settings,
        db,
        limit=remaining,
    )

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    published = 0
    try:
        for draft_id in draft_ids:
            result = await publish_draft(
                bot,
                settings,
                db,
                draft_id,
                auto_published=True,
            )
            if result is not None:
                published += 1
    finally:
        await bot.session.close()

    print(f"Promo publications: {published}")


if __name__ == "__main__":
    asyncio.run(main())
