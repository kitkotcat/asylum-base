from __future__ import annotations

import html

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

from bot.app.config import Settings
from bot.app.db import Database
from bot.app.keyboards import main_menu, simple_back_keyboard
from bot.app.services.content_db import list_recent_publications

router = Router(name=__name__)


async def _remember_user(message: Message, db: Database) -> None:
    if message.from_user is None:
        return
    await db.upsert_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
    )


def _welcome_text() -> str:
    return (
        "🛡 <b>Asylum Base</b>\n\n"
        "Полезный помощник для игроков Last Asylum: Plague:\n"
        "🔥 актуальные скидки на пополнение\n"
        "🎁 проверенные промокоды\n"
        "📰 новости и обновления\n"
        "📘 гайды по игре\n\n"
        "Проект не является официальным сообществом игры. "
        "Партнёрские ссылки помечаются в публикациях."
    )


@router.message(CommandStart())
async def start(message: Message, settings: Settings, db: Database) -> None:
    await _remember_user(message, db)
    menu_message = await message.answer(
        "Открываю меню…",
        reply_markup=ReplyKeyboardRemove(),
    )
    await menu_message.edit_text(
        _welcome_text(),
        reply_markup=main_menu(community_url=settings.community_url),
    )


@router.callback_query(F.data == "menu:home")
async def menu_home(callback: CallbackQuery, settings: Settings) -> None:
    await callback.answer()
    if callback.message is not None:
        await callback.message.edit_text(
            _welcome_text(),
            reply_markup=main_menu(community_url=settings.community_url),
        )


@router.message(Command("help"))
async def help_command(message: Message, settings: Settings) -> None:
    await message.answer(
        "🆘 <b>Помощь</b>\n\n"
        "/start — главное меню\n"
        "/deals — актуальные предложения\n"
        "/promocodes — промокоды\n"
        "/news — последние новости\n"
        "/guides — полезные гайды\n"
        "/help — эта справка\n\n"
        "Цены и условия предложений могут меняться. "
        "Перед оплатой всегда проверяйте регион, пакет и итоговую стоимость.",
        reply_markup=main_menu(community_url=settings.community_url),
    )


async def _news_text(db: Database) -> str:
    rows = await list_recent_publications(db, kinds=("news", "google_play"), limit=5)
    if not rows:
        return (
            "📰 <b>Новости</b>\n\n"
            "Пока нет опубликованных новостей. "
            "Бот проверяет источники автоматически."
        )
    lines = ["📰 <b>Последние новости</b>", ""]
    for row in rows:
        title = html.escape(str(row["title"]))
        url = html.escape(str(row["target_url"]), quote=True)
        if url:
            lines.append(f'• <a href="{url}">{title}</a>')
        else:
            lines.append(f"• {title}")
    return "\n".join(lines)


@router.message(Command("news"))
async def news(message: Message, db: Database) -> None:
    await message.answer(
        await _news_text(db),
        reply_markup=simple_back_keyboard(),
        disable_web_page_preview=True,
    )


@router.callback_query(F.data == "menu:news")
async def news_callback(callback: CallbackQuery, db: Database) -> None:
    await callback.answer()
    if callback.message is not None:
        await callback.message.edit_text(
            await _news_text(db),
            reply_markup=simple_back_keyboard(),
            disable_web_page_preview=True,
        )


def _guides_text() -> str:
    return (
        "📘 <b>Гайды по Last Asylum</b>\n\n"
        "• старт и развитие базы\n"
        "• герои и составы отрядов\n"
        "• события и ежедневные активности\n"
        "• альянсы и совместная игра\n\n"
        "Материалы публикуются и обновляются в нашем сообществе."
    )


@router.message(Command("guides"))
async def guides(message: Message, settings: Settings) -> None:
    await message.answer(
        _guides_text(),
        reply_markup=simple_back_keyboard(
            url=settings.guides_url or settings.community_url,
            label="📘 Открыть гайды",
        ),
    )


@router.callback_query(F.data == "menu:guides")
async def guides_callback(callback: CallbackQuery, settings: Settings) -> None:
    await callback.answer()
    if callback.message is not None:
        await callback.message.edit_text(
            _guides_text(),
            reply_markup=simple_back_keyboard(
                url=settings.guides_url or settings.community_url,
                label="📘 Открыть гайды",
            ),
        )
