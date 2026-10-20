from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import leagues as L
from ..config import settings
from ..db import get_session
from ..deps import current_user, is_club_organizer
from ..models import Club, League, LeagueKind, Tournament, User

router = APIRouter(prefix="/leagues", tags=["leagues"])


def today() -> date:
    return datetime.now(ZoneInfo(settings.app_timezone)).date()


class LeagueIn(BaseModel):
    club_id: int
    name: str = Field(min_length=2, max_length=128)
    kind: LeagueKind
    months: Literal[1, 2, 3]
    starts_on: date | None = None          # по умолчанию - сегодня
    description: str = Field(default="", max_length=3000)


async def _get(session: AsyncSession, lid: int) -> League:
    league = await session.get(League, lid)
    if not league:
        raise HTTPException(404, "Сезон не найден")
    return league


@router.post("", status_code=201)
async def create_league(data: LeagueIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    if not await is_club_organizer(session, data.club_id, user):
        raise HTTPException(403, "Нужны права организатора клуба")
    start = data.starts_on or today()
    if start < today():
        raise HTTPException(400, "Сезон не может начинаться в прошлом")
    end = L.season_end(start, data.months)
    # два сезона одного вида в клубе не должны пересекаться: иначе непонятно, куда идёт ивент
    overlap = (await session.execute(select(League).where(
        League.club_id == data.club_id, League.kind == data.kind, League.closed.is_(False),
        League.starts_on <= end, League.ends_on >= start))).scalars().first()
    if overlap:
        raise HTTPException(409, f"В эти даты уже идёт сезон «{overlap.name}» ({overlap.starts_on:%d.%m}–{overlap.ends_on:%d.%m})")
    league = League(club_id=data.club_id, name=data.name.strip(), kind=data.kind, months=data.months,
                    starts_on=start, ends_on=end, description=data.description.strip(), created_by=user.id)
    session.add(league)
    await session.commit()
    return await L.summary(session, league, today())


@router.get("")
async def list_leagues(club_id: int | None = None, status: str | None = Query(None, pattern="^(active|upcoming|finished)$"),
                       session: AsyncSession = Depends(get_session)):
    q = select(League, Club).join(Club, Club.id == League.club_id).order_by(League.starts_on.desc())
    if club_id:
        q = q.where(League.club_id == club_id)
    out = []
    for league, club in (await session.execute(q.limit(200))).all():
        s = await L.summary(session, league, today())
        if status and s["status"] != status:
            continue
        out.append({**s, "club": club.name, "club_slug": club.slug})
    return out


@router.get("/{lid}")
async def get_league(lid: int, session: AsyncSession = Depends(get_session)):
    league = await _get(session, lid)
    club = await session.get(Club, league.club_id)
    table = await (L.edh_table(session, league) if league.kind == LeagueKind.edh else L.berserk_table(session, league))
    events = (await session.execute(select(Tournament).where(Tournament.league_id == lid)
                                    .order_by(Tournament.starts_at))).scalars().all()
    return {**await L.summary(session, league, today()), "club": club.name, "club_slug": club.slug,
            "standings": table,
            "tournaments": [{"id": t.id, "name": t.name, "status": t.status, "starts_at": t.starts_at,
                             "format": t.format} for t in events]}


@router.post("/{lid}/close", status_code=204)
async def close_league(lid: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    """Досрочно завершить сезон: новые ивенты к нему не привязываются, таблица фиксируется."""
    league = await _get(session, lid)
    if not await is_club_organizer(session, league.club_id, user):
        raise HTTPException(403, "Нужны права организатора клуба")
    league.closed = True
    await session.commit()
