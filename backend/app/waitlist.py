"""Лист ожидания турниров: встать в очередь, когда мест нет, и автоматическая запись при освобождении места."""
import random

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from . import notify
from .config import settings
from .models import ClubMember, Tournament, TournamentPlayer, TournamentStatus, WaitlistEntry
from .reports import esc


async def players_count(session: AsyncSession, tid: int) -> int:
    return (await session.execute(select(func.count()).select_from(TournamentPlayer).where(
        TournamentPlayer.tournament_id == tid))).scalar_one()


async def queue(session: AsyncSession, tid: int) -> list[WaitlistEntry]:
    return (await session.execute(select(WaitlistEntry).where(WaitlistEntry.tournament_id == tid)
                                  .order_by(WaitlistEntry.created_at, WaitlistEntry.id))).scalars().all()


async def position(session: AsyncSession, tid: int, user_id: int) -> int | None:
    for i, e in enumerate(await queue(session, tid), 1):
        if e.user_id == user_id:
            return i
    return None


def _when(t: Tournament) -> str:
    from zoneinfo import ZoneInfo
    return t.starts_at.astimezone(ZoneInfo(settings.app_timezone)).strftime("%d.%m в %H:%M")


async def promote(session: AsyncSession, t: Tournament) -> list[int]:
    """Записать из очереди столько, сколько есть свободных мест (без коммита). Возвращает user_id записанных."""
    if t.status != TournamentStatus.registration:
        return []
    free = None if not t.max_players else t.max_players - await players_count(session, t.id)
    moved = []
    for e in await queue(session, t.id):
        if free is not None and free <= 0:
            break
        await session.delete(e)
        exists = (await session.execute(select(TournamentPlayer.id).where(
            TournamentPlayer.tournament_id == t.id, TournamentPlayer.user_id == e.user_id))).first()
        if exists:
            continue
        if not (await session.execute(select(ClubMember.id).where(
                ClubMember.club_id == t.club_id, ClubMember.user_id == e.user_id))).first():
            session.add(ClubMember(club_id=t.club_id, user_id=e.user_id))
        session.add(TournamentPlayer(tournament_id=t.id, user_id=e.user_id, seed=random.randint(0, 10**9),
                                     bracket=e.bracket, deck_id=e.deck_id))
        await notify.to_user(session, e.user_id, "waitlist_promoted",
                             f"🎉 Освободилось место — вы записаны на «{esc(t.name)}» ({_when(t)}).\n"
                             "Если не сможете прийти, отмените запись, чтобы место досталось следующему.",
                             buttons=[[{"text": "Отменить запись", "callback_data": f"unreg:{t.id}"}]],
                             dedup_key=f"wl:{t.id}:{e.user_id}")
        moved.append(e.user_id)
        if free is not None:
            free -= 1
    await session.flush()
    return moved
