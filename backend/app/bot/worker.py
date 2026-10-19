"""Рассылка из очереди outbox. Запускать ОДНИМ экземпляром (at-least-once: при падении
между отправкой и коммитом сообщение может уйти повторно)."""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import LinkPreviewOptions
from sqlalchemy import select

from ..botutil import MAX_ATTEMPTS, backoff_seconds, parse_chat_id
from ..db import SessionLocal
from ..models import OutboxMessage, OutboxStatus

log = logging.getLogger("outbox")


async def deliver(bot: Bot, m: OutboxMessage) -> None:
    chat = parse_chat_id(m.chat_id)
    if m.photo_url and len(m.text) <= 1024:
        try:
            await bot.send_photo(chat, m.photo_url, caption=m.text, parse_mode=m.parse_mode)
            return
        except TelegramBadRequest:
            pass  # недоступная картинка не должна терять сообщение - шлём без неё
    await bot.send_message(chat, m.text, parse_mode=m.parse_mode,
                           link_preview_options=LinkPreviewOptions(is_disabled=True))


async def process_batch(bot: Bot) -> int:
    now = datetime.now(timezone.utc)
    async with SessionLocal() as s:
        msgs = (await s.execute(select(OutboxMessage).where(
            OutboxMessage.status == OutboxStatus.pending, OutboxMessage.next_attempt_at <= now)
            .order_by(OutboxMessage.id).limit(20))).scalars().all()
        for m in msgs:
            try:
                await deliver(bot, m)
                m.status, m.sent_at, m.last_error = OutboxStatus.sent, datetime.now(timezone.utc), None
            except TelegramRetryAfter as e:                     # лимит Telegram: ждём, попытку не тратим
                m.next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=e.retry_after + 1)
                await s.commit()
                await asyncio.sleep(min(e.retry_after, 30))
                continue
            except (TelegramForbiddenError, TelegramBadRequest) as e:  # чат не найден, бот выгнан и т.п.
                m.attempts += 1
                m.status, m.last_error = OutboxStatus.failed, repr(e)[:500]
                log.warning("outbox %s failed permanently: %r", m.id, e)
            except Exception as e:  # noqa: BLE001  сеть, 5xx: повтор с нарастающей задержкой
                m.attempts += 1
                m.last_error = repr(e)[:500]
                if m.attempts >= MAX_ATTEMPTS:
                    m.status = OutboxStatus.failed
                else:
                    m.next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=backoff_seconds(m.attempts))
            await s.commit()
            await asyncio.sleep(0.05)
        return len(msgs)


async def run_outbox(bot: Bot) -> None:
    while True:
        try:
            n = await process_batch(bot)
        except Exception:  # noqa: BLE001
            log.exception("outbox batch error")
            n = 0
        await asyncio.sleep(0.5 if n else 3)
