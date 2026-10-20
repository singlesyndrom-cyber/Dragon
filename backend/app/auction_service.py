"""Операции аукциона над БД. Общие для бота и API сайта.

Каждая изменяющая функция сама делает commit. Ошибки для пользователя - AuctionError.
Конкурентные ставки сериализуются блокировкой строки лота (SELECT ... FOR UPDATE).
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from . import notify
from .auction import (MAX_ACTIVE_LOTS, AuctionError, check_bid, check_lot, deal_status, extend_end,
                      min_next_bid)
from .auction_texts import (deal_buttons, deal_closed_text, outbid_text, post_url, rate_buttons, rate_text,
                            sold_text, unsold_text, user_link, won_text)
from .models import (AuthAccount, Bid, Deal, DealRating, Lot, LotStatus, Provider, User)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------- пользователи Telegram ----------
async def get_or_create_tg_user(session: AsyncSession, tg_id: int, username: str | None,
                                display_name: str | None) -> User:
    """Пользователь бота = аккаунт платформы с привязанным Telegram (тот же, что при входе на сайт)."""
    acc = (await session.execute(select(AuthAccount).where(
        AuthAccount.provider == Provider.telegram, AuthAccount.external_id == str(tg_id)))).scalar_one_or_none()
    if acc:
        user = await session.get(User, acc.user_id)
        if user.tg_username != username:
            user.tg_username = username
            await session.commit()
        return user
    user = User(nickname=(username or display_name or f"tg{tg_id}")[:64], tg_username=username)
    session.add(user)
    await session.flush()
    session.add(AuthAccount(user_id=user.id, provider=Provider.telegram, external_id=str(tg_id)))
    await session.commit()
    return user


async def tg_chat_id(session: AsyncSession, user_id: int) -> str | None:
    return (await session.execute(select(AuthAccount.external_id).where(
        AuthAccount.user_id == user_id, AuthAccount.provider == Provider.telegram))).scalar_one_or_none()


async def contact(session: AsyncSession, user_id: int) -> str:
    user = await session.get(User, user_id)
    return user_link(user.nickname, await tg_chat_id(session, user_id), user.tg_username)


# ---------- рейтинг ----------
async def user_rating(session: AsyncSession, user_id: int) -> dict:
    rows = (await session.execute(select(DealRating.role, func.avg(DealRating.score), func.count())
                                  .where(DealRating.to_user_id == user_id).group_by(DealRating.role))).all()
    by = {role: (round(float(avg), 2), n) for role, avg, n in rows}
    done = (await session.execute(select(func.count()).select_from(Deal).where(
        Deal.status == "completed", (Deal.seller_id == user_id) | (Deal.buyer_id == user_id)))).scalar_one()
    s_avg, s_n = by.get("seller", (None, 0))
    b_avg, b_n = by.get("buyer", (None, 0))
    return {"user_id": user_id, "seller_avg": s_avg, "seller_count": s_n,
            "buyer_avg": b_avg, "buyer_count": b_n, "deals_completed": done}


# ---------- лоты ----------
async def create_lot(session: AsyncSession, seller: User, title: str, condition: str, start_price: int | None,
                     hours: int, photo_file_id: str | None, now: datetime | None = None) -> Lot:
    now = now or utcnow()
    if seller.is_banned:
        raise AuctionError("Аккаунт заблокирован администратором")
    title = check_lot(title, condition, start_price, hours)
    active = (await session.execute(select(func.count()).select_from(Lot).where(
        Lot.seller_id == seller.id, Lot.status == LotStatus.active))).scalar_one()
    if active >= MAX_ACTIVE_LOTS:
        raise AuctionError(f"Одновременно можно держать не больше {MAX_ACTIVE_LOTS} активных лотов")
    lot = Lot(seller_id=seller.id, title=title, condition=condition, start_price=start_price,
              photo_file_id=photo_file_id, ends_at=now + timedelta(hours=hours))
    session.add(lot)
    await session.commit()
    return lot


async def attach_post(session: AsyncSession, lot_id: int, chat_id: str, message_id: int) -> None:
    lot = await session.get(Lot, lot_id)
    lot.chat_id, lot.message_id = str(chat_id), message_id
    await session.commit()


async def cancel_lot(session: AsyncSession, lot_id: int, user: User, is_admin: bool = False) -> Lot:
    lot = (await session.execute(select(Lot).where(Lot.id == lot_id).with_for_update())).scalar_one_or_none()
    if not lot or (lot.seller_id != user.id and not is_admin):
        raise AuctionError("Лот не найден")
    if lot.status != LotStatus.active:
        raise AuctionError("Лот уже не активен")
    if lot.bids_count and not is_admin:
        raise AuctionError("На лот уже есть ставки: снять его может только администратор")
    lot.status, lot.finished_at = LotStatus.cancelled, utcnow()
    await session.commit()
    return lot


@dataclass
class BidOutcome:
    lot: Lot
    previous_leader_id: int | None
    extended: bool


async def place_bid(session: AsyncSession, lot_id: int, user: User, amount: int | None,
                    now: datetime | None = None) -> BidOutcome:
    now = now or utcnow()
    if user.is_banned:
        raise AuctionError("Аккаунт заблокирован администратором")
    lot = (await session.execute(select(Lot).where(Lot.id == lot_id).with_for_update())).scalar_one_or_none()
    if not lot:
        raise AuctionError("Лот не найден")
    check_bid(amount=amount, start_price=lot.start_price, current_price=lot.current_price, seller_id=lot.seller_id,
              leader_id=lot.leader_id, bidder_id=user.id, ends_at=lot.ends_at, now=now,
              active=lot.status == LotStatus.active)
    prev = lot.leader_id
    new_end = extend_end(lot.ends_at, now)
    extended = new_end != lot.ends_at
    lot.current_price, lot.leader_id, lot.ends_at = amount, user.id, new_end
    lot.bids_count += 1
    session.add(Bid(lot_id=lot.id, user_id=user.id, amount=amount, extended=extended))
    if prev and prev != user.id:
        await notify.enqueue(session, "auction_outbid", await tg_chat_id(session, prev),
                             outbid_text(lot.title, amount, post_url(lot.chat_id, lot.message_id)))
    await session.commit()
    return BidOutcome(lot, prev, extended)


async def finish_due(session: AsyncSession, now: datetime | None = None, limit: int = 50) -> list[int]:
    """Закрывает истёкшие лоты: продан (создаётся сделка, стороны получают контакты) или без ставок."""
    now = now or utcnow()
    lots = (await session.execute(select(Lot).where(Lot.status == LotStatus.active, Lot.ends_at <= now)
                                  .order_by(Lot.ends_at).limit(limit)
                                  .with_for_update(skip_locked=True))).scalars().all()
    for lot in lots:
        lot.finished_at = now
        if lot.leader_id is None:
            lot.status = LotStatus.unsold
            await notify.enqueue(session, "auction_unsold", await tg_chat_id(session, lot.seller_id),
                                 unsold_text(lot.title))
            continue
        lot.status = LotStatus.sold
        deal = Deal(lot_id=lot.id, seller_id=lot.seller_id, buyer_id=lot.leader_id, price=lot.current_price)
        session.add(deal)
        await session.flush()
        await notify.enqueue(session, "auction_won", await tg_chat_id(session, deal.buyer_id),
                             won_text(lot.title, deal.price, await contact(session, deal.seller_id)),
                             buttons=deal_buttons(deal.id), dedup_key=f"deal-won:{deal.id}")
        await notify.enqueue(session, "auction_sold", await tg_chat_id(session, deal.seller_id),
                             sold_text(lot.title, deal.price, await contact(session, deal.buyer_id)),
                             buttons=deal_buttons(deal.id), dedup_key=f"deal-sold:{deal.id}")
    await session.commit()
    return [lot.id for lot in lots]


# ---------- сделки и оценки ----------
async def _deal_for(session: AsyncSession, deal_id: int, user: User, lock: bool = False) -> Deal:
    q = select(Deal).where(Deal.id == deal_id)
    deal = (await session.execute(q.with_for_update() if lock else q)).scalar_one_or_none()
    if not deal or user.id not in (deal.seller_id, deal.buyer_id):
        raise AuctionError("Сделка не найдена")
    return deal


async def confirm_deal(session: AsyncSession, deal_id: int, user: User, ok: bool) -> Deal:
    deal = await _deal_for(session, deal_id, user, lock=True)
    field = "seller_ok" if user.id == deal.seller_id else "buyer_ok"
    if getattr(deal, field) is not None:
        raise AuctionError("Вы уже отметили результат этой сделки")
    setattr(deal, field, ok)
    deal.status = deal_status(deal.seller_ok, deal.buyer_ok)
    lot = await session.get(Lot, deal.lot_id)
    if deal.status == "completed":
        for uid, other_role in ((deal.buyer_id, "seller"), (deal.seller_id, "buyer")):
            await notify.enqueue(session, "deal_rate", await tg_chat_id(session, uid), rate_text(lot.title, other_role),
                                 buttons=rate_buttons(deal.id), dedup_key=f"deal-rate:{deal.id}:{uid}")
    elif deal.status in ("failed", "disputed"):
        for uid in (deal.seller_id, deal.buyer_id):
            await notify.enqueue(session, "deal_closed", await tg_chat_id(session, uid),
                                 deal_closed_text(lot.title, deal.status), dedup_key=f"deal-closed:{deal.id}:{uid}")
    await session.commit()
    return deal


async def rate_deal(session: AsyncSession, deal_id: int, user: User, score: int, comment: str = "") -> DealRating:
    deal = await _deal_for(session, deal_id, user)
    if deal.status != "completed":
        raise AuctionError("Оценить можно только сделку, подтверждённую обеими сторонами")
    if not 1 <= score <= 5:
        raise AuctionError("Оценка от 1 до 5")
    exists = (await session.execute(select(DealRating).where(
        DealRating.deal_id == deal.id, DealRating.from_user_id == user.id))).scalar_one_or_none()
    if exists:
        raise AuctionError("Вы уже оценили эту сделку")
    to_seller = user.id == deal.buyer_id
    r = DealRating(deal_id=deal.id, from_user_id=user.id, to_user_id=deal.seller_id if to_seller else deal.buyer_id,
                   role="seller" if to_seller else "buyer", score=score, comment=(comment or "")[:500])
    session.add(r)
    await session.commit()
    return r


# ---------- представление лота (бот и сайт) ----------
async def lot_view(session: AsyncSession, lot_id: int) -> dict | None:
    lot = await session.get(Lot, lot_id)
    if not lot:
        return None
    found = (await session.execute(select(User.id, User.nickname, User.player_no).where(
        User.id.in_({lot.seller_id, lot.leader_id} - {None})))).all()
    names = {uid: nick for uid, nick, _ in found}
    numbers = {uid: no for uid, _, no in found}
    rating = await user_rating(session, lot.seller_id)
    return {"id": lot.id, "title": lot.title, "condition": lot.condition, "seller_id": lot.seller_id,
            "seller": names.get(lot.seller_id), "seller_no": numbers.get(lot.seller_id),
            "seller_avg": rating["seller_avg"],
            "seller_count": rating["seller_count"], "start_price": lot.start_price,
            "current_price": lot.current_price, "leader_id": lot.leader_id, "leader": names.get(lot.leader_id),
            "leader_no": numbers.get(lot.leader_id),
            "bids": lot.bids_count, "ends_at": lot.ends_at, "status": lot.status.value,
            "next_bid": min_next_bid(lot.start_price, lot.current_price), "chat_id": lot.chat_id,
            "message_id": lot.message_id, "has_photo": bool(lot.photo_file_id),
            "post_url": post_url(lot.chat_id, lot.message_id)}
