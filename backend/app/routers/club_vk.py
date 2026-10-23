"""Настройки VK клуба (для организаторов): сообщество, беседа, личные сообщения, стена."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from .. import notify, vk, vkclub
from ..db import get_session
from ..deps import current_user, is_club_organizer
from ..models import Club, ClubVk, User
from ..secretbox import encrypt
from .auth import VkIn, vk_redirect_uri

router = APIRouter(prefix="/clubs/{club_id}/vk", tags=["vk"])


async def _club(session: AsyncSession, club_id: int, user: User) -> Club:
    club = await session.get(Club, club_id)
    if not club:
        raise HTTPException(404, "Клуб не найден")
    if not await is_club_organizer(session, club_id, user):
        raise HTTPException(403, "Нужны права организатора клуба")
    return club


async def _cfg(session: AsyncSession, club_id: int, create: bool = False) -> ClubVk | None:
    cfg = await session.get(ClubVk, club_id)
    if not cfg and create:
        cfg = ClubVk(club_id=club_id)
        session.add(cfg)
    return cfg


def _view(cfg: ClubVk | None) -> dict:
    """Состояние для страницы настроек. Токены наружу не отдаются - только факт, что они есть."""
    c = cfg or ClubVk()
    return {"group_id": c.group_id, "group_name": c.group_name, "has_group_token": bool(c.group_token),
            "peer_id": c.peer_id, "bind_code": c.bind_code,
            "chat_enabled": c.chat_enabled is not False, "dm_enabled": c.dm_enabled is not False,
            "wall_enabled": bool(c.wall_enabled), "wall_connected": bool(c.wall_token),
            "wall_mode": "vkid" if c.wall_refresh else ("token" if c.wall_token else None),
            "wall_user_name": c.wall_user_name, "last_error": c.last_error,
            "vkid_enabled": vk.vkid_enabled(), "redirect_uri": vk_redirect_uri()}


@router.get("")
async def get_vk(club_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    await _club(session, club_id, user)
    return _view(await _cfg(session, club_id))


class VkSettings(BaseModel):
    group_token: str | None = Field(default=None, max_length=512)   # токен сообщества с правом «сообщения»
    chat_enabled: bool | None = None
    dm_enabled: bool | None = None
    wall_enabled: bool | None = None


@router.put("")
async def put_vk(club_id: int, data: VkSettings, user: User = Depends(current_user),
                 session: AsyncSession = Depends(get_session)):
    await _club(session, club_id, user)
    cfg = await _cfg(session, club_id, create=True)
    warnings = []
    if data.group_token is not None:
        token = data.group_token.strip()
        try:
            g = await vk.group_info(token)
        except vk.VkError as e:
            raise HTTPException(400, f"VK не принял токен сообщества: {e.message}")
        if cfg.group_id and cfg.group_id != g["id"]:            # другое сообщество: беседа и стена - от старого
            cfg.peer_id, cfg.wall_token, cfg.wall_refresh, cfg.wall_enabled = None, None, None, False
        cfg.group_id, cfg.group_name, cfg.group_token, cfg.last_error = g["id"], g["name"], encrypt(token), None
        try:
            await vk.enable_longpoll(token, g["id"])
        except vk.VkError as e:
            warnings.append("Не удалось включить Long Poll API автоматически — кнопки «Записаться» не будут "
                            f"работать, пока не включите его в настройках сообщества ({e.message})")
    for field in ("chat_enabled", "dm_enabled", "wall_enabled"):
        v = getattr(data, field)
        if v is not None:
            setattr(cfg, field, v)
    if cfg.wall_enabled and not cfg.wall_token:
        cfg.wall_enabled = False
        warnings.append("Сначала подключите стену: публиковать посты может только администратор сообщества")
    await session.commit()
    return {**_view(cfg), "warnings": warnings}


@router.delete("", status_code=204)
async def delete_vk(club_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    await _club(session, club_id, user)
    cfg = await _cfg(session, club_id)
    if cfg:
        await session.delete(cfg)
        await session.commit()


@router.post("/bind")
async def bind_chat(club_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    """Код привязки беседы: отправьте его в беседу, куда добавлено сообщество, - бот запомнит беседу."""
    await _club(session, club_id, user)
    cfg = await _cfg(session, club_id)
    if not cfg or not cfg.group_token:
        raise HTTPException(400, "Сначала подключите сообщество VK")
    cfg.bind_code = vkclub.new_bind_code()
    await session.commit()
    return _view(cfg)


class PeerIn(BaseModel):
    peer_id: int | None = Field(default=None, ge=1)


@router.put("/peer")
async def set_peer(club_id: int, data: PeerIn, user: User = Depends(current_user),
                   session: AsyncSession = Depends(get_session)):
    """Беседа вручную: номер беседы (1, 2…) или peer_id (2000000001…). None - отключить беседу."""
    await _club(session, club_id, user)
    cfg = await _cfg(session, club_id)
    if not cfg or not cfg.group_token:
        raise HTTPException(400, "Сначала подключите сообщество VK")
    p = data.peer_id
    cfg.peer_id = None if p is None else (p if p >= vkclub.PEER_CHAT_BASE else vkclub.PEER_CHAT_BASE + p)
    cfg.bind_code = None
    await session.commit()
    return _view(cfg)


class TestIn(BaseModel):
    target: str = Field(pattern="^(chat|wall)$")


@router.post("/test", status_code=202)
async def test_vk(club_id: int, data: TestIn, user: User = Depends(current_user),
                  session: AsyncSession = Depends(get_session)):
    club = await _club(session, club_id, user)
    cfg = await _cfg(session, club_id)
    if not cfg or not cfg.group_token:
        raise HTTPException(400, "Сначала подключите сообщество VK")
    text = f"✅ Проверка связи: клуб «{club.name}» подключён к VK. Сюда будут приходить анонсы и итоги турниров."
    if data.target == "chat":
        if not cfg.peer_id:
            raise HTTPException(400, "Беседа ещё не привязана")
        await notify.enqueue(session, "test", f"{club_id}:{cfg.peer_id}", text, channel="vk")
    else:
        if not cfg.wall_token:
            raise HTTPException(400, "Стена не подключена")
        await notify.enqueue(session, "test", str(club_id), text, channel="vkwall")
    cfg.last_error = None
    await session.commit()


# ---------- стена ----------
@router.post("/wall/vkid")
async def wall_vkid(club_id: int, data: VkIn, user: User = Depends(current_user),
                    session: AsyncSession = Depends(get_session)):
    """Администратор сообщества входит через VK ID с правом «стена» - сохраняем его токены (с обновлением)."""
    await _club(session, club_id, user)
    cfg = await _cfg(session, club_id)
    if not cfg or not cfg.group_id:
        raise HTTPException(400, "Сначала подключите сообщество VK")
    try:
        got = await vk.exchange_code(data.code, data.code_verifier, data.device_id, vk_redirect_uri(), data.state)
    except vk.VkError as e:
        raise HTTPException(400, f"VK ID не выдал доступ: {e.message}")
    if "wall" not in str(got.get("scope", "wall")).split():
        raise HTTPException(400, "VK ID не выдал право «стена». Проверьте доступы приложения VK ID или вставьте "
                                 "токен администратора вручную")
    vkclub.save_wall_tokens(cfg, got)
    cfg.wall_device_id = data.device_id
    try:
        info = await vk.user_info(got["access_token"])
        cfg.wall_user_name = f"{info.get('first_name', '')} {info.get('last_name', '')}".strip() or None
    except vk.VkError:
        cfg.wall_user_name = None
    cfg.wall_enabled, cfg.last_error = True, None
    await session.commit()
    return _view(cfg)


class WallTokenIn(BaseModel):
    token: str = Field(min_length=20, max_length=512)


@router.put("/wall/token")
async def wall_token_manual(club_id: int, data: WallTokenIn, user: User = Depends(current_user),
                            session: AsyncSession = Depends(get_session)):
    """Токен администратора сообщества с правами wall (и offline), полученный вручную."""
    await _club(session, club_id, user)
    cfg = await _cfg(session, club_id)
    if not cfg or not cfg.group_id:
        raise HTTPException(400, "Сначала подключите сообщество VK")
    token = data.token.strip()
    try:
        names = await vk.call("users.get", token)
    except vk.VkError as e:
        raise HTTPException(400, f"VK не принял токен: {e.message}")
    if not names:
        raise HTTPException(400, "Это токен сообщества, а нужен токен администратора (пользователя)")
    cfg.wall_token, cfg.wall_refresh, cfg.wall_device_id, cfg.wall_expires_at = encrypt(token), None, None, None
    cfg.wall_user_name = f"{names[0].get('first_name', '')} {names[0].get('last_name', '')}".strip() or None
    cfg.wall_enabled, cfg.last_error = True, None
    await session.commit()
    return _view(cfg)


@router.delete("/wall")
async def wall_disconnect(club_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    await _club(session, club_id, user)
    cfg = await _cfg(session, club_id)
    if cfg:
        cfg.wall_token = cfg.wall_refresh = cfg.wall_device_id = cfg.wall_user_name = None
        cfg.wall_expires_at, cfg.wall_enabled = None, False
        await session.commit()
    return _view(cfg)
