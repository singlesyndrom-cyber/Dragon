"""Кнопки бота: запись на турнир из анонса, отмена записи и брони из напоминания, напоминания.

Логика отделена от aiogram: функции принимают сессию и данные пользователя Telegram и возвращают текст ответа,
поэтому их проверяют тесты без Telegram. Кнопка записывает по номеру игрока, к которому привязан Telegram/VK
(в кабинете или входом через них). Не привязан - ответ NeedLink: одноразовая ссылка, где игрок входит
и привязывает аккаунт (или создаёт новый), и запись делается там же. Аккаунты-дубли молча не создаются.
"""
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import notify
from .config import settings
from .models import (AuthAccount, Club, ClubTable, LinkCode, Provider, TableBooking, Tournament, TournamentPlayer,
                     TournamentStatus, User)
from .reports import esc

TOURNAMENT_REMIND = timedelta(hours=24)   # напоминание о турнире - за сутки
BOOKING_REMIND = timedelta(hours=2)       # о брони - за 2 часа


def _local(dt: datetime) -> datetime:
    return dt.astimezone(ZoneInfo(settings.app_timezone))


def _when(dt: datetime) -> str:
    return _local(dt).strftime("%d.%m в %H:%M")


LINK_TTL = timedelta(days=3)


@dataclass
class NeedLink:
    """Telegram или VK ещё не связан с номером игрока: вместо записи - ссылка на подтверждение."""
    code: str
    text: str


async def find_social_user(session: AsyncSession, provider: Provider, ext_id: int | str,
                           username: str | None = None) -> User | None:
    """Аккаунт сайта, к которому привязан этот Telegram или VK (в кабинете или входом через них)."""
    acc = (await session.execute(select(AuthAccount).where(
        AuthAccount.provider == provider, AuthAccount.external_id == str(ext_id)))).scalar_one_or_none()
    if not acc:
        return None
    user = await session.get(User, acc.user_id)
    if provider == Provider.telegram and username and user.tg_username != username:
        user.tg_username = username
        await session.commit()
    return user


async def make_link_code(session: AsyncSession, provider: Provider, ext_id: int | str, username: str | None,
                         name: str | None, tid: int | None) -> str:
    code = secrets.token_urlsafe(18)
    session.add(LinkCode(code=code, provider=provider, external_id=str(ext_id), username=username,
                         display_name=(name or "")[:128] or None, tournament_id=tid))
    await session.commit()
    return code


async def register_user(session: AsyncSession, user: User, t: Tournament) -> str:
    """Записать игрока; мест нет - в лист ожидания. Текст ответа для кнопки или страницы."""
    from .routers.tournaments import FullError, join_waitlist, self_register   # роутер импортирует этот модуль не напрямую
    if (await session.execute(select(TournamentPlayer.id).where(
            TournamentPlayer.tournament_id == t.id, TournamentPlayer.user_id == user.id))).first():
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
    taken = len((await session.execute(select(TournamentPlayer.id).where(TournamentPlayer.tournament_id == t.id))).all())
    seats = f" Записано {taken} из {t.max_players}." if t.max_players else f" Записано: {taken}."
    return f"✅ {user.nickname} (№{user.player_no}), вы записаны на «{t.name}» ({_when(t.starts_at)}).{seats}"


async def register(session: AsyncSession, tg_id: int, username: str | None, name: str | None, tid: int,
                   provider: Provider = Provider.telegram) -> str | NeedLink:
    """Кнопка «Записаться» под анонсом: запись по номеру игрока, к которому привязан этот Telegram/VK.
    Не привязан - ссылка: войти и привязать (или создать аккаунт), запись произойдёт там же."""
    t = await session.get(Tournament, tid)
    if not t:
        return "Турнир не найден"
    user = await find_social_user(session, provider, tg_id, username)
    if user is None:
        if t.status != TournamentStatus.registration:
            return "Регистрация закрыта"
        code = await make_link_code(session, provider, tg_id, username, name, tid)
        where = "Telegram" if provider == Provider.telegram else "ВКонтакте"
        return NeedLink(code, f"Ваш {where} ещё не связан с номером игрока. Откройте ссылку: войдите на сайт — "
                              f"мы привяжем {where} и сразу запишем вас на «{t.name}».")
    return await register_user(session, user, t)


async def unregister(session: AsyncSession, tg_id: int, username: str | None, name: str | None, tid: int,
                     provider: Provider = Provider.telegram) -> str:
    from .routers.tournaments import self_unregister
    t = await session.get(Tournament, tid)
    if not t:
        return "Турнир не найден"
    user = await find_social_user(session, provider, tg_id, username)
    if user is None:
        return "Вы не были записаны на этот турнир."
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
    user = await find_social_user(session, provider, tg_id, username)
    if user is None:
        return "Отменить бронь может тот, кто бронировал, или организатор клуба"
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
