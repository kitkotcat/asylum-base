from __future__ import annotations

import asyncio
import contextlib
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault

from bot.app.config import Settings, load_settings
from bot.app.db import Database
from bot.app.handlers import register_routers
from bot.app.services.community_db import init_community_schema
from bot.app.services.content_db import init_content_schema
from bot.app.services.scheduler import run_scheduler


PUBLIC_COMMANDS = [
    BotCommand(command="start", description="Главное меню"),
    BotCommand(command="deals", description="Актуальные скидки"),
    BotCommand(command="promocodes", description="Активные промокоды"),
    BotCommand(command="news", description="Последние новости"),
    BotCommand(command="guides", description="Гайды по игре"),
    BotCommand(command="heroes", description="Герои"),
    BotCommand(command="squads", description="Составы и связки"),
    BotCommand(command="events", description="Календарь событий"),
    BotCommand(command="suggest", description="Предложить материал"),
    BotCommand(command="help", description="Помощь"),
]

ADMIN_COMMANDS = PUBLIC_COMMANDS + [
    BotCommand(command="admin", description="Админ-панель"),
    BotCommand(command="radar_status", description="Статус источников"),
    BotCommand(command="radar_check", description="Проверить источники"),
    BotCommand(command="report", description="Статистика"),
    BotCommand(command="promo_add", description="Добавить промокод"),
    BotCommand(command="promo_expire", description="Отключить промокод"),
    BotCommand(command="post", description="Ручная публикация"),
    BotCommand(command="hero_add", description="Добавить героя"),
    BotCommand(command="squad_add", description="Добавить состав"),
    BotCommand(command="event_add", description="Добавить событие"),
    BotCommand(command="content_add", description="Поставить контент в очередь"),
    BotCommand(command="content_queue", description="Очередь контента"),
    BotCommand(command="content_pause", description="Остановить автопост"),
    BotCommand(command="content_resume", description="Возобновить автопост"),
    BotCommand(command="suggestions", description="Предложения игроков"),
    BotCommand(command="analytics", description="Контент-аналитика"),
    BotCommand(command="id", description="ID чата и темы"),
]


async def set_commands(bot: Bot, settings: Settings) -> None:
    await bot.set_my_commands(PUBLIC_COMMANDS, scope=BotCommandScopeDefault())
    for admin_id in settings.admin_ids:
        try:
            await bot.set_my_commands(
                ADMIN_COMMANDS,
                scope=BotCommandScopeChat(chat_id=admin_id),
            )
        except Exception:
            logging.getLogger(__name__).exception(
                "Не удалось установить команды администратора %s", admin_id
            )


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    settings = load_settings()
    db = Database(settings.db_path)
    await db.init()
    await init_content_schema(db)
    await init_community_schema(db)

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = Dispatcher()
    register_routers(dispatcher)

    await bot.delete_webhook(drop_pending_updates=True)
    await set_commands(bot, settings)

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
