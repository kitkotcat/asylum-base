from __future__ import annotations

import html
import math

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bot.app.config import Settings
from bot.app.db import Database
from bot.app.keyboards import deals_keyboard
from bot.app.services.content import clean_condition, money
from bot.app.services.content_db import list_lootbar_packages_page

router = Router(name=__name__)


async def _render_deals(
    db: Database,
    settings: Settings,
    *,
    page: int,
) -> tuple[str, int, int]:
    if not settings.lootbar_page_url:
        return "🔥 Монитор предложений пока не подключён.", 0, 1

    rows, total = await list_lootbar_packages_page(
        db,
        settings.lootbar_page_url,
        page=page,
        page_size=settings.deals_page_size,
    )
    total_pages = max(math.ceil(total / settings.deals_page_size), 1)
    safe_page = min(max(page, 0), total_pages - 1)
    if safe_page != page:
        rows, total = await list_lootbar_packages_page(
            db,
            settings.lootbar_page_url,
            page=safe_page,
            page_size=settings.deals_page_size,
        )

    if not rows:
        return (
            "🔥 <b>Актуальные скидки</b>\n\n"
            "Пакеты ещё загружаются. Попробуйте немного позже.",
            safe_page,
            total_pages,
        )

    lines = [
        "🔥 <b>Актуальные предложения LootBar</b>",
        "",
        "Акционная цена может требовать купон.",
        "",
    ]
    start_number = safe_page * settings.deals_page_size + 1
    for index, row in enumerate(rows, start=start_number):
        currency = str(row["currency"])
        name = html.escape(str(row["name"]))
        promo = money(int(row["promo_price_minor"]), currency)
        official = money(int(row["official_price_minor"]), currency)
        savings = money(int(row["savings_minor"]), currency)
        condition = clean_condition(
            str(row["discount_badge"]),
            str(row["coupon_name"]),
        )
        lines.append(f"<b>{index}. {name}</b>")
        lines.append(f"{promo} вместо {official} · экономия {savings}")
        if condition:
            lines.append(f"🏷 {html.escape(condition)}")
        lines.append("")

    lines.append(
        "<i>Проверьте регион, условия купона и итоговую цену перед оплатой.</i>"
    )
    return "\n".join(lines), safe_page, total_pages


@router.message(Command("deals"))
@router.message(Command("topup"))
async def deals(message: Message, settings: Settings, db: Database) -> None:
    text, page, total_pages = await _render_deals(db, settings, page=0)
    await message.answer(
        text,
        reply_markup=deals_keyboard(
            page=page,
            total_pages=total_pages,
            affiliate_url=settings.lootbar_affiliate_url,
        ),
    )


@router.callback_query(F.data == "menu:deals")
async def deals_menu(callback: CallbackQuery, settings: Settings, db: Database) -> None:
    await db.log_referral_click(callback.from_user.id, "menu_deals_open")
    await callback.answer()
    text, page, total_pages = await _render_deals(db, settings, page=0)
    if callback.message is not None:
        await callback.message.edit_text(
            text,
            reply_markup=deals_keyboard(
                page=page,
                total_pages=total_pages,
                affiliate_url=settings.lootbar_affiliate_url,
            ),
        )


@router.callback_query(F.data.startswith("deals:p:"))
async def deals_page(callback: CallbackQuery, settings: Settings, db: Database) -> None:
    try:
        page = int((callback.data or "").rsplit(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Некорректная страница", show_alert=True)
        return
    await callback.answer()
    text, safe_page, total_pages = await _render_deals(db, settings, page=page)
    if callback.message is not None:
        await callback.message.edit_text(
            text,
            reply_markup=deals_keyboard(
                page=safe_page,
                total_pages=total_pages,
                affiliate_url=settings.lootbar_affiliate_url,
            ),
        )


@router.callback_query(F.data == "deals:noop")
async def deals_noop(callback: CallbackQuery) -> None:
    await callback.answer()
