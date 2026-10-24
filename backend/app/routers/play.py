"""Приложение игрока за столом: текущий матч в идущем турнире (соперник, стол, тур) и отправка результата судье.

Игрок присылает результат из приложения (вручную или по счётчику жизней). Судья видит отчёты своего тура
в реальном времени и вносит их одной кнопкой; если оба игрока прислали одно и то же - отчёт «согласован».
Сам результат матча меняет только судья (как и раньше) - приложение лишь подсказывает ему.
"""
import re
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import rating as R
from ..db import get_session
from ..deps import current_user
from ..models import (Club, Match, MatchReport, MatchResult, PlayerRating, Tournament, TournamentFormat,
                      TournamentPlayer, TournamentStatus, User)
from .tournaments import _get, _require_judge, set_result

router = APIRouter(prefix="/play", tags=["play"])

SCORE = re.compile(r"^[0-9]-[0-9](-[0-9])?$")
FLIP = {"p1": "p2", "p2": "p1", "draw": "draw"}


def _v(x) -> str | None:
    return getattr(x, "value", x)


def _side(m: Match, uid: int) -> str:
    return "p1" if m.p1_user_id == uid else "p2"


def _outcome(result: str | None, side: str) -> str | None:
    """Результат матча (p1/p2/draw) глазами игрока: win / loss / draw."""
    if result is None:
        return None
    return "draw" if result == "draw" else ("win" if result == side else "loss")


def _flip_score(score: str | None) -> str | None:
    if not score:
        return None
    a = score.split("-")
    return "-".join([a[1], a[0], *a[2:]])


def _report_out(r: MatchReport | None, side: str) -> dict | None:
    if not r:
        return None
    score = r.score if side == "p1" else _flip_score(r.score)
    return {"outcome": _outcome(_v(r.result), side), "score": score, "source": r.source, "at": r.updated_at}


