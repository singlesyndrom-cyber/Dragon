"""Настройки VK клуба (для организаторов): сообщество, беседа, личные сообщения, стена."""
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import notify, vk, vkclub
from ..db import get_session
from ..deps import current_user, is_club_organizer
from ..models import Club, ClubVk, ClubVkChat, User
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


async def _view(session: AsyncSession, cfg: ClubVk | None, club_id: int) -> dict:
    """Состояние для страницы настроек. Токены наружу не отдаются - только факт, что они есть."""
    c = cfg or ClubVk()
    chats = (await session.execute(select(ClubVkChat).where(ClubVkChat.club_id == club_id)
                                   .order_by(ClubVkChat.id))).scalars().all()
    return {"group_id": c.group_id, "group_name": c.group_name, "has_group_token": bool(c.group_token),
            "chats": [{"id": x.id, "game": x.game, "peer_id": x.peer_id, "title": x.title} for x in chats],
            "games": vkclub.GAMES, "bind_code": c.bind_code, "bind_game": c.bind_game,
            "chat_enabled": c.chat_enabled is not False, "dm_enabled": c.dm_enabled is not False,
            "wall_enabled": bool(c.wall_enabled), "wall_connected": bool(c.wall_token),
            "wall_mode": "vkid" if c.wall_refresh else ("token" if c.wall_token else None),
            "wall_user_name": c.wall_user_name, "last_error": c.last_error,
            "vkid_enabled": vk.vkid_enabled(), "redirect_uri": vk_redirect_uri()}


