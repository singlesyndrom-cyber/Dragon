import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .. import notify
from ..db import get_session
from ..deps import current_user, is_club_organizer, require_admin
from ..models import Club, ClubMember, ClubRole, ClubStats, User

router = APIRouter(prefix="/clubs", tags=["clubs"])


class ClubIn(BaseModel):
    name: str = Field(min_length=2, max_length=128)
    description: str = ""
    city: str = ""
    telegram_chat_id: str | None = None


class ClubUpdate(BaseModel):
    description: str | None = None
    city: str | None = None
    telegram_chat_id: str | None = None


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9а-яё]+", "-", name.lower()).strip("-")


def club_out(c: Club) -> dict:
    s = c.stats
    return {"id": c.id, "name": c.name, "slug": c.slug, "city": c.city, "description": c.description,
            "rating": s.club_rating if s else 0, "tournaments_total": s.tournaments_total if s else 0,
            "avg_participants": s.avg_participants if s else 0,
            "busiest_weekday": s.busiest_weekday if s else None}


@router.get("")
async def list_clubs(session: AsyncSession = Depends(get_session)):
    res = await session.execute(select(Club).options(selectinload(Club.stats)).order_by(Club.name))
    return [club_out(c) for c in res.scalars()]


@router.get("/{slug}")
async def get_club(slug: str, session: AsyncSession = Depends(get_session)):
    res = await session.execute(select(Club).where(Club.slug == slug).options(selectinload(Club.stats)))
    club = res.scalar_one_or_none()
    if not club:
        raise HTTPException(404, "Клуб не найден")
    return club_out(club)


@router.post("", status_code=201)
async def create_club(data: ClubIn, owner: User = Depends(current_user),
                      session: AsyncSession = Depends(get_session)):
    """Создатель становится организатором. Заявки на клубы можно модерировать админом позже."""
    slug = slugify(data.name)
    exists = await session.execute(select(Club).where((Club.name == data.name) | (Club.slug == slug)))
    if exists.scalar_one_or_none():
        raise HTTPException(409, "Клуб с таким названием уже есть")
    club = Club(**data.model_dump(), slug=slug, stats=ClubStats())
    club.members.append(ClubMember(user_id=owner.id, role=ClubRole.organizer))
    session.add(club)
    await session.commit()
    return {"id": club.id, "slug": club.slug}


@router.patch("/{club_id}")
async def update_club(club_id: int, data: ClubUpdate, user: User = Depends(current_user),
                      session: AsyncSession = Depends(get_session)):
    if not await is_club_organizer(session, club_id, user):
        raise HTTPException(403, "Нужны права организатора клуба")
    club = await session.get(Club, club_id)
    if not club:
        raise HTTPException(404, "Клуб не найден")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(club, k, v)
    await session.commit()
    return {"ok": True}


@router.post("/{club_id}/join", status_code=204)
async def join_club(club_id: int, user: User = Depends(current_user),
                    session: AsyncSession = Depends(get_session)):
    if not await session.get(Club, club_id):
        raise HTTPException(404, "Клуб не найден")
    res = await session.execute(select(ClubMember).where(ClubMember.club_id == club_id,
                                                         ClubMember.user_id == user.id))
    if res.scalar_one_or_none():
        raise HTTPException(409, "Вы уже в клубе")
    session.add(ClubMember(club_id=club_id, user_id=user.id))
    await session.commit()


@router.get("/{club_id}/leaderboard")
async def leaderboard(club_id: int, session: AsyncSession = Depends(get_session)):
    """Локальная лига клуба."""
    res = await session.execute(
        select(ClubMember).where(ClubMember.club_id == club_id)
        .options(selectinload(ClubMember.user)).order_by(ClubMember.league_points.desc()).limit(100))
    return [{"user_id": m.user_id, "nickname": m.user.nickname, "league_points": m.league_points,
             "edh_bank": round(m.edh_bank, 1), "events_played": m.events_played} for m in res.scalars()]


@router.post("/{club_id}/members/{user_id}/organizer", status_code=204)
async def make_organizer(club_id: int, user_id: int, admin: User = Depends(require_admin),
                         session: AsyncSession = Depends(get_session)):
    res = await session.execute(select(ClubMember).where(ClubMember.club_id == club_id,
                                                         ClubMember.user_id == user_id))
    m = res.scalar_one_or_none()
    if not m:
        raise HTTPException(404, "Участник не найден")
    m.role = ClubRole.organizer
    await session.commit()


@router.post("/{club_id}/telegram/test", status_code=202)
async def telegram_test(club_id: int, user: User = Depends(current_user),
                        session: AsyncSession = Depends(get_session)):
    """Проверка подключения: бот отправит тестовое сообщение в чат клуба."""
    if not await is_club_organizer(session, club_id, user):
        raise HTTPException(403, "Нужны права организатора клуба")
    club = await session.get(Club, club_id)
    if not club:
        raise HTTPException(404, "Клуб не найден")
    if not club.telegram_chat_id:
        raise HTTPException(400, "Сначала укажите telegram_chat_id в настройках клуба")
    await notify.enqueue(session, "test", club.telegram_chat_id,
                         f"✅ Бот подключён к клубу «{notify.esc(club.name)}». Анонсы и итоги будут приходить сюда.")
    await session.commit()
    return {"queued": True}


@router.get("/{club_id}/membership")
async def membership(club_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    """Роль текущего пользователя в клубе; организатору - ещё и настройки клуба для формы."""
    club = await session.get(Club, club_id)
    if not club:
        raise HTTPException(404, "Клуб не найден")
    m = (await session.execute(select(ClubMember).where(ClubMember.club_id == club_id,
                                                        ClubMember.user_id == user.id))).scalar_one_or_none()
    can_manage = await is_club_organizer(session, club_id, user)
    out = {"member": m is not None, "role": m.role if m else None, "can_manage": can_manage,
           "edh_bank": round(m.edh_bank, 1) if m else None, "league_points": m.league_points if m else None}
    if can_manage:
        out["settings"] = {"description": club.description, "city": club.city,
                           "telegram_chat_id": club.telegram_chat_id}
    return out
