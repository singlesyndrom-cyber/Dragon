"""Запуск: python -m app.bot.main  (отдельный процесс, см. сервис bot в docker-compose)."""
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession

from .. import scryfall
from ..config import settings
from . import auctions, handlers
from .worker import run_outbox


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    if not settings.telegram_bot_token:
        raise SystemExit("TELEGRAM_BOT_TOKEN не задан")
    session = AiohttpSession(proxy=settings.telegram_proxy) if settings.telegram_proxy else None
    if session:
        logging.info("Telegram через прокси %s", settings.telegram_proxy.split("@")[-1])
    bot = Bot(settings.telegram_bot_token, session=session)
    dp = Dispatcher()
    auctions.BOT["username"] = (await bot.get_me()).username or ""
    dp.include_router(auctions.router)   # раньше handlers: /start с параметром ставки
    dp.include_router(handlers.router)
    tasks = [asyncio.create_task(run_outbox(bot)), asyncio.create_task(auctions.finish_loop(bot))]
    if settings.scryfall_auto_sync:
        tasks.append(asyncio.create_task(scryfall.auto_sync_loop()))
    try:
        await dp.start_polling(bot)
    finally:
        for t in tasks:
            t.cancel()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
