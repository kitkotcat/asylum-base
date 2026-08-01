from __future__ import annotations

import html

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bot.app.db import Database
from bot.app.keyboards import promo_vote_keyboard

router = Router(name=__name__)


@router.message(Command("promocodes"))
@router.message(F.text == "🎁 Промокоды")
async def promocodes(message: Message, db: Database) -> None:
    promos = await db.list_active_promos()
    if not promos:
        await message.answer(
            "🎁 Сейчас в базе нет подтверждённых активных промокодов."
        )
        return

    await message.answer("🎁 <b>Активные промокоды</b>")
    for promo in promos:
        text = (
            f"Код: <code>{html.escape(str(promo['code']))}</code>\n"
            f"Награда: {html.escape(str(promo['reward']))}\n"
            f"Источник: {html.escape(str(promo['source']))}\n"
            f"✅ {promo['works']}   ❌ {promo['fails']}"
        )
        await message.answer(
            text,
            reply_markup=promo_vote_keyboard(int(promo["id"])),
        )


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
