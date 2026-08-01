from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from aiogram.types import LinkPreviewOptions

from bot.app.config import Settings
from bot.app.db import Database
from bot.app.keyboards import draft_keyboard
from bot.app.services.parsers import (
    check_page_changed,
    collect_rss_drafts,
    render_draft,
)

logger = logging.getLogger(__name__)


async def _notify_admins(
    bot: Bot,
    settings: Settings,
    db: Database,
    draft_ids: list[int],
) -> None:
    if not settings.admin_ids:
        logger.warning("ADMIN_IDS пуст: черновики некому отправлять")
        return

    for draft_id in draft_ids:
        draft = await db.get_draft(draft_id)
        if draft is None:
            continue

        text = render_draft(
            title=str(draft["title"]),
            summary=str(draft["summary"]),
            link=str(draft["link"]),
        )

        for admin_id in settings.admin_ids:
            try:
                await bot.send_message(
                    admin_id,
                    text,
                    reply_markup=draft_keyboard(draft_id),
                    link_preview_options=LinkPreviewOptions(
                        is_disabled=True
                    ),
                )
            except Exception:
                logger.exception(
                    "Не удалось отправить черновик %s админу %s",
                    draft_id,
                    admin_id,
                )


async def run_scheduler(
    bot: Bot,
    settings: Settings,
    db: Database,
) -> None:
    await asyncio.sleep(10)

    while True:
        draft_ids: list[int] = []

        try:
            draft_ids.extend(
                await collect_rss_drafts(db, settings.rss_feed_urls)
            )
        except Exception:
            logger.exception("Ошибка RSS-проверки")

        try:
            lootbar_draft_id = await check_page_changed(
                db,
                settings.lootbar_page_url,
            )
            if lootbar_draft_id is not None:
                draft_ids.append(lootbar_draft_id)
        except Exception:
            logger.exception("Ошибка мониторинга LootBar")

        if draft_ids:
            await _notify_admins(bot, settings, db, draft_ids)

        await asyncio.sleep(settings.parser_interval_minutes * 60)
