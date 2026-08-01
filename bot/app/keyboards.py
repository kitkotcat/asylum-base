from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="🎁 Промокоды"),
                KeyboardButton(text="💳 Пополнения"),
            ],
            [
                KeyboardButton(text="📢 Новости"),
                KeyboardButton(text="📩 Предложить"),
            ],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите раздел",
    )


def topup_gate_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💳 Получить ссылку LootBar",
                    callback_data="topup:get",
                )
            ]
        ]
    )


def topup_url_keyboard(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Открыть LootBar ↗️", url=url)]
        ]
    )


def promo_vote_keyboard(promo_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
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
        ]
    )


def draft_keyboard(draft_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Опубликовать",
                    callback_data=f"draft:approve:{draft_id}",
                ),
                InlineKeyboardButton(
                    text="❌ Отклонить",
                    callback_data=f"draft:reject:{draft_id}",
                ),
            ]
        ]
    )
