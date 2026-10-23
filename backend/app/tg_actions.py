"""Кнопки бота: запись на турнир из анонса, отмена записи и брони из напоминания, напоминания.

Логика отделена от aiogram: функции принимают сессию и данные пользователя Telegram и возвращают текст ответа,
поэтому их проверяют тесты без Telegram. Игрок Telegram - это аккаунт платформы (тот же, что при входе на сайт
через Telegram); если такого ещё нет, он создаётся, как при ставке на аукционе.
"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import notify
from .auction_service import get_or_create_social_user
from .config import settings
from .models import Club, ClubTable, Provider, TableBooking, Tournament, TournamentPlayer, TournamentStatus
from .reports import esc

TOURNAMENT_REMIND = timedelta(hours=24)   # напоминание о турнире - за сутки
BOOKING_REMIND = timedelta(hours=2)       # о брони - за 2 часа


def _local(dt: datetime) -> datetime:
    return dt.astimezone(ZoneInfo(settings.app_timezone))


def _when(dt: datetime) -> str:
    return _local(dt).strftime("%d.%m в %H:%M")


async def register(session: AsyncSession, tg_id: int, username: str | None, name: str | None, tid: int,
                  provider: Provider = Provider.telegram) -> str:
    """Кнопка «Записаться» под анонсом. Мест нет - ставим в лист ожидания."""
    from .routers.tournaments import FullError, join_waitlist, self_register   # роутер импортирует этот модуль не напрямую
    user = await get_or_create_social_user(session, provider, tg_id, username, name)
    t = await session.get(Tournament, tid)
    if not t:
        return "Турнир не найден"
    if (await session.execute(select(TournamentPlayer.id).where(
            TournamentPlayer.tournament_id == tid, TournamentPlayer.user_id == user.id))).first():
        return f"Вы уже записаны на «{t.name}» ({_when(t.starts_at)})."
    try:
        await self_register(session, t, user)
        await session.commit()
    except FullError:            # мест нет: ничего не записано, сразу в очередь
        try:
            pos = await join_waitlist(session, t, user)
            await session.commit()
        except HTTPException as e:
            await session.rollback()
            return str(e.detail)
        return f"Мест нет — вы в листе ожидания ({pos}-й). Освободится место — запишем и напишем вам."
    except HTTPException as e:
        await session.rollback()
        return str(e.detail)
    taken = len((await session.execute(select(TournamentPlayer.id).where(TournamentPlayer.tournament_id == tid))).all())
    seats = f" Записано {taken} из {t.max_players}." if t.max_players else f" Записано: {taken}."
    return f"✅ {user.nickname}, вы записаны на «{t.name}» ({_when(t.starts_at)}).{seats}"


async def unregister(session: AsyncSession, tg_id: int, username: str | None, name: str | None, tid: int,
                    provider: Provider = Provider.telegram) -> str:
    from .routers.tournaments import self_unregister
    user = await get_or_create_social_user(session, provider, tg_id, username, name)
    t = await session.get(Tournament, tid)
    if not t:
        return "Турнир не найден"
    try:
        done = await self_unregister(session, t, user)
        await session.commit()
    except HTTPException as e:
        await session.rollback()
        return str(e.detail)
    return f"Запись на «{t.name}» отменена." if done else "Вы не были записаны на этот турнир."


async def cancel_booking(session: AsyncSession, tg_id: int, username: str | None, name: str | None, booking_id: int,
                         provider: Provider = Provider.telegram) -> str:
    from .routers.tables import cancel_booking as cancel
    user = await get_or_create_social_user(session, provider, tg_id, username, name)
    try:
        b = await cancel(session, booking_id, user)
        await session.commit()
    except HTTPException as e:
        await session.rollback()
        return str(e.detail)
    return f"Бронь на {_when(b.starts_at)} отменена."


async def tournament_reminders(session: AsyncSession, now: datetime | None = None) -> int:
    """За сутки до турнира: записанным - напоминание с кнопкой «Отменить запись». Каждому - один раз."""
    now = now or datetime.now(timezone.utc)
    rows = (await session.execute(
        select(TournamentPlayer, Tournament, Club).join(Tournament, Tournament.id == TournamentPlayer.tournament_id)
        .join(Club, Club.id == Tournament.club_id)
        .where(TournamentPlayer.reminded.is_(False), Tournament.status == TournamentStatus.registration,
               Tournament.silent.is_(False),
               Tournament.starts_at > now + timedelta(hours=1), Tournament.starts_at <= now + TOURNAMENT_REMIND))).all()
    sent = 0
    for tp, t, club in rows:
        tp.reminded = True
        day = "Сегодня" if _local(t.starts_at).date() == _local(now).date() else "Завтра"
        sent += await notify.to_user(
            session, tp.user_id, "tournament_reminder",
            f"⏰ {day} в {_local(t.starts_at):%H:%M} — «{esc(t.name)}» в клубе «{esc(club.name)}». Вы записаны.\n"
            "Если не сможете прийти, отмените запись: место достанется следующему.",
            buttons=[[{"text": "Отменить запись", "callback_data": f"unreg:{t.id}"}]],
            dedup_key=f"remind-t:{t.id}:{tp.user_id}", club_id=t.club_id)
    await session.commit()
    return sent


async def booking_reminders(session: AsyncSession, now: datetime | None = None) -> int:
    """За 2 часа до брони - напоминание с кнопкой «Отменить бронь»."""
    now = now or datetime.now(timezone.utc)
    rows = (await session.execute(
        select(TableBooking, ClubTable.name, Club.name).join(ClubTable, ClubTable.id == TableBooking.table_id)
        .join(Club, Club.id == TableBooking.club_id)
        .where(TableBooking.reminded.is_(False), TableBooking.status == "active",
               TableBooking.starts_at > now, TableBooking.starts_at <= now + BOOKING_REMIND))).all()
    sent = 0
    for b, table, club in rows:
        b.reminded = True
        sent += await notify.to_user(
            session, b.user_id, "booking_reminder",
            f"⏰ Скоро ваша бронь: «{esc(club)}», стол «{esc(table)}», "
            f"{_local(b.starts_at):%H:%M}–{_local(b.ends_at):%H:%M}.\nНе получается прийти — отмените, чтобы стол достался другим.",
            buttons=[[{"text": "Отменить бронь", "callback_data": f"bcancel:{b.id}"}]],
            dedup_key=f"remind-b:{b.id}", club_id=b.club_id)
    await session.commit()
    return sent
