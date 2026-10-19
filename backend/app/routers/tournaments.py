import random
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .. import notify
from ..config import settings
from ..db import get_session
from ..deps import current_user, is_club_organizer
from ..models import (Club, ClubMember, ClubStats, Match, MatchResult, Tournament,
                      TournamentFormat, TournamentPlayer, TournamentStatus, User)
from ..swiss import MatchRec, compute_standings, default_rounds, pair_round

router = APIRouter(prefix="/tournaments", tags=["tournaments"])


class TournamentIn(BaseModel):
    club_id: int
    name: str = Field(min_length=2, max_length=128)
    game: str = "mtg"
    format: TournamentFormat = TournamentFormat.swiss
    rounds: int | None = Field(default=None, ge=1, le=15)
    starts_at: datetime | None = None   # дата и время ивента; без часового пояса - APP_TIMEZONE


class ResultIn(BaseModel):
    result: MatchResult


async def _get(session: AsyncSession, tid: int) -> Tournament:
    t = await session.get(Tournament, tid)
    if not t:
        raise HTTPException(404, "Турнир не найден")
    return t


async def _require_org(session: AsyncSession, t: Tournament, user: User):
    if not await is_club_organizer(session, t.club_id, user):
        raise HTTPException(403, "Нужны права организатора клуба")


async def _state(session: AsyncSession, t: Tournament):
    """players для движка (id -> (рейтинг клуба, seed)) и список матчей."""
    if t.format == TournamentFormat.edh:
        raise HTTPException(400, "Это EDH-ивент: используйте разделы /edh")
    res = await session.execute(
        select(TournamentPlayer, ClubMember.league_points)
        .join(ClubMember, (ClubMember.user_id == TournamentPlayer.user_id) & (ClubMember.club_id == t.club_id),
              isouter=True)
        .where(TournamentPlayer.tournament_id == t.id))
    players = {tp.user_id: (float(lp or 0), tp.seed) for tp, lp in res.all()}
    ms = (await session.execute(select(Match).where(Match.tournament_id == t.id))).scalars().all()
    recs = [MatchRec(m.p1_user_id, m.p2_user_id, m.result.value if m.result else None) for m in ms]
    return players, ms, recs


async def _make_round(session: AsyncSession, t: Tournament, players, recs):
    pairs = pair_round(players, recs)
    t.current_round += 1
    for table, (a, b) in enumerate(pairs, 1):
        session.add(Match(tournament_id=t.id, round_no=t.current_round, table_no=table,
                          p1_user_id=a, p2_user_id=b,
                          result=MatchResult.p1 if b is None else None))  # bye = победа


@router.post("", status_code=201)
async def create_tournament(data: TournamentIn, user: User = Depends(current_user),
                            session: AsyncSession = Depends(get_session)):
    if not await is_club_organizer(session, data.club_id, user):
        raise HTTPException(403, "Нужны права организатора клуба")
    rounds = data.rounds or (1 if data.format == TournamentFormat.fast_swiss else None)
    extra = {}
    if data.starts_at:
        extra["starts_at"] = (data.starts_at if data.starts_at.tzinfo
                              else data.starts_at.replace(tzinfo=ZoneInfo(settings.app_timezone)))
    t = Tournament(club_id=data.club_id, name=data.name, game=data.game, format=data.format,
                   rounds_total=rounds, created_by=user.id, **extra)
    session.add(t)
    await session.flush()
    await notify.on_tournament_created(session, t)
    await session.commit()
    return {"id": t.id}


@router.get("")
async def list_tournaments(club_id: int | None = None, session: AsyncSession = Depends(get_session)):
    q = select(Tournament).order_by(Tournament.starts_at.desc()).limit(100)
    if club_id:
        q = q.where(Tournament.club_id == club_id)
    return [{"id": t.id, "club_id": t.club_id, "name": t.name, "format": t.format,
             "status": t.status, "round": t.current_round, "rounds_total": t.rounds_total}
            for t in (await session.execute(q)).scalars()]


@router.post("/{tid}/register", status_code=204)
async def register(tid: int, bracket: int = Query(2, ge=1, le=5), user: User = Depends(current_user),
                   session: AsyncSession = Depends(get_session)):
    t = await _get(session, tid)
    if t.status != TournamentStatus.registration:
        raise HTTPException(400, "Регистрация закрыта")
    exists = await session.execute(select(TournamentPlayer).where(
        TournamentPlayer.tournament_id == tid, TournamentPlayer.user_id == user.id))
    if exists.scalar_one_or_none():
        raise HTTPException(409, "Вы уже зарегистрированы")
    member = await session.execute(select(ClubMember).where(
        ClubMember.club_id == t.club_id, ClubMember.user_id == user.id))
    if not member.scalar_one_or_none():
        session.add(ClubMember(club_id=t.club_id, user_id=user.id))  # автовступление в клуб
    session.add(TournamentPlayer(tournament_id=tid, user_id=user.id, seed=random.randint(0, 10**9), bracket=bracket))
    await session.commit()


