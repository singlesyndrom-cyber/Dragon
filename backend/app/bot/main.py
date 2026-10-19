"""Запуск: python -m app.bot.main  (отдельный процесс, см. сервис bot в docker-compose)."""
import asyncio
import logging

from aiogram import Bot, Dispatcher

from ..config import settings
from . import handlers
from .worker import run_outbox


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    if not settings.telegram_bot_token:
        raise SystemExit("TELEGRAM_BOT_TOKEN не задан")
    bot = Bot(settings.telegram_bot_token)
    dp = Dispatcher()
    dp.include_router(handlers.router)
    sender = asyncio.create_task(run_outbox(bot))
    try:
        await dp.start_polling(bot)
    finally:
        sender.cancel()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
