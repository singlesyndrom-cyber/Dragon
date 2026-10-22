"""Служебные задачи процесса бота: пульс для мониторинга и отправка резервной копии администраторам."""
import asyncio
import logging
import os

from aiogram import Bot
from aiogram.types import FSInputFile
from sqlalchemy import select

from .. import system
from ..db import SessionLocal
from ..models import AuthAccount, GlobalRole, Provider, User

log = logging.getLogger("bot.system")
TG_FILE_LIMIT = 45 * 1024 * 1024   # бот может отправить файл до 50 МБ


async def heartbeat_loop() -> None:
    while True:
        try:
            async with SessionLocal() as s:
                await system.set_status(s, system.HEARTBEAT, "")
                await s.commit()
        except Exception:  # noqa: BLE001
            log.exception("не удалось записать пульс")
        await asyncio.sleep(60)


async def send_new_backup(bot: Bot) -> str | None:
    """Новую облегчённую копию - администраторам с привязанным Telegram (каждую один раз)."""
    info = system.backups_info()
    last = info.get("last") or {}
    name = last.get("light")
    if not last.get("ok") or not name:
        return None
    async with SessionLocal() as s:
        sent = await system.get_status(s, "backup_sent")
        if sent and sent.value == name:
            return None
        chats = (await s.execute(select(AuthAccount.external_id).join(User, User.id == AuthAccount.user_id).where(
            User.role == GlobalRole.admin, AuthAccount.provider == Provider.telegram))).scalars().all()
        path = os.path.join(system.settings.backups_dir, name)
        size = os.path.getsize(path) if os.path.exists(path) else 0
        if not size:
            return None
        for chat in chats:
            if size > TG_FILE_LIMIT:
                await bot.send_message(int(chat), f"🗄 Резервная копия {name} готова ({size // 1024 // 1024} МБ), "
                                                  "но слишком большая для Telegram — она лежит на сервере в /opt/dragon/backups.")
            else:
                await bot.send_document(int(chat), FSInputFile(path), caption=(
                    f"🗄 Резервная копия базы Dragon ({size // 1024} КБ, без базы карт).\n"
                    "Как восстановить: deploy/backup/README.md"))
        await system.set_status(s, "backup_sent", name)
        await s.commit()
    log.info("копия %s отправлена: %s", name, len(chats))
    return name


async def backup_sender_loop(bot: Bot) -> None:
    await asyncio.sleep(60)
    while True:
        try:
            await send_new_backup(bot)
        except Exception:  # noqa: BLE001
            log.exception("не удалось отправить резервную копию")
        await asyncio.sleep(600)
