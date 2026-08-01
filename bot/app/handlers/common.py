from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from bot.app.db import Database
from bot.app.keyboards import main_menu

router = Router(name=__name__)


async def _remember_user(message: Message, db: Database) -> None:
    if message.from_user is None:
        return
    await db.upsert_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
    )


@router.message(CommandStart())
async def start(message: Message, db: Database) -> None:
    await _remember_user(message, db)
    await message.answer(
        "🛡 <b>Asylum Base</b>\n\n"
        "Новости, промокоды и выгодные предложения для игроков.\n\n"
        "Проект не является официальным сообществом игры. "
        "Партнёрские ссылки помечаются в публикациях.",
        reply_markup=main_menu(),
    )


@router.message(Command("help"))
async def help_command(message: Message) -> None:
    await message.answer(
        "Доступные команды:\n"
        "/start — главное меню\n"
        "/promocodes — активные промокоды\n"
        "/topup — предложения LootBar\n"
        "/news — новости\n"
        "/submit — предложить информацию\n"
        "/id — ID чата и темы\n"
        "/help — помощь"
    )


@router.message(Command("news"))
@router.message(F.text == "📢 Новости")
async def news(message: Message) -> None:
    await message.answer(
        "📢 Новости будут публиковаться в группе "
        "после проверки администратором."
    )


@router.message(Command("submit"))
@router.message(F.text == "📩 Предложить")
async def submit(message: Message) -> None:
    await message.answer(
        "Пришлите администратору ссылку на новость или промокод. "
        "Отдельную форму добавим после запуска основной версии."
    )


@router.message(Command("id"))
async def show_ids(message: Message) -> None:
    await message.answer(
        "<b>Технические идентификаторы</b>\n"
        f"user_id: <code>{message.from_user.id if message.from_user else '—'}</code>\n"
        f"chat_id: <code>{message.chat.id}</code>\n"
        f"message_thread_id: <code>{message.message_thread_id}</code>"
    )
