"""Кнопки клубных сообщений: запись на турнир из анонса, отмена записи и брони; фоновые напоминания и анонсы."""
import asyncio
import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery

from .. import notify, tg_actions
from ..db import SessionLocal

router = Router()
log = logging.getLogger("bot.club_events")


def _who(cb: CallbackQuery) -> tuple[int, str | None, str | None]:
    u = cb.from_user
    return u.id, u.username, " ".join(x for x in (u.first_name, u.last_name) if x) or None


async def _answer(cb: CallbackQuery, action, arg: int) -> None:
    async with SessionLocal() as s:
        try:
            text = await action(s, *_who(cb), arg)
        except Exception:  # noqa: BLE001
            log.exception("кнопка %s", cb.data)
            text = "Не получилось, попробуйте ещё раз или запишитесь на сайте."
    await cb.answer(text[:200], show_alert=True)


@router.callback_query(F.data.startswith("reg:"))
async def on_register(cb: CallbackQuery):
    await _answer(cb, tg_actions.register, int(cb.data.split(":")[1]))


@router.callback_query(F.data.startswith("unreg:"))
async def on_unregister(cb: CallbackQuery):
    await _answer(cb, tg_actions.unregister, int(cb.data.split(":")[1]))


@router.callback_query(F.data.startswith("bcancel:"))
async def on_cancel_booking(cb: CallbackQuery):
    await _answer(cb, tg_actions.cancel_booking, int(cb.data.split(":")[1]))


async def reminders_loop() -> None:
    """Раз в 5 минут: анонсы турниров серий (за неделю), напоминания о турнирах (за сутки) и бронях (за 2 часа)."""
    await asyncio.sleep(30)
    while True:
        for job in (notify.announce_due, tg_actions.tournament_reminders, tg_actions.booking_reminders):
            try:
                async with SessionLocal() as s:
                    await job(s)
            except Exception:  # noqa: BLE001
                log.exception("фоновая задача %s", job.__name__)
        await asyncio.sleep(300)
