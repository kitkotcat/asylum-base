from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu(*, community_url: str = "") -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="🔥 Скидки", callback_data="menu:deals"),
            InlineKeyboardButton(text="🎁 Промокоды", callback_data="menu:promos"),
        ],
        [
            InlineKeyboardButton(text="📰 Новости", callback_data="menu:news"),
            InlineKeyboardButton(text="📘 Гайды", callback_data="menu:guides"),
        ],
    ]
    if community_url:
        rows.append([InlineKeyboardButton(text="💬 Наше сообщество", url=community_url)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def deals_keyboard(
    *,
    page: int,
    total_pages: int,
    affiliate_url: str,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    navigation: list[InlineKeyboardButton] = []
    if page > 0:
        navigation.append(InlineKeyboardButton(text="◀️", callback_data=f"deals:p:{page - 1}"))
    navigation.append(InlineKeyboardButton(text=f"{page + 1}/{max(total_pages, 1)}", callback_data="deals:noop"))
    if page + 1 < total_pages:
        navigation.append(InlineKeyboardButton(text="▶️", callback_data=f"deals:p:{page + 1}"))
    rows.append(navigation)
    if affiliate_url:
        rows.append([InlineKeyboardButton(text="💳 Открыть LootBar", url=affiliate_url)])
    rows.append([InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def simple_back_keyboard(*, url: str = "", label: str = "Открыть") -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if url:
        rows.append([InlineKeyboardButton(text=label, url=url)])
    rows.append([InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def promos_keyboard(
    *,
    promo_id: int,
    page: int,
    total_pages: int,
) -> InlineKeyboardMarkup:
    navigation: list[InlineKeyboardButton] = []
    if page > 0:
        navigation.append(
            InlineKeyboardButton(
                text="◀️",
                callback_data=f"promos:p:{page - 1}",
            )
        )
    navigation.append(
        InlineKeyboardButton(
            text=f"{page + 1}/{max(total_pages, 1)}",
            callback_data="promos:noop",
        )
    )
    if page + 1 < total_pages:
        navigation.append(
            InlineKeyboardButton(
                text="▶️",
                callback_data=f"promos:p:{page + 1}",
            )
        )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            navigation,
            [
                InlineKeyboardButton(
                    text="✅ Работает",
                    callback_data=f"promo:vote:{promo_id}:1",
                ),
                InlineKeyboardButton(
                    text="❌ Не работает",
                    callback_data=f"promo:vote:{promo_id}:-1",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🏠 Главное меню",
                    callback_data="menu:home",
                )
            ],
        ]
    )


def promo_vote_keyboard(promo_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Работает", callback_data=f"promo:vote:{promo_id}:1"),
                InlineKeyboardButton(text="❌ Не работает", callback_data=f"promo:vote:{promo_id}:-1"),
            ]
        ]
    )


def draft_keyboard(draft_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Опубликовать", callback_data=f"draft:approve:{draft_id}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"draft:reject:{draft_id}"),
            ]
        ]
    )


def admin_panel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📡 Проверить источники", callback_data="admin:radar"),
                InlineKeyboardButton(text="📝 Черновики", callback_data="admin:drafts"),
            ],
            [
                InlineKeyboardButton(text="📊 Отчёт", callback_data="admin:report"),
                InlineKeyboardButton(text="⚙️ Статус", callback_data="admin:status"),
            ],
        ]
    )
