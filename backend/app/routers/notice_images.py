"""Пул картинок оповещений клуба (организаторы и судьи) и раздача загруженных картинок."""
from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import noticeimages as ni
from ..db import get_session
from ..deps import current_user
from ..models import Card, Club, NoticeImage, User
from .clubs import is_staff

router = APIRouter(tags=["notice-images"])
PURPOSE_RE = "^(" + "|".join(ni.PURPOSES) + ")$"
GAME_RE = "^(" + "|".join(ni.GAMES) + ")$"
MAX_IMAGES = 300


async def _staff(session: AsyncSession, club_id: int, user: User) -> None:
    if not await session.get(Club, club_id):
        raise HTTPException(404, "Клуб не найден")
    if not await is_staff(session, club_id, user):
        raise HTTPException(403, "Картинками оповещений управляют организаторы и судьи клуба")


def _row(img: NoticeImage) -> dict:
    return {"id": img.id, "purpose": img.purpose, "game": img.game, "url": ni.public_url(img) or "",
            "preview": img.source_url or f"/api/media/notice/{img.id}.jpg", "kind": "card" if img.source_url else "upload",
            "card_name": img.card_name, "credit": img.credit, "enabled": img.enabled, "uses": img.uses,
            "last_used_at": img.last_used_at, "width": img.width, "height": img.height}


async def _check_limit(session: AsyncSession, club_id: int) -> None:
    n = len((await session.execute(select(NoticeImage.id).where(NoticeImage.club_id == club_id))).all())
    if n >= MAX_IMAGES:
        raise HTTPException(400, f"В пуле уже {MAX_IMAGES} картинок — удалите лишние")


@router.get("/clubs/{club_id}/notice-images")
async def list_images(club_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    await _staff(session, club_id, user)
    rows = (await session.execute(select(NoticeImage).where(NoticeImage.club_id == club_id)
                                  .order_by(NoticeImage.id.desc()))).scalars()
    return {"purposes": ni.PURPOSES, "games": ni.GAMES, "items": [_row(i) for i in rows]}


@router.post("/clubs/{club_id}/notice-images", status_code=201)
async def upload_image(club_id: int, file: UploadFile = File(...), purpose: str = Form("announce", pattern=PURPOSE_RE),
                       game: str = Form("any", pattern=GAME_RE), user: User = Depends(current_user),
                       session: AsyncSession = Depends(get_session)):
    await _staff(session, club_id, user)
    await _check_limit(session, club_id)
    raw = await file.read(ni.MAX_UPLOAD + 1)
    if len(raw) > ni.MAX_UPLOAD:
        raise HTTPException(413, "Файл больше 15 МБ")
    try:
        data, w, h = ni.prepare_upload(raw)
    except ValueError as e:
        raise HTTPException(400, str(e))
    img = NoticeImage(club_id=club_id, purpose=purpose, game=game, data=data, width=w, height=h, added_by=user.id)
    session.add(img)
    await session.commit()
    return _row(img)


class CardArtIn(BaseModel):
    card_id: int
    purpose: str = Field(default="announce", pattern=PURPOSE_RE)
    game: str | None = Field(default=None, pattern=GAME_RE)


@router.post("/clubs/{club_id}/notice-images/card", status_code=201)
async def add_card_art(club_id: int, data: CardArtIn, user: User = Depends(current_user),
                       session: AsyncSession = Depends(get_session)):
    """Арт карты из Картотеки (обрезанный арт Scryfall) с подписью художника."""
    await _staff(session, club_id, user)
    await _check_limit(session, club_id)
    card = await session.get(Card, data.card_id)
    url = ni.art_crop(card.image_url) if card else None
    if not card or not url:
        raise HTTPException(400, "У этой карты нет арта в базе")
    dup = (await session.execute(select(NoticeImage.id).where(NoticeImage.club_id == club_id,
                                                              NoticeImage.source_url == url,
                                                              NoticeImage.purpose == data.purpose))).first()
    if dup:
        raise HTTPException(409, "Этот арт уже в пуле")
    artist = (card.extra or {}).get("artist")
    img = NoticeImage(club_id=club_id, purpose=data.purpose, game=data.game or (card.game if card.game in ni.GAMES else "any"),
                      source_url=url, card_id=card.id, card_name=card.name,
                      credit=f"Арт: {artist} · {card.name}" if artist else f"Арт: {card.name}", added_by=user.id)
    session.add(img)
    await session.commit()
    return _row(img)


class ImagePatch(BaseModel):
    purpose: str | None = Field(default=None, pattern=PURPOSE_RE)
    game: str | None = Field(default=None, pattern=GAME_RE)
    enabled: bool | None = None


async def _own(session: AsyncSession, club_id: int, img_id: int) -> NoticeImage:
    img = await session.get(NoticeImage, img_id)
    if not img or img.club_id != club_id:
        raise HTTPException(404, "Картинка не найдена")
    return img


@router.patch("/clubs/{club_id}/notice-images/{img_id}")
async def patch_image(club_id: int, img_id: int, data: ImagePatch, user: User = Depends(current_user),
                      session: AsyncSession = Depends(get_session)):
    await _staff(session, club_id, user)
    img = await _own(session, club_id, img_id)
    for f in ("purpose", "game", "enabled"):
        v = getattr(data, f)
        if v is not None:
            setattr(img, f, v)
    await session.commit()
    return _row(img)


@router.delete("/clubs/{club_id}/notice-images/{img_id}", status_code=204)
async def delete_image(club_id: int, img_id: int, user: User = Depends(current_user),
                       session: AsyncSession = Depends(get_session)):
    await _staff(session, club_id, user)
    await session.delete(await _own(session, club_id, img_id))
    await session.commit()


@router.get("/media/notice/{img_id}.jpg")
async def media(img_id: int, session: AsyncSession = Depends(get_session)):
    """Загруженная картинка оповещения (публично: её забирают Telegram и VK по ссылке)."""
    img = await session.get(NoticeImage, img_id)
    if not img or not img.data:
        raise HTTPException(404, "Картинки нет")
    return Response(img.data, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=604800"})
