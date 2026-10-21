from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_session
from .models import ClubMember, ClubRole, GlobalRole, User
from .security import decode_claims

bearer = HTTPBearer(auto_error=False)


async def _user_from(creds: HTTPAuthorizationCredentials | None, session: AsyncSession) -> User | None:
    claims = decode_claims(creds.credentials) if creds else None
    if not claims:
        return None
    user = await session.get(User, claims[0])
    if not user or user.is_banned or claims[1] != (user.token_version or 0):
        return None
    return user


async def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    session: AsyncSession = Depends(get_session),
) -> User:
    user = await _user_from(creds, session)
    if not user:
        raise HTTPException(401, "Не авторизован")
    return user


async def optional_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    session: AsyncSession = Depends(get_session),
) -> User | None:
    return await _user_from(creds, session)


async def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != GlobalRole.admin:
        raise HTTPException(403, "Нужны права администратора")
    return user


async def require_moderator(user: User = Depends(current_user)) -> User:
    """Рассмотрение заявок «Создатель Клуба»: администратор или модератор."""
    if user.role != GlobalRole.admin and not user.is_moderator:
        raise HTTPException(403, "Нужны права администратора или модератора")
    return user


def can_create_club(user: User) -> bool:
    return user.role == GlobalRole.admin or bool(user.is_club_creator)


async def is_club_organizer(session: AsyncSession, club_id: int, user: User) -> bool:
    if user.role == GlobalRole.admin:
        return True
    res = await session.execute(
        select(ClubMember).where(
            ClubMember.club_id == club_id,
            ClubMember.user_id == user.id,
            ClubMember.role == ClubRole.organizer,
        )
    )
    return res.scalar_one_or_none() is not None


# ---------- судьи клуба ----------
JUDGE_GAMES = {"mtg": "Magic", "edh": "EDH", "berserk": "Берсерк"}


def judge_direction(game: str, fmt) -> str:
    """Направление турнира для прав судьи: EDH, «Берсерк» или Magic (швейцарки MTG)."""
    fmt = getattr(fmt, "value", fmt)
    if fmt == "edh":
        return "edh"
    return "berserk" if game == "berserk" else "mtg"


def parse_judge_games(value: str | None) -> list[str]:
    return [g for g in (value or "").split(",") if g in JUDGE_GAMES]


async def can_judge(session: AsyncSession, club_id: int, game: str, fmt, user: User) -> bool:
    """Организатор судит всё; судья клуба - только свои направления."""
    if await is_club_organizer(session, club_id, user):
        return True
    m = (await session.execute(select(ClubMember.judge_games).where(
        ClubMember.club_id == club_id, ClubMember.user_id == user.id))).scalar_one_or_none()
    return judge_direction(game, fmt) in parse_judge_games(m)
