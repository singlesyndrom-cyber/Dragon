"""VK клуба: токены (расшифровка, обновление токена стены VK ID), код привязки беседы."""
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from . import vk
from .models import ClubVk
from .secretbox import decrypt, encrypt

PEER_CHAT_BASE = 2_000_000_000   # peer_id беседы = 2000000000 + номер беседы


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
