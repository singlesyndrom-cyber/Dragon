"""Драфт турнира: настройки, рассадка, таймер на экране судьи (см. app/draft.py)."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .. import draft as dl
from ..db import get_session
from ..deps import current_user
from ..models import Tournament, TournamentPlayer, TournamentStatus, User
from .tournaments import _get, _require_judge

router = APIRouter(prefix="/tournaments", tags=["draft"])


class ControlIn(BaseModel):
    action: str = Field(pattern="^(start|pause|resume|skip|add|reset)$")
    seconds: int = Field(default=30, ge=1, le=3600)


def _draft(t: Tournament) -> dict:
    if not t.draft:
        raise HTTPException(400, "Это не драфт-турнир")
    return t.draft


async def _seating(session, tid: int) -> list[dict]:
    rows = (await session.execute(select(TournamentPlayer.user_id, User.nickname, TournamentPlayer.pod,
                                         TournamentPlayer.seat, TournamentPlayer.dropped)
                                  .join(User, User.id == TournamentPlayer.user_id)
                                  .where(TournamentPlayer.tournament_id == tid))).all()
    return sorted([{"user_id": u, "nickname": n, "pod": p, "seat": s, "dropped": d} for u, n, p, s, d in rows],
                  key=lambda r: (r["pod"] or 99, r["seat"] or 99, r["nickname"].lower()))


@router.get("/{tid}/draft")
async def get_draft(tid: int, session: AsyncSession = Depends(get_session)):
    """Состояние драфта для экрана судьи: настройки, рассадка, текущий этап и остаток времени."""
    t = await _get(session, tid)
    d = _draft(t)
    now = datetime.now(timezone.utc)
    raw = d.get("state") or {}
    return {"config": d["config"], "state": dl.current(d["config"], raw, now), "raw": raw,
            "timeline": dl.steps_with_extra(d["config"], raw), "seating": await _seating(session, tid),
            "status": t.status.value, "round": t.current_round, "rounds_total": t.rounds_total,
            "round_minutes": t.round_minutes, "round_started_at": t.round_started_at, "server_now": now}


@router.put("/{tid}/draft/config")
async def set_config(tid: int, cfg: dict, user: User = Depends(current_user),
                     session: AsyncSession = Depends(get_session)):
    t = await _get(session, tid)
    await _require_judge(session, t, user)
    d = _draft(t)
    if (d.get("state") or {}).get("started_at"):
        raise HTTPException(400, "Драфт уже идёт: настройки меняются до старта")
    config = dl.clean_config({**d["config"], **cfg}, t.game)
    t.draft = {**d, "config": config}
    t.round_minutes = config["round_minutes"]
    await session.commit()
    return config


@router.post("/{tid}/draft/seat")
async def seat_players(tid: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    """Случайная рассадка (можно повторить до начала драфта): столы по 6-8 игроков."""
    t = await _get(session, tid)
    await _require_judge(session, t, user)
    d = _draft(t)
    if t.status != TournamentStatus.registration or (d.get("state") or {}).get("started_at"):
        raise HTTPException(400, "Рассадка - до начала драфта")
    ids = (await session.execute(select(TournamentPlayer.user_id).where(
        TournamentPlayer.tournament_id == tid, TournamentPlayer.dropped.is_(False)))).scalars().all()
    if len(ids) < 2:
        raise HTTPException(400, "Нужно хотя бы 2 участника")
    await session.execute(update(TournamentPlayer).where(TournamentPlayer.tournament_id == tid)
                          .values(pod=None, seat=None))
    for uid, pod, seat in dl.seat(ids):
        await session.execute(update(TournamentPlayer).where(TournamentPlayer.tournament_id == tid,
                                                             TournamentPlayer.user_id == uid).values(pod=pod, seat=seat))
    await session.commit()
    return {"pods": dl.pods(len(ids)), "seating": await _seating(session, tid)}


@router.post("/{tid}/draft/control")
async def control(tid: int, data: ControlIn, user: User = Depends(current_user),
                  session: AsyncSession = Depends(get_session)):
    """Старт, пауза, продолжение, «пропустить этап», «+N секунд», сброс таймера."""
    t = await _get(session, tid)
    await _require_judge(session, t, user)
    d = _draft(t)
    st = dict(d.get("state") or {})
    now = datetime.now(timezone.utc)
    if data.action == "start":
        if st.get("started_at"):
            raise HTTPException(400, "Драфт уже начат")
        seated = (await session.execute(select(TournamentPlayer.id).where(
            TournamentPlayer.tournament_id == tid, TournamentPlayer.seat.is_not(None)).limit(1))).first()
        if not seated:
            raise HTTPException(400, "Сначала рассадите игроков")
        st = {"started_at": now.isoformat(), "offset": 0}
    elif not st.get("started_at") and data.action != "reset":
        raise HTTPException(400, "Драфт ещё не начат")
    elif data.action == "pause" and not st.get("paused_at"):
        st["paused_at"] = now.isoformat()
    elif data.action == "resume" and st.get("paused_at"):
        paused = datetime.fromisoformat(st.pop("paused_at"))
        st["offset"] = float(st.get("offset", 0)) - (now - paused).total_seconds()
    elif data.action == "skip":
        st = dl.skip(d["config"], st, now)
    elif data.action == "add":
        st = dl.add_time(d["config"], st, now, data.seconds)
    elif data.action == "reset":
        if t.status != TournamentStatus.registration:
            raise HTTPException(400, "Туры уже идут")
        st = {}
    t.draft = {**d, "state": st}
    await session.commit()
    return dl.current(d["config"], st, now)
