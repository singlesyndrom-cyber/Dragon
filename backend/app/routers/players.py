"""Публичная карточка игрока по номеру: кто это, где играет и какая у него репутация на аукционе."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import auction_service as svc
from ..db import get_session
from ..models import Club, ClubMember, DealRating, TournamentPlayer, User

router = APIRouter(prefix="/players", tags=["players"])


@router.get("/{player_no}")
async def player_card(player_no: int, session: AsyncSession = Depends(get_session)):
    user = (await session.execute(select(User).where(User.player_no == player_no))).scalar_one_or_none()
    if not user:
        raise HTTPException(404, "Игрока с таким номером нет")
    clubs = (await session.execute(select(Club.name, Club.slug, ClubMember.events_played)
                                   .join(ClubMember, ClubMember.club_id == Club.id)
                                   .where(ClubMember.user_id == user.id)
                                   .order_by(ClubMember.events_played.desc(), Club.name))).all()
    events = (await session.execute(select(func.count()).select_from(TournamentPlayer).where(
        TournamentPlayer.user_id == user.id))).scalar_one()
    reviews = (await session.execute(select(DealRating.role, DealRating.score, DealRating.comment, DealRating.created_at)
                                     .where(DealRating.to_user_id == user.id, DealRating.comment != "")
                                     .order_by(DealRating.id.desc()).limit(5))).all()
    return {"player_no": user.player_no, "nickname": user.nickname, "since": user.created_at,
            "banned": user.is_banned, "tournaments": events,
            "clubs": [{"name": n, "slug": sl, "events": e} for n, sl, e in clubs],
            "auction": await svc.user_rating(session, user.id),
            "reviews": [{"role": r, "score": sc, "comment": c, "at": at} for r, sc, c, at in reviews]}
