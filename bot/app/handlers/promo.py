from __future__ import annotations

import html

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bot.app.db import Database
from bot.app.keyboards import promo_vote_keyboard, simple_back_keyboard
from bot.app.services.content_db import list_active_promos_extended

router = Router(name=__name__)


async def _send_promos(message: Message, db: Database) -> None:
    promos = await list_active_promos_extended(db, limit=20)
    if not promos:
        await message.answer(
            "🎁 Сейчас нет подтверждённых активных промокодов.",
            reply_markup=simple_back_keyboard(),
        )
        return

    await message.answer("🎁 <b>Активные промокоды</b>")
    for promo in promos:
        expires = str(promo["expires_at"] or "не указано")
        status = str(promo["verification_status"])
        text = (
            f"Код: <code>{html.escape(str(promo['code']))}</code>\n"
            f"🎁 Награда: {html.escape(str(promo['reward']))}\n"
            f"🌍 Регион: {html.escape(str(promo['region']))}\n"
            f"⏳ Действует до: {html.escape(expires)}\n"
            f"✅ Статус: {html.escape(status)}\n"
            f"Источник: {html.escape(str(promo['source']))}\n"
            f"Голоса: ✅ {promo['works']} · ❌ {promo['fails']}"
        )
        await message.answer(
            text,
            reply_markup=promo_vote_keyboard(int(promo["id"])),
        )


@router.message(Command("promocodes"))
async def promocodes(message: Message, db: Database) -> None:
    await _send_promos(message, db)


@router.callback_query(F.data == "menu:promos")
async def promocodes_callback(callback: CallbackQuery, db: Database) -> None:
    await callback.answer()
    if callback.message is not None:
        await callback.message.edit_text(
            "🎁 Загружаю активные промокоды…",
            reply_markup=simple_back_keyboard(),
        )
        await _send_promos(callback.message, db)


@router.callback_query(F.data.startswith("promo:vote:"))
async def promo_vote(callback: CallbackQuery, db: Database) -> None:
    if callback.data is None:
        return
    try:
        _, _, promo_id_raw, vote_raw = callback.data.split(":")
        promo_id = int(promo_id_raw)
        vote = int(vote_raw)
    except (ValueError, TypeError):
        await callback.answer("Некорректные данные", show_alert=True)
        return
    if vote not in {-1, 1}:
        await callback.answer("Некорректный голос", show_alert=True)
        return
    await db.vote_promo(promo_id, callback.from_user.id, vote)
    await callback.answer(
        "Спасибо, голос учтён: "
        + ("код работает" if vote == 1 else "код не работает")
    )
