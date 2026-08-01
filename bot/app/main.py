from __future__ import annotations

import asyncio
import contextlib
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from bot.app.config import load_settings
from bot.app.db import Database
from bot.app.handlers import register_routers
from bot.app.services.scheduler import run_scheduler


async def set_commands(bot: Bot) -> None:
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Открыть главное меню"),
            BotCommand(command="promocodes", description="Активные промокоды"),
            BotCommand(command="topup", description="Пополнения и скидки"),
            BotCommand(command="news", description="Свежие новости"),
            BotCommand(command="submit", description="Предложить информацию"),
            BotCommand(command="radar_status", description="Статус Content Radar"),
            BotCommand(command="radar_check", description="Проверить источники"),
            BotCommand(command="id", description="Показать ID чата и темы"),
            BotCommand(command="help", description="Помощь"),
        ]
    )


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    settings = load_settings()
    db = Database(settings.db_path)
    await db.init()

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = Dispatcher()
    register_routers(dispatcher)

    await bot.delete_webhook(drop_pending_updates=True)
    await set_commands(bot)

    scheduler_task = asyncio.create_task(
        run_scheduler(bot=bot, settings=settings, db=db)
    )

    try:
        await dispatcher.start_polling(
            bot,
            settings=settings,
            db=db,
            allowed_updates=dispatcher.resolve_used_update_types(),
        )
    finally:
        scheduler_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await scheduler_task
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
