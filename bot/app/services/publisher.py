from __future__ import annotations

import hashlib
import logging
from typing import Any, Mapping
from urllib.parse import urlencode

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions, Message

from bot.app.config import Settings
from bot.app.db import Database
from bot.app.services.content import render_public_caption
from bot.app.services.content_db import (
    draft_content_key,
    entity_published_recently,
    get_draft_with_payload,
    publication_exists,
    record_publication,
)

logger = logging.getLogger(__name__)

THREAD_BY_KIND = {
    "news": "news_thread_id",
    "google_play": "news_thread_id",
    "promo": "promo_thread_id",
    "deal": "topup_thread_id",
    "deal_digest": "topup_thread_id",
    "topup": "topup_thread_id",
    "guide": "guides_thread_id",
    "hero": "heroes_thread_id",
    "squad": "heroes_thread_id",
    "event": "news_thread_id",
    "alliance": "alliance_thread_id",
}


def thread_id_for_kind(settings: Settings, kind: str) -> int:
    thread_attr = THREAD_BY_KIND.get(kind)
    if thread_attr is None:
        raise RuntimeError(f"Неизвестный тип публикации: {kind}")
    thread_id = getattr(settings, thread_attr)
    if thread_id is None:
        env_name = thread_attr.upper()
        raise RuntimeError(f"{env_name} не заполнен в .env")
    return thread_id


def target_url(settings: Settings, raw_url: str, *, campaign: str) -> str:
    if not settings.tracked_redirect_base_url:
        return raw_url
    query = urlencode({"to": raw_url, "campaign": campaign})
    separator = "&" if "?" in settings.tracked_redirect_base_url else "?"
    return f"{settings.tracked_redirect_base_url}{separator}{query}"


def cta_keyboard(
    kind: str,
    url: str,
    *,
    metadata: Mapping[str, Any] | None = None,
) -> InlineKeyboardMarkup | None:
    rows: list[list[InlineKeyboardButton]] = []
    metadata = metadata or {}

    if url:
        if kind in {"deal", "deal_digest", "topup"}:
            text = "💳 Купить со скидкой"
        elif kind == "promo":
            text = "🎁 Активировать код"
        else:
            text = "🔗 Читать полностью"
        rows.append([InlineKeyboardButton(text=text, url=url)])

    if kind == "promo" and metadata.get("promo_id"):
        promo_id = int(metadata["promo_id"])
        rows.append(
            [
                InlineKeyboardButton(
                    text="✅ Работает",
                    callback_data=f"promo:vote:{promo_id}:1",
                ),
                InlineKeyboardButton(
                    text="❌ Не работает",
                    callback_data=f"promo:vote:{promo_id}:-1",
                ),
            ]
        )

    if not rows:
        return None
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def publish(
    bot: Bot,
    settings: Settings,
    kind: str,
    text: str,
) -> Message:
    if settings.group_chat_id is None:
        raise RuntimeError("GROUP_CHAT_ID не заполнен в .env")
    thread_id = thread_id_for_kind(settings, kind)
    return await bot.send_message(
        chat_id=settings.group_chat_id,
        message_thread_id=thread_id,
        text=text,
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


async def publish_draft(
    bot: Bot,
    settings: Settings,
    db: Database,
    draft_id: int,
    *,
    auto_published: bool,
) -> Message | None:
    draft = await get_draft_with_payload(db, draft_id)
    if draft is None:
        raise RuntimeError(f"Черновик {draft_id} не найден")

    content_key = draft_content_key(draft)
    if await publication_exists(db, content_key):
        await db.set_draft_status(draft_id, "published")
        return None

    kind = str(draft["kind"])
    entity_key = str(draft.get("entity_key") or "")
    if auto_published and kind == "deal" and await entity_published_recently(
        db, entity_key, hours=settings.deal_cooldown_hours
    ):
        await db.set_draft_status(draft_id, "cooldown")
        return None

    if settings.group_chat_id is None:
        raise RuntimeError("GROUP_CHAT_ID не заполнен в .env")

    thread_id = thread_id_for_kind(settings, kind)
    raw_url = str(draft.get("link") or "")
    campaign = hashlib.sha1(content_key.encode("utf-8")).hexdigest()[:12]
    url = target_url(settings, raw_url, campaign=campaign)
    caption = render_public_caption(draft)
    metadata = draft.get("metadata") or {}
    keyboard = (
        cta_keyboard(kind, url, metadata=metadata)
        if url or kind == "promo"
        else None
    )
    image_url = str(draft.get("image_url") or "")
    sent: Message | None = None

    try:
        if image_url and kind in {"deal", "guide", "hero", "squad", "event", "alliance"}:
            try:
                sent = await bot.send_photo(
                    chat_id=settings.group_chat_id,
                    message_thread_id=thread_id,
                    photo=image_url,
                    caption=caption,
                    reply_markup=keyboard,
                )
            except Exception:
                logger.exception(
                    "Image failed for %s; falling back to text: %s",
                    kind,
                    image_url,
                )

        if sent is None:
            sent = await bot.send_message(
                chat_id=settings.group_chat_id,
                message_thread_id=thread_id,
                text=caption,
                reply_markup=keyboard,
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            )

        await record_publication(
            db,
            content_key=content_key,
            draft_id=draft_id,
            kind=kind,
            entity_key=entity_key,
            title=str(draft["title"]),
            target_chat_id=settings.group_chat_id,
            thread_id=thread_id,
            telegram_message_id=sent.message_id,
            target_url=url,
            status="published",
            auto_published=auto_published,
        )
        await db.set_draft_status(draft_id, "published")
        return sent
    except Exception as exc:
        await record_publication(
            db,
            content_key=content_key,
            draft_id=draft_id,
            kind=kind,
            entity_key=entity_key,
            title=str(draft["title"]),
            target_chat_id=settings.group_chat_id,
            thread_id=thread_id,
            telegram_message_id=None,
            target_url=url,
            status="failed",
            auto_published=auto_published,
            error=f"{type(exc).__name__}: {exc}",
        )
        raise
