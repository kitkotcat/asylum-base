from __future__ import annotations

import asyncio
import logging

from aiogram import Bot

from bot.app.config import Settings
from bot.app.db import Database
from bot.app.keyboards import draft_keyboard
from bot.app.services.parsers import (
    check_google_play_update,
    check_page_changed,
    collect_rss_drafts,
    render_draft,
)

logger = logging.getLogger(__name__)


async def notify_admins(
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
                    disable_web_page_preview=True,
                )
            except Exception:
                logger.exception(
                    "Не удалось отправить черновик %s администратору %s",
                    draft_id,
                    admin_id,
                )


async def run_radar_once(
    bot: Bot,
    settings: Settings,
    db: Database,
) -> list[int]:
    draft_ids: list[int] = []

    try:
        draft_ids.extend(await collect_rss_drafts(db, settings.rss_feed_urls))
    except Exception:
        logger.exception("Ошибка RSS-проверки")

    try:
        draft_id = await check_page_changed(
            db,
            settings.lootbar_page_url,
            kind="topup",
            title="Изменилась страница LootBar",
            summary=(
                "Бот обнаружил изменение страницы пополнения. "
                "Проверьте цены, наборы и условия вручную перед публикацией."
            ),
        )
        if draft_id is not None:
            draft_ids.append(draft_id)
    except Exception:
        logger.exception("Ошибка мониторинга LootBar")

    try:
        draft_id = await check_google_play_update(db, settings.google_play_url)
        if draft_id is not None:
            draft_ids.append(draft_id)
    except Exception:
        logger.exception("Ошибка мониторинга Google Play")

    if draft_ids:
        await notify_admins(bot, settings, db, draft_ids)

    return draft_ids


async def run_scheduler(
    bot: Bot,
    settings: Settings,
    db: Database,
) -> None:
    await asyncio.sleep(10)
    while True:
        await run_radar_once(bot, settings, db)
        await asyncio.sleep(settings.parser_interval_minutes * 60)
