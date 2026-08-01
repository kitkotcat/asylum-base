from __future__ import annotations

import html

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bot.app.db import Database
from bot.app.keyboards import promos_keyboard, simple_back_keyboard
from bot.app.services.content_db import list_active_promos_extended

router = Router(name=__name__)


PROMOS_LIMIT = 20


def render_promo_text(promo: object, *, page: int, total: int) -> str:
    expires = str(promo["expires_at"] or "не указано")
    status = str(promo["verification_status"])
    source = str(promo["source"] or "не указан")
    return (
        "🎁 <b>Активный промокод</b>\n\n"
        f"Код: <code>{html.escape(str(promo['code']))}</code>\n"
        f"🎁 Награда: {html.escape(str(promo['reward']))}\n"
        f"🌍 Регион: {html.escape(str(promo['region']))}\n"
        f"⏳ Действует до: {html.escape(expires)}\n"
        f"✅ Статус: {html.escape(status)}\n"
        f"🔗 Источник: {html.escape(source)}\n"
        f"Голоса: ✅ {promo['works']} · ❌ {promo['fails']}\n\n"
        f"<i>Промокод {page + 1} из {total}</i>"
    )


async def _show_promos(
    message: Message,
    db: Database,
    *,
    page: int = 0,
    edit: bool = False,
) -> None:
    promos = await list_active_promos_extended(db, limit=PROMOS_LIMIT)
    if not promos:
        text = "🎁 Сейчас нет подтверждённых активных промокодов."
        markup = simple_back_keyboard()
    else:
        page = max(0, min(page, len(promos) - 1))
        promo = promos[page]
        text = render_promo_text(promo, page=page, total=len(promos))
        markup = promos_keyboard(
            promo_id=int(promo["id"]),
            page=page,
            total_pages=len(promos),
        )

    if edit:
        await message.edit_text(text, reply_markup=markup)
    else:
        await message.answer(text, reply_markup=markup)


@router.message(Command("promocodes"))
async def promocodes(message: Message, db: Database) -> None:
    await _show_promos(message, db)


@router.callback_query(F.data == "menu:promos")
async def promocodes_callback(callback: CallbackQuery, db: Database) -> None:
    await callback.answer()
    if callback.message is not None:
        await _show_promos(callback.message, db, edit=True)


@router.callback_query(F.data.startswith("promos:p:"))
async def promocodes_page(callback: CallbackQuery, db: Database) -> None:
    await callback.answer()
    if callback.message is None or callback.data is None:
        return
    try:
        page = int(callback.data.rsplit(":", 1)[1])
    except (TypeError, ValueError):
        return
    await _show_promos(callback.message, db, page=page, edit=True)


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