@router.delete("/{tid}/register", status_code=204)
async def unregister(tid: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    t = await _get(session, tid)
    if t.status != TournamentStatus.registration:
        raise HTTPException(400, "Турнир уже начался")
    res = await session.execute(select(TournamentPlayer).where(
        TournamentPlayer.tournament_id == tid, TournamentPlayer.user_id == user.id))
    tp = res.scalar_one_or_none()
    if tp:
        await session.delete(tp)
        await session.commit()


@router.post("/{tid}/start")
async def start(tid: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    t = await _get(session, tid)
    await _require_org(session, t, user)
    if t.format == TournamentFormat.edh:
        raise HTTPException(400, "Для EDH используйте POST /edh/{id}/round")
    if t.status != TournamentStatus.registration:
        raise HTTPException(400, "Турнир уже запущен")
    players, _, recs = await _state(session, t)
    if len(players) < 2:
        raise HTTPException(400, "Нужно минимум 2 участника")
    t.rounds_total = t.rounds_total or default_rounds(len(players))
    t.status = TournamentStatus.running
    await _make_round(session, t, players, recs)
    await session.commit()
    return {"round": t.current_round, "rounds_total": t.rounds_total}


@router.get("/{tid}/round/{round_no}")
async def get_round(tid: int, round_no: int, session: AsyncSession = Depends(get_session)):
    res = await session.execute(
        select(Match).where(Match.tournament_id == tid, Match.round_no == round_no).order_by(Match.table_no))
    names = {u.id: u.nickname for u in (await session.execute(select(User))).scalars()}
    return [{"match_id": m.id, "table": m.table_no, "p1": names.get(m.p1_user_id),
             "p2": names.get(m.p2_user_id) if m.p2_user_id else None, "result": m.result}
            for m in res.scalars()]


@router.post("/matches/{match_id}/result", status_code=204)
async def report_result(match_id: int, data: ResultIn, user: User = Depends(current_user),
                        session: AsyncSession = Depends(get_session)):
    m = await session.get(Match, match_id)
    if not m:
        raise HTTPException(404, "Матч не найден")
    t = await _get(session, m.tournament_id)
    await _require_org(session, t, user)
    if t.status != TournamentStatus.running or m.round_no != t.current_round:
        raise HTTPException(400, "Результат можно вводить только в текущем туре")
    if m.p2_user_id is None:
        raise HTTPException(400, "Это bye, результат не нужен")
    m.result = data.result
    await session.commit()


@router.post("/{tid}/next-round")
async def next_round(tid: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    t = await _get(session, tid)
    await _require_org(session, t, user)
    if t.status != TournamentStatus.running:
        raise HTTPException(400, "Турнир не идёт")
    players, ms, recs = await _state(session, t)
    if any(m.result is None for m in ms if m.round_no == t.current_round):
        raise HTTPException(400, "Введены не все результаты тура")
    if t.current_round >= t.rounds_total:
        raise HTTPException(400, "Все туры сыграны, завершите турнир")
    await _make_round(session, t, players, recs)
    await session.commit()
    return {"round": t.current_round}


@router.get("/{tid}/standings")
async def standings(tid: int, session: AsyncSession = Depends(get_session)):
    t = await _get(session, tid)
    players, _, recs = await _state(session, t)
    names = {u.id: u.nickname for u in (await session.execute(select(User))).scalars()}
    return [{"rank": r.rank, "player": names.get(r.player_id), "user_id": r.player_id, "points": r.points,
             "owp": round(r.owp, 3), "buchholz": r.buchholz} for r in compute_standings(players, recs)]


@router.post("/{tid}/finish")
async def finish(tid: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    t = await _get(session, tid)
    await _require_org(session, t, user)
    if t.status != TournamentStatus.running:
        raise HTTPException(400, "Турнир не идёт")
    players, ms, recs = await _state(session, t)
    if any(m.result is None for m in ms if m.round_no == t.current_round):
        raise HTTPException(400, "Введены не все результаты тура")
    table = compute_standings(players, recs)

    # лига клуба: очки турнира добавляются к локальному рейтингу, счётчик ивентов растёт
    members = (await session.execute(select(ClubMember).where(ClubMember.club_id == t.club_id))).scalars()
    by_user = {m.user_id: m for m in members}
    for r in table:
        if r.player_id in by_user:
            by_user[r.player_id].league_points += r.points
            by_user[r.player_id].events_played += 1
    t.status = TournamentStatus.finished
    await session.flush()
    await _recompute_club_stats(session, t.club_id)
    await notify.on_tournament_finished(session, t, table)
    await session.commit()
    return {"winner_id": table[0].player_id, "standings": [{"rank": r.rank, "user_id": r.player_id,
                                                         "points": r.points} for r in table]}


async def _recompute_club_stats(session: AsyncSession, club_id: int):
    """Статистика клуба по всем завершённым турнирам."""
    rows = (await session.execute(
        select(Tournament.starts_at, func.count(TournamentPlayer.id))
        .join(TournamentPlayer, TournamentPlayer.tournament_id == Tournament.id)
        .where(Tournament.club_id == club_id, Tournament.status == TournamentStatus.finished)
        .group_by(Tournament.id, Tournament.starts_at))).all()
    stats = await session.get(ClubStats, club_id) or ClubStats(club_id=club_id)
    session.add(stats)
    total = len(rows)
    participants = sum(c for _, c in rows)
    stats.tournaments_total = total
    stats.participants_total = participants
    stats.avg_participants = participants / total if total else 0.0
    weekdays = Counter(d.weekday() for d, _ in rows)
    stats.busiest_weekday = weekdays.most_common(1)[0][0] if weekdays else None
    # Формула рейтинга клуба - стартовая, подкрутим по вашему желанию:
    # больше турниров и больше участников = выше рейтинг
    stats.club_rating = total * 10 + participants
