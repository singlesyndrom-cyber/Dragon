from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_session
from .models import ClubMember, ClubRole, GlobalRole, User
from .security import decode_token

bearer = HTTPBearer(auto_error=False)


async def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    session: AsyncSession = Depends(get_session),
) -> User:
    user_id = decode_token(creds.credentials) if creds else None
    user = await session.get(User, user_id) if user_id else None
    if not user or user.is_banned:
        raise HTTPException(401, "Не авторизован")
    return user


async def optional_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    session: AsyncSession = Depends(get_session),
) -> User | None:
    user_id = decode_token(creds.credentials) if creds else None
    user = await session.get(User, user_id) if user_id else None
    return user if user and not user.is_banned else None


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
