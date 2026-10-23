"""VK клуба: токены (расшифровка, обновление токена стены VK ID), код привязки беседы."""
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from . import vk
from .models import ClubVk, ClubVkChat
from .secretbox import decrypt, encrypt

PEER_CHAT_BASE = 2_000_000_000   # peer_id беседы = 2000000000 + номер беседы
GAMES = {"mtg": "Magic: The Gathering", "berserk": "Берсерк", "all": "Все игры и новости"}


async def chat_peers(session: AsyncSession, club_id: int, game: str | None) -> list[int]:
    """Беседы для сообщения: турнир - беседа его игры, иначе общая (all); новости (game=None) - общая,
    а если общей нет - все беседы клуба."""
    rows = (await session.execute(select(ClubVkChat).where(ClubVkChat.club_id == club_id))).scalars().all()
    if game:
        pick = [r for r in rows if r.game == game] or [r for r in rows if r.game == "all"]
    else:
        pick = [r for r in rows if r.game == "all"] or rows
    return list(dict.fromkeys(r.peer_id for r in pick))


MIGRATE_PEER = [
    text("INSERT INTO club_vk_chats (club_id, game, peer_id) SELECT v.club_id, 'all', v.peer_id FROM club_vk v "
         "WHERE v.peer_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM club_vk_chats c WHERE c.club_id = v.club_id)"),
    text("UPDATE club_vk SET peer_id = NULL WHERE peer_id IS NOT NULL"),
]


async def migrate_legacy_peer(conn) -> None:
    """Одна беседа клуба из старых настроек -> беседа «все игры» в club_vk_chats."""
    for stmt in MIGRATE_PEER:
        await conn.execute(stmt)


def new_bind_code() -> str:
    return f"{secrets.randbelow(900000) + 100000}"


def group_token(cfg: ClubVk | None) -> str | None:
    return decrypt(cfg.group_token) if cfg else None


async def wall_token(session: AsyncSession, cfg: ClubVk) -> str | None:
    """Токен для wall.post. Токен VK ID живёт около часа - заранее обновляем по refresh_token (он тоже меняется).
    Токен, вставленный вручную (без refresh), используется как есть."""
    token = decrypt(cfg.wall_token)
    refresh = decrypt(cfg.wall_refresh)
    if not token:
        return None
    soon = datetime.now(timezone.utc) + timedelta(minutes=5)
    if refresh and cfg.wall_device_id and cfg.wall_expires_at and cfg.wall_expires_at <= soon:
        got = await vk.refresh_token(refresh, cfg.wall_device_id)
        save_wall_tokens(cfg, got)
        await session.commit()
        token = got["access_token"]
    return token


def save_wall_tokens(cfg: ClubVk, got: dict) -> None:
    cfg.wall_token = encrypt(got["access_token"])
    if got.get("refresh_token"):
        cfg.wall_refresh = encrypt(got["refresh_token"])
    if got.get("expires_in"):
        cfg.wall_expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(got["expires_in"]))
