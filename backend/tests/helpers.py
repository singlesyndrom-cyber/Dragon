"""Общее для интеграционных тестов."""
from sqlalchemy import update

from app.db import SessionLocal
from app.models import User


async def make_creator(c, headers) -> None:
    """Статус «Создатель Клуба» напрямую в базе: в жизни его выдаёт модератор по заявке."""
    me = (await c.get("/auth/me", headers=headers)).json()
    async with SessionLocal() as s:
        await s.execute(update(User).where(User.id == me["id"]).values(is_club_creator=True))
        await s.commit()
