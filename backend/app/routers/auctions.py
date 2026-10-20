"""Аукционы на сайте: просмотр лотов (гости), сделки, оценки и жалобы (игроки), модерация (админ).
Создание лотов и ставки идут через Telegram-бота (по ТЗ)."""
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import auction_service as svc
from ..auction import AuctionError
from ..config import settings
from ..db import get_session
from ..deps import current_user, require_admin
from ..models import Bid, Complaint, Deal, GlobalRole, Lot, LotStatus, User

router = APIRouter(tags=["auctions"])


class ConfirmIn(BaseModel):
    ok: bool


class RateIn(BaseModel):
    score: int = Field(ge=1, le=5)
    comment: str = Field(default="", max_length=500)


class ComplaintIn(BaseModel):
    against_user_id: int
    deal_id: int | None = None
    text: str = Field(min_length=5, max_length=2000)


class BanIn(BaseModel):
    banned: bool


def _err(e: AuctionError) -> HTTPException:
    return HTTPException(400, str(e))


def _public(view: dict) -> dict:
    view = {k: v for k, v in view.items() if k not in ("chat_id", "message_id", "has_photo")}
    return view


# ---------- публичное ----------
@router.get("/auctions/lots")
async def list_lots(status: LotStatus = LotStatus.active, seller_id: int | None = None,
                    limit: int = Query(30, ge=1, le=100), offset: int = Query(0, ge=0),
                    session: AsyncSession = Depends(get_session)):
    q = select(Lot.id).where(Lot.status == status)
    if seller_id:
        q = q.where(Lot.seller_id == seller_id)
    order = Lot.ends_at.asc() if status == LotStatus.active else Lot.finished_at.desc()
    ids = (await session.execute(q.order_by(order).limit(limit).offset(offset))).scalars().all()
    out = []
    for i in ids:
        v = await svc.lot_view(session, i)
        out.append({**_public(v), "photo_url": f"/auctions/lots/{i}/photo" if v["has_photo"] else None})
    return out


@router.get("/auctions/lots/{lot_id}")
async def get_lot(lot_id: int, session: AsyncSession = Depends(get_session)):
    v = await svc.lot_view(session, lot_id)
    if not v:
        raise HTTPException(404, "Лот не найден")
    rows = (await session.execute(select(Bid, User.nickname).join(User, User.id == Bid.user_id)
                                  .where(Bid.lot_id == lot_id).order_by(Bid.id.desc()).limit(50))).all()
    return {**_public(v), "photo_url": f"/auctions/lots/{lot_id}/photo" if v["has_photo"] else None,
            "bids_history": [{"nickname": n, "amount": b.amount, "at": b.created_at, "extended": b.extended}
                             for b, n in rows]}


@router.get("/auctions/lots/{lot_id}/photo")
async def lot_photo(lot_id: int, session: AsyncSession = Depends(get_session)):
    """Фото хранится в Telegram (file_id); сайт получает его через этот прокси, токен бота наружу не уходит."""
    lot = await session.get(Lot, lot_id)
    if not lot or not lot.photo_file_id:
        raise HTTPException(404, "Фото нет")
    if not settings.telegram_bot_token:
        raise HTTPException(503, "Бот не настроен")
    base = f"https://api.telegram.org/bot{settings.telegram_bot_token}"
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            meta = (await c.get(f"{base}/getFile", params={"file_id": lot.photo_file_id})).json()
            path = meta["result"]["file_path"]
            img = await c.get(f"https://api.telegram.org/file/bot{settings.telegram_bot_token}/{path}")
            img.raise_for_status()
    except (httpx.HTTPError, KeyError, ValueError):
        raise HTTPException(502, "Не удалось получить фото из Telegram")
    return Response(img.content, media_type=img.headers.get("content-type", "image/jpeg"),
                    headers={"Cache-Control": "public, max-age=86400"})


@router.get("/auctions/users/{user_id}/rating")
async def rating(user_id: int, session: AsyncSession = Depends(get_session)):
    if not await session.get(User, user_id):
        raise HTTPException(404, "Пользователь не найден")
    return await svc.user_rating(session, user_id)


