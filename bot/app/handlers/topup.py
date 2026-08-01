from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bot.app.config import Settings
from bot.app.db import Database
from bot.app.keyboards import topup_gate_keyboard, topup_url_keyboard

router = Router(name=__name__)


@router.message(Command("topup"))
@router.message(F.text == "💳 Пополнения")
async def topup(message: Message, settings: Settings) -> None:
    if not settings.lootbar_affiliate_url:
        await message.answer(
            "💳 Раздел пополнений готов. "
            "Партнёрская ссылка LootBar ещё не подключена."
        )
        return

    await message.answer(
        "💳 <b>Пополнения и предложения LootBar</b>\n\n"
        "Перед оплатой проверьте регион, выбранный пакет "
        "и итоговую стоимость.\n\n"
        "ℹ️ Ссылка партнёрская: проект может получить комиссию "
        "без увеличения цены для пользователя.",
        reply_markup=topup_gate_keyboard(),
    )


@router.callback_query(F.data == "topup:get")
async def topup_click(
    callback: CallbackQuery,
    settings: Settings,
    db: Database,
) -> None:
    if not settings.lootbar_affiliate_url:
        await callback.answer("Ссылка пока не подключена", show_alert=True)
        return

    await db.log_referral_click(
        telegram_id=callback.from_user.id,
        campaign="bot_topup_menu",
    )
    await callback.answer("Ссылка подготовлена")

    if callback.message is not None:
        await callback.message.answer(
            "Нажмите кнопку ниже, чтобы открыть предложение:",
            reply_markup=topup_url_keyboard(
                settings.lootbar_affiliate_url
            ),
        )
