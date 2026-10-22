"""Состояние системы для администратора: бот, очередь Telegram, резервные копии."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from .. import system
from ..db import get_session
from ..deps import require_admin
from ..models import User

router = APIRouter(prefix="/admin", tags=["system"])


@router.get("/system")
async def system_health(_: User = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    return await system.health(session)