# ---------- игрок ----------
@router.post("/auctions/lots/{lot_id}/cancel", status_code=204)
async def cancel(lot_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    try:
        await svc.cancel_lot(session, lot_id, user, is_admin=user.role == GlobalRole.admin)
    except AuctionError as e:
        raise _err(e)


@router.get("/auctions/deals/mine")
async def my_deals(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(Deal, Lot.title).join(Lot, Lot.id == Deal.lot_id)
                                  .where((Deal.seller_id == user.id) | (Deal.buyer_id == user.id))
                                  .order_by(Deal.id.desc()).limit(100))).all()
    return [{"id": d.id, "lot_id": d.lot_id, "title": t, "price": d.price, "status": d.status,
             "role": "seller" if d.seller_id == user.id else "buyer",
             "counterparty_id": d.buyer_id if d.seller_id == user.id else d.seller_id,
             "my_answer": d.seller_ok if d.seller_id == user.id else d.buyer_ok} for d, t in rows]


@router.post("/auctions/deals/{deal_id}/confirm")
async def confirm(deal_id: int, data: ConfirmIn, user: User = Depends(current_user),
                  session: AsyncSession = Depends(get_session)):
    try:
        deal = await svc.confirm_deal(session, deal_id, user, data.ok)
    except AuctionError as e:
        raise _err(e)
    return {"status": deal.status}


@router.post("/auctions/deals/{deal_id}/rate", status_code=201)
async def rate(deal_id: int, data: RateIn, user: User = Depends(current_user),
               session: AsyncSession = Depends(get_session)):
    try:
        await svc.rate_deal(session, deal_id, user, data.score, data.comment)
    except AuctionError as e:
        raise _err(e)
    return {"ok": True}


@router.post("/auctions/complaints", status_code=201)
async def complain(data: ComplaintIn, user: User = Depends(current_user),
                   session: AsyncSession = Depends(get_session)):
    if data.against_user_id == user.id or not await session.get(User, data.against_user_id):
        raise HTTPException(400, "Некорректный пользователь")
    if data.deal_id is not None:
        deal = await session.get(Deal, data.deal_id)
        if not deal or {user.id, data.against_user_id} != {deal.seller_id, deal.buyer_id}:
            raise HTTPException(400, "Жалоба по сделке возможна только между её участниками")
    c = Complaint(from_user_id=user.id, against_user_id=data.against_user_id, deal_id=data.deal_id,
                  text=data.text.strip())
    session.add(c)
    await session.commit()
    return {"id": c.id}


# ---------- админ ----------
async def _nicks(session: AsyncSession, ids: list[int]) -> dict[int, str]:
    if not ids:
        return {}
    return dict((await session.execute(select(User.id, User.nickname).where(User.id.in_(set(ids))))).all())


@router.get("/admin/complaints")
async def complaints(status: str = Query("open", pattern="^(open|resolved)$"), admin: User = Depends(require_admin),
                     session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(Complaint).where(Complaint.status == status)
                                  .order_by(Complaint.id.desc()).limit(200))).scalars().all()
    nick = await _nicks(session, [c.from_user_id for c in rows] + [c.against_user_id for c in rows])
    return [{"id": c.id, "from_user_id": c.from_user_id, "from_nick": nick.get(c.from_user_id),
             "against_user_id": c.against_user_id, "against_nick": nick.get(c.against_user_id),
             "deal_id": c.deal_id, "text": c.text, "created_at": c.created_at} for c in rows]


@router.post("/admin/complaints/{complaint_id}/resolve", status_code=204)
async def resolve(complaint_id: int, admin: User = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    c = await session.get(Complaint, complaint_id)
    if not c:
        raise HTTPException(404, "Жалоба не найдена")
    c.status = "resolved"
    await session.commit()


@router.get("/admin/deals/disputed")
async def disputed(admin: User = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(Deal).where(Deal.status == "disputed").order_by(Deal.id.desc()))).scalars().all()
    nick = await _nicks(session, [d.seller_id for d in rows] + [d.buyer_id for d in rows])
    return [{"id": d.id, "lot_id": d.lot_id, "seller_id": d.seller_id, "seller_nick": nick.get(d.seller_id),
             "buyer_id": d.buyer_id, "buyer_nick": nick.get(d.buyer_id), "price": d.price,
             "seller_ok": d.seller_ok, "buyer_ok": d.buyer_ok} for d in rows]


@router.post("/admin/users/{user_id}/ban", status_code=204)
async def ban(user_id: int, data: BanIn, admin: User = Depends(require_admin),
              session: AsyncSession = Depends(get_session)):
    u = await session.get(User, user_id)
    if not u:
        raise HTTPException(404, "Пользователь не найден")
    if u.id == admin.id:
        raise HTTPException(400, "Нельзя заблокировать себя")
    u.is_banned = data.banned
    await session.commit()
