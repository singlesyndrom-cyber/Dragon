"""Администратор: карточка аккаунта по номеру игрока, удаление аккаунта без истории, объединение двух аккаунтов.

Объединение переносит на основной аккаунт ВСЁ, что ссылается на второй: способы входа (email, Telegram),
турниры, матчи, столы EDH, колоды, лоты и сделки, брони, участие в клубах (очки лиги и ивенты складываются).
Таблицы со ссылкой на пользователя находятся по схеме автоматически, поэтому новая таблица тоже будет учтена.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import Base, get_session
from ..deps import require_admin
from ..models import (AuthAccount, Bid, ClubCreatorRequest, ClubMember, ClubRole, Deal, Deck, EdhSeat, GlobalRole,
                      LeagueMember, Lot, Match, PasswordReset, Provider, Tournament, TournamentPlayer, User)

router = APIRouter(prefix="/admin/users", tags=["admin users"])


async def _by_no(session: AsyncSession, player_no: int) -> User:
    u = (await session.execute(select(User).where(User.player_no == player_no))).scalar_one_or_none()
    if not u:
        raise HTTPException(404, f"Игрока с номером {player_no} нет")
    return u


async def _count(session: AsyncSession, stmt) -> int:
    return (await session.execute(stmt)).scalar_one()


async def _history(session: AsyncSession, uid: int) -> dict:
    """Что у игрока накоплено: по этому решаем, можно ли удалить аккаунт без потерь."""
    return {
        "tournaments": await _count(session, select(func.count()).select_from(TournamentPlayer).where(TournamentPlayer.user_id == uid)),
        "matches": await _count(session, select(func.count()).select_from(Match).where(
            or_(Match.p1_user_id == uid, Match.p2_user_id == uid))),
        "edh_seats": await _count(session, select(func.count()).select_from(EdhSeat).where(EdhSeat.user_id == uid)),
        "deals": await _count(session, select(func.count()).select_from(Deal).where(
            or_(Deal.seller_id == uid, Deal.buyer_id == uid))),
        "lots": await _count(session, select(func.count()).select_from(Lot).where(Lot.seller_id == uid)),
        "bids": await _count(session, select(func.count()).select_from(Bid).where(Bid.user_id == uid)),
        "tournaments_created": await _count(session, select(func.count()).select_from(Tournament).where(Tournament.created_by == uid)),
    }


@router.get("/lookup/{player_no}")
async def lookup(player_no: int, _: User = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    u = await _by_no(session, player_no)
    accounts = (await session.execute(select(AuthAccount.provider, AuthAccount.external_id).where(
        AuthAccount.user_id == u.id))).all()
    clubs = await _count(session, select(func.count()).select_from(ClubMember).where(ClubMember.user_id == u.id))
    decks = await _count(session, select(func.count()).select_from(Deck).where(Deck.user_id == u.id))
    return {"id": u.id, "player_no": u.player_no, "nickname": u.nickname, "role": u.role, "banned": u.is_banned,
            "moderator": u.is_moderator, "club_creator": u.is_club_creator, "created_at": u.created_at,
            "emails": [e for p, e in accounts if p == Provider.email],
            "telegram": any(p == Provider.telegram for p, _ in accounts),
            "clubs": clubs, "decks": decks, **await _history(session, u.id)}


@router.delete("/{player_no}")
async def delete_user(player_no: int, admin: User = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    """Удалить аккаунт, у которого нет игровой истории (турниров, матчей, сделок). Иначе - объединить или заблокировать."""
    u = await _by_no(session, player_no)
    if u.id == admin.id:
        raise HTTPException(400, "Нельзя удалить самого себя")
    if u.role == GlobalRole.admin:
        raise HTTPException(400, "Сначала снимите с аккаунта права администратора")
    h = await _history(session, u.id)
    if any(h.values()):
        parts = [f"{label}: {h[k]}" for k, label in (("tournaments", "турниров"), ("deals", "сделок"), ("lots", "лотов"),
                                                       ("bids", "ставок"), ("tournaments_created", "созданных турниров"))
                 if h[k]]
        raise HTTPException(409, "У игрока есть история (" + ", ".join(parts or ["матчи"]) + "): удаление сотрёт её. "
                                 "Объедините аккаунт с основным или заблокируйте его.")
    nickname, uid = u.nickname, u.id
    session.expunge(u)
    await session.execute(delete(User).where(User.id == uid))   # способы входа, клубы, колоды, брони - каскадом в БД
    await session.commit()
    return {"deleted": player_no, "nickname": nickname}


class MergeIn(BaseModel):
    from_no: int = Field(ge=1)       # этот аккаунт исчезнет
    into_no: int = Field(ge=1)       # на этот переносится всё


@router.post("/merge")
async def merge_users(data: MergeIn, admin: User = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    if data.from_no == data.into_no:
        raise HTTPException(400, "Укажите два разных номера")
    src, dst = await _by_no(session, data.from_no), await _by_no(session, data.into_no)
    if src.role == GlobalRole.admin:
        raise HTTPException(400, "Аккаунт администратора нельзя объединить с другим")
    s_id, d_id = src.id, dst.id

    # конфликты, которые нельзя свести автоматически
    both = (await session.execute(select(TournamentPlayer.tournament_id).where(TournamentPlayer.user_id == s_id)
                                  .intersect(select(TournamentPlayer.tournament_id).where(
                                      TournamentPlayer.user_id == d_id)))).all()
    if both:
        raise HTTPException(409, "Оба аккаунта играли в одном и том же турнире — объединить нельзя")
    leagues = (await session.execute(select(LeagueMember.league_id).where(LeagueMember.user_id == s_id)
                                     .intersect(select(LeagueMember.league_id).where(LeagueMember.user_id == d_id)))).all()
    if leagues:
        raise HTTPException(409, "Оба аккаунта участвуют в одном сезоне лиги — объединить нельзя")
    mutual = await _count(session, select(func.count()).select_from(Deal).where(or_(
        (Deal.seller_id == s_id) & (Deal.buyer_id == d_id), (Deal.seller_id == d_id) & (Deal.buyer_id == s_id))))
    if mutual:
        raise HTTPException(409, "У аккаунтов есть сделки друг с другом — объединить нельзя")

    # клубы, где состоят оба: очки лиги и ивенты складываются, банк EDH - того, кто играл больше
    for sm in (await session.execute(select(ClubMember).where(ClubMember.user_id == s_id))).scalars().all():
        dm = (await session.execute(select(ClubMember).where(ClubMember.club_id == sm.club_id,
                                                             ClubMember.user_id == d_id))).scalar_one_or_none()
        if not dm:
            continue
        if (sm.events_played or 0) > (dm.events_played or 0):
            dm.edh_bank, dm.last_bonus_week = sm.edh_bank, sm.last_bonus_week
        dm.league_points = (dm.league_points or 0) + (sm.league_points or 0)
        dm.events_played = (dm.events_played or 0) + (sm.events_played or 0)
        if sm.role == ClubRole.organizer:
            dm.role = ClubRole.organizer
        games = {g for g in f"{dm.judge_games},{sm.judge_games}".split(",") if g}
        dm.judge_games = ",".join(sorted(games))
        dm.joined_at = min(dm.joined_at, sm.joined_at)
        await session.delete(sm)
    # одна заявка «Создатель Клуба» на рассмотрении на человека
    if (await session.execute(select(ClubCreatorRequest.id).where(ClubCreatorRequest.user_id == d_id,
                                                                  ClubCreatorRequest.status == "pending"))).first():
        await session.execute(delete(ClubCreatorRequest).where(ClubCreatorRequest.user_id == s_id,
                                                               ClubCreatorRequest.status == "pending"))
    await session.execute(delete(PasswordReset).where(PasswordReset.user_id == s_id))
    await session.flush()

    # все остальные ссылки на пользователя - по схеме
    moved = 0
    for table in Base.metadata.sorted_tables:
        if table.name == "users":
            continue
        for fk in table.foreign_keys:
            if fk.column.table.name == "users" and fk.column.name == "id":
                res = await session.execute(update(table).where(fk.parent == s_id).values({fk.parent.name: d_id}))
                moved += res.rowcount or 0

    dst.is_club_creator = dst.is_club_creator or src.is_club_creator
    dst.is_moderator = dst.is_moderator or src.is_moderator
    dst.tg_username = dst.tg_username or src.tg_username
    session.expunge(src)
    await session.execute(delete(User).where(User.id == s_id))
    await session.commit()
    return {"merged": data.from_no, "into": data.into_no, "nickname": dst.nickname, "moved": moved}