@router.get("")
async def get_vk(club_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    await _club(session, club_id, user)
    return await _view(session, await _cfg(session, club_id), club_id)


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
        if cfg.group_id and cfg.group_id != g["id"]:            # другое сообщество: беседы и стена - от старого
            cfg.peer_id, cfg.wall_token, cfg.wall_refresh, cfg.wall_enabled = None, None, None, False
            await session.execute(delete(ClubVkChat).where(ClubVkChat.club_id == club_id))
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
    return {**await _view(session, cfg, club_id), "warnings": warnings}


@router.delete("", status_code=204)
async def delete_vk(club_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    await _club(session, club_id, user)
    cfg = await _cfg(session, club_id)
    await session.execute(delete(ClubVkChat).where(ClubVkChat.club_id == club_id))
    if cfg:
        await session.delete(cfg)
    await session.commit()


GAME_PATTERN = "^(" + "|".join(vkclub.GAMES) + ")$"


class BindIn(BaseModel):
    game: str = Field(default="all", pattern=GAME_PATTERN)


@router.post("/bind")
async def bind_chat(club_id: int, data: BindIn | None = None, user: User = Depends(current_user),
                    session: AsyncSession = Depends(get_session)):
    """Код привязки беседы для игры: отправьте его в беседу, где состоит сообщество, - бот запомнит беседу."""
    await _club(session, club_id, user)
    cfg = await _cfg(session, club_id)
    if not cfg or not cfg.group_token:
        raise HTTPException(400, "Сначала подключите сообщество VK")
    cfg.bind_code, cfg.bind_game = vkclub.new_bind_code(), (data.game if data else "all")
    await session.commit()
    return await _view(session, cfg, club_id)


@router.delete("/bind")
async def cancel_bind(club_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    await _club(session, club_id, user)
    cfg = await _cfg(session, club_id)
    if cfg:
        cfg.bind_code = cfg.bind_game = None
        await session.commit()
    return await _view(session, cfg, club_id)


class PeerIn(BaseModel):
    peer_id: int = Field(ge=1)
    game: str = Field(default="all", pattern=GAME_PATTERN)


@router.put("/peer")
async def set_peer(club_id: int, data: PeerIn, user: User = Depends(current_user),
                   session: AsyncSession = Depends(get_session)):
    """Беседа вручную: номер беседы у сообщества (1, 2…) или peer_id (2000000001…)."""
    await _club(session, club_id, user)
    cfg = await _cfg(session, club_id)
    if not cfg or not cfg.group_token:
        raise HTTPException(400, "Сначала подключите сообщество VK")
    p = data.peer_id if data.peer_id >= vkclub.PEER_CHAT_BASE else vkclub.PEER_CHAT_BASE + data.peer_id
    chat = (await session.execute(select(ClubVkChat).where(ClubVkChat.club_id == club_id,
                                                           ClubVkChat.game == data.game))).scalar_one_or_none()
    if not chat:
        chat = ClubVkChat(club_id=club_id, game=data.game, peer_id=p)
        session.add(chat)
    chat.peer_id, chat.title = p, await vk.chat_title(vkclub.group_token(cfg), p)
    await session.commit()
    return await _view(session, cfg, club_id)


class ChatPatch(BaseModel):
    game: str = Field(pattern=GAME_PATTERN)


async def _chat(session: AsyncSession, club_id: int, chat_id: int) -> ClubVkChat:
    chat = await session.get(ClubVkChat, chat_id)
    if not chat or chat.club_id != club_id:
        raise HTTPException(404, "Беседа не найдена")
    return chat


@router.patch("/chats/{chat_id}")
async def patch_chat(club_id: int, chat_id: int, data: ChatPatch, user: User = Depends(current_user),
                     session: AsyncSession = Depends(get_session)):
    """Сменить игру беседы. Если у этой игры уже есть беседа - та отвязывается от игры."""
    await _club(session, club_id, user)
    chat = await _chat(session, club_id, chat_id)
    if chat.game != data.game:
        await session.execute(delete(ClubVkChat).where(ClubVkChat.club_id == club_id, ClubVkChat.game == data.game))
        chat.game = data.game
        await session.commit()
    return await _view(session, await _cfg(session, club_id), club_id)


@router.delete("/chats/{chat_id}")
async def delete_chat(club_id: int, chat_id: int, user: User = Depends(current_user),
                      session: AsyncSession = Depends(get_session)):
    await _club(session, club_id, user)
    await session.delete(await _chat(session, club_id, chat_id))
    await session.commit()
    return await _view(session, await _cfg(session, club_id), club_id)


class TestIn(BaseModel):
    target: str = Field(pattern="^(chat|wall)$")
    chat_id: int | None = None


@router.post("/test", status_code=202)
async def test_vk(club_id: int, data: TestIn, user: User = Depends(current_user),
                  session: AsyncSession = Depends(get_session)):
    club = await _club(session, club_id, user)
    cfg = await _cfg(session, club_id)
    if not cfg or not cfg.group_token:
        raise HTTPException(400, "Сначала подключите сообщество VK")
    text = f"✅ Проверка связи: клуб «{club.name}» подключён к VK. Сюда будут приходить анонсы и итоги турниров."
    if data.target == "chat":
        chats = (await session.execute(select(ClubVkChat).where(ClubVkChat.club_id == club_id))).scalars().all()
        chat = next((c for c in chats if c.id == data.chat_id), None) if data.chat_id else (chats[0] if chats else None)
        if not chat:
            raise HTTPException(400, "Беседа ещё не привязана")
        what = ("новости клуба и турниры игр без своей беседы" if chat.game == "all"
                else f"анонсы и итоги турниров «{vkclub.GAMES.get(chat.game, chat.game)}»")
        await notify.enqueue(session, "test", f"{club_id}:{chat.peer_id}",
                             f"✅ Проверка связи: беседа подключена к клубу «{club.name}». Сюда будут приходить {what}.",
                             channel="vk")
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
    scopes = [x for x in re.split(r"[\s,]+", str(got.get("scope", "wall"))) if x]
    if "wall" not in scopes:
        raise HTTPException(400, "VK ID не выдал право «стена» (выданы: " + (", ".join(scopes) or "нет") + "). "
                                 "Включите доступ «Стена» во вкладке «Доступы» приложения VK ID "
                                 "или вставьте токен администратора вручную")
    vkclub.save_wall_tokens(cfg, got)
    cfg.wall_device_id = data.device_id
    try:
        info = await vk.user_info(got["access_token"])
        cfg.wall_user_name = f"{info.get('first_name', '')} {info.get('last_name', '')}".strip() or None
    except vk.VkError:
        cfg.wall_user_name = None
    cfg.wall_enabled, cfg.last_error = True, None
    await session.commit()
    return await _view(session, cfg, club_id)


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
    return await _view(session, cfg, club_id)


@router.delete("/wall")
async def wall_disconnect(club_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    await _club(session, club_id, user)
    cfg = await _cfg(session, club_id)
    if cfg:
        cfg.wall_token = cfg.wall_refresh = cfg.wall_device_id = cfg.wall_user_name = None
        cfg.wall_expires_at, cfg.wall_enabled = None, False
        await session.commit()
    return await _view(session, cfg, club_id)