@router.get("/current")
async def current(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    """Матчи текущего тура в идущих турнирах, где играет пользователь (обычно один)."""
    rows = (await session.execute(
        select(Tournament, Match, Club.name)
        .join(TournamentPlayer, (TournamentPlayer.tournament_id == Tournament.id) & (TournamentPlayer.user_id == user.id))
        .join(Match, (Match.tournament_id == Tournament.id) & (Match.round_no == Tournament.current_round)
              & ((Match.p1_user_id == user.id) | (Match.p2_user_id == user.id)))
        .join(Club, Club.id == Tournament.club_id)
        .where(Tournament.status == TournamentStatus.running, Tournament.format != TournamentFormat.edh,
               TournamentPlayer.dropped.is_(False))
        .order_by(Tournament.starts_at.desc()))).all()
    out = []
    for t, m, club in rows:
        side = _side(m, user.id)
        opp_id = m.p2_user_id if side == "p1" else m.p1_user_id
        opp = await session.get(User, opp_id) if opp_id else None
        rep = {r.user_id: r for r in (await session.execute(
            select(MatchReport).where(MatchReport.match_id == m.id))).scalars()}
        opp_rating = None
        if opp:
            pr = (await session.execute(select(PlayerRating).where(
                PlayerRating.user_id == opp.id,
                PlayerRating.discipline == R.discipline(t.game, t.format, t.draft)))).scalar_one_or_none()
            if pr:
                opp_rating = {"rating": round(pr.rating), "games": pr.games}
        out.append({
            "tournament": {"id": t.id, "name": t.name, "game": t.game, "format": _v(t.format), "club": club,
                           "round": t.current_round, "rounds_total": t.rounds_total},
            "match_id": m.id, "table": m.table_no, "side": side, "bye": opp is None,
            "opponent": {"nickname": opp.nickname, "player_no": opp.player_no, "is_guest": opp.is_guest,
                         "rating": opp_rating} if opp else None,
            "result": _outcome(_v(m.result), side) if opp else "win",
            "my_report": _report_out(rep.get(user.id), side),
            "opp_report": _report_out(rep.get(opp_id), side) if opp_id else None,
        })
    return out


class ReportIn(BaseModel):
    outcome: Literal["win", "loss", "draw"]
    score: str | None = Field(None, max_length=8)      # счёт партий с вашей стороны: "2-1"
    source: Literal["manual", "life"] = "manual"


async def _my_match(session: AsyncSession, mid: int, user: User) -> tuple[Tournament, Match]:
    m = await session.get(Match, mid)
    if not m or user.id not in (m.p1_user_id, m.p2_user_id):
        raise HTTPException(404, "Матч не найден")
    t = await _get(session, m.tournament_id)
    if t.status != TournamentStatus.running or m.round_no != t.current_round:
        raise HTTPException(400, "Этот тур уже закрыт")
    if m.p2_user_id is None:
        raise HTTPException(400, "У вас bye: результат не нужен")
    return t, m


@router.post("/matches/{mid}/report")
async def report(mid: int, data: ReportIn, user: User = Depends(current_user),
                 session: AsyncSession = Depends(get_session)):
    t, m = await _my_match(session, mid, user)
    if m.result is not None:
        raise HTTPException(409, "Судья уже внёс результат этого матча")
    if data.score and not SCORE.match(data.score):
        raise HTTPException(400, "Счёт пишется так: 2-1 (или 1-1-1 с ничьими)")
    side = _side(m, user.id)
    result = "draw" if data.outcome == "draw" else (side if data.outcome == "win" else FLIP[side])
    score = data.score if side == "p1" else _flip_score(data.score)
    r = (await session.execute(select(MatchReport).where(
        MatchReport.match_id == m.id, MatchReport.user_id == user.id))).scalar_one_or_none()
    if r is None:
        r = MatchReport(match_id=m.id, user_id=user.id)
        session.add(r)
    r.result, r.score, r.source = MatchResult(result), score, data.source
    r.updated_at = datetime.now().astimezone()
    await session.commit()
    return {"ok": True}


@router.delete("/matches/{mid}/report", status_code=204)
async def withdraw(mid: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    _, m = await _my_match(session, mid, user)
    await session.execute(delete(MatchReport).where(MatchReport.match_id == m.id, MatchReport.user_id == user.id))
    await session.commit()


async def _round_reports(session: AsyncSession, t: Tournament) -> list[dict]:
    ms = (await session.execute(select(Match).where(
        Match.tournament_id == t.id, Match.round_no == t.current_round, Match.p2_user_id.is_not(None))
        .order_by(Match.table_no))).scalars().all()
    if not ms:
        return []
    reps = (await session.execute(select(MatchReport).where(MatchReport.match_id.in_([m.id for m in ms])))).scalars().all()
    by: dict[int, dict[int, MatchReport]] = {}
    for r in reps:
        by.setdefault(r.match_id, {})[r.user_id] = r
    ids = {x for m in ms for x in (m.p1_user_id, m.p2_user_id)}
    names = dict((await session.execute(select(User.id, User.nickname).where(User.id.in_(ids)))).all())
    out = []
    for m in ms:
        got = by.get(m.id, {})
        if not got:
            continue
        r1, r2 = got.get(m.p1_user_id), got.get(m.p2_user_id)
        results = {_v(r.result) for r in (r1, r2) if r}
        agreed = _v(r1.result) if r1 and r2 and len(results) == 1 else None
        conflict = len(results) > 1
        one = next(iter(results)) if len(results) == 1 else None
        pick = r1 or r2
        out.append({
            "match_id": m.id, "table": m.table_no, "p1": names.get(m.p1_user_id), "p2": names.get(m.p2_user_id),
            "p1_report": {"result": _v(r1.result), "score": r1.score, "source": r1.source, "at": r1.updated_at} if r1 else None,
            "p2_report": {"result": _v(r2.result), "score": r2.score, "source": r2.source, "at": r2.updated_at} if r2 else None,
            "agreed": agreed, "conflict": conflict, "suggested": one,
            "score": pick.score if one and pick else None,
            "applied": _v(m.result),
        })
    return out


@router.get("/tournaments/{tid}/reports")
async def round_reports(tid: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    """Для судьи: отчёты игроков текущего тура (опрашивается раз в несколько секунд)."""
    t = await _get(session, tid)
    await _require_judge(session, t, user)
    if t.status != TournamentStatus.running:
        return {"round": t.current_round, "items": []}
    return {"round": t.current_round, "items": await _round_reports(session, t)}


class ApplyIn(BaseModel):
    match_ids: list[int] | None = None     # None - все согласованные


@router.post("/tournaments/{tid}/reports/apply")
async def apply_reports(tid: int, data: ApplyIn, user: User = Depends(current_user),
                        session: AsyncSession = Depends(get_session)):
    """Судья вносит согласованные отчёты (или выбранные: если прислал только один игрок)."""
    t = await _get(session, tid)
    await _require_judge(session, t, user)
    if t.status != TournamentStatus.running:
        raise HTTPException(400, "Турнир не идёт")
    items = await _round_reports(session, t)
    applied = 0
    for it in items:
        if it["applied"]:
            continue
        if data.match_ids is None:
            res = it["agreed"]
        elif it["match_id"] in data.match_ids:
            res = it["suggested"]
        else:
            continue
        if res:
            set_result(session, t, await session.get(Match, it["match_id"]), res, user)
            applied += 1
    await session.commit()
    return {"applied": applied}
