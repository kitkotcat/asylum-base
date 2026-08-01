from __future__ import annotations

from aiogram import Bot
from aiogram.types import LinkPreviewOptions

from bot.app.config import Settings

THREAD_BY_KIND = {
    "news": "news_thread_id",
    "promo": "promo_thread_id",
    "topup": "topup_thread_id",
}


async def publish(
    bot: Bot,
    settings: Settings,
    kind: str,
    text: str,
) -> None:
    if settings.group_chat_id is None:
        raise RuntimeError("GROUP_CHAT_ID не заполнен в .env")

    thread_attr = THREAD_BY_KIND.get(kind, "news_thread_id")
    thread_id = getattr(settings, thread_attr)

    await bot.send_message(
        chat_id=settings.group_chat_id,
        message_thread_id=thread_id,
        text=text,
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )
