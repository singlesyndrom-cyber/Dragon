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
