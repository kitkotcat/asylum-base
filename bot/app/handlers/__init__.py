from aiogram import Dispatcher

from bot.app.handlers import admin, common, promo, topup


def register_routers(dispatcher: Dispatcher) -> None:
    dispatcher.include_router(common.router)
    dispatcher.include_router(promo.router)
    dispatcher.include_router(topup.router)
    dispatcher.include_router(admin.router)
