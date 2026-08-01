from __future__ import annotations

import html

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bot.app.config import Settings
from bot.app.db import Database
from bot.app.services.parsers import render_public_post
from bot.app.services.publisher import publish

router = Router(name=__name__)


def _is_admin(user_id: int | None, settings: Settings) -> bool:
    return user_id is not None and user_id in settings.admin_ids


@router.message(Command("promo_add"))
async def promo_add(
    message: Message,
    settings: Settings,
    db: Database,
) -> None:
    user_id = message.from_user.id if message.from_user else None
    if not _is_admin(user_id, settings):
        await message.answer("Команда доступна только администратору.")
        return

    payload = (message.text or "").partition(" ")[2].strip()
    parts = [part.strip() for part in payload.split("|")]
    if len(parts) != 3 or not all(parts):
        await message.answer(
            "Формат:\n"
            "<code>/promo_add CODE | Награда | Источник</code>"
        )
        return

    code, reward, source = parts
    promo_id = await db.add_promo(code, reward, source)
    await message.answer(
        f"✅ Промокод сохранён. ID: <code>{promo_id}</code>"
    )


@router.message(Command("post"))
async def manual_post(message: Message, settings: Settings) -> None:
    user_id = message.from_user.id if message.from_user else None
    if not _is_admin(user_id, settings):
        await message.answer("Команда доступна только администратору.")
        return

    payload = (message.text or "").partition(" ")[2].strip()
    kind, separator, text = payload.partition("|")
    kind = kind.strip().lower()
    text = text.strip()

    if not separator or kind not in {"news", "promo", "topup"} or not text:
        await message.answer(
            "Формат:\n"
            "<code>/post news | Текст новости</code>\n"
            "<code>/post promo | Текст промо</code>\n"
            "<code>/post topup | Текст предложения</code>"
        )
        return

    try:
        await publish(
            bot=message.bot,
            settings=settings,
            kind=kind,
            text=html.escape(text),
        )
    except RuntimeError as exc:
        await message.answer(f"⚠️ {html.escape(str(exc))}")
        return

    await message.answer("✅ Пост опубликован.")


@router.callback_query(F.data.startswith("draft:"))
async def moderate_draft(
    callback: CallbackQuery,
    settings: Settings,
    db: Database,
) -> None:
    if not _is_admin(callback.from_user.id, settings):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    if callback.data is None:
        return

    try:
        _, action, draft_id_raw = callback.data.split(":")
        draft_id = int(draft_id_raw)
    except (ValueError, TypeError):
        await callback.answer("Некорректные данные", show_alert=True)
        return

    draft = await db.get_draft(draft_id)
    if draft is None:
        await callback.answer("Черновик не найден", show_alert=True)
        return
    if str(draft["status"]) != "pending":
        await callback.answer("Черновик уже обработан", show_alert=True)
        return

    if action == "reject":
        await db.set_draft_status(draft_id, "rejected")
        await callback.answer("Черновик отклонён")
        if callback.message is not None:
            await callback.message.edit_reply_markup(reply_markup=None)
        return

    if action != "approve":
        await callback.answer("Неизвестное действие", show_alert=True)
        return

    text = render_public_post(
        title=str(draft["title"]),
        summary=str(draft["summary"]),
        link=str(draft["link"]),
    )

    try:
        await publish(
            bot=callback.bot,
            settings=settings,
            kind=str(draft["kind"]),
            text=text,
        )
    except RuntimeError as exc:
        await callback.answer(str(exc), show_alert=True)
        return

    await db.set_draft_status(draft_id, "published")
    await callback.answer("Опубликовано")
    if callback.message is not None:
        await callback.message.edit_reply_markup(reply_markup=None)
