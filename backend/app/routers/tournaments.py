import random
from collections import Counter
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .. import leagues, notify
from ..config import settings
from ..db import get_session
from ..deps import current_user, is_club_organizer
from ..models import (Club, ClubMember, ClubStats, League, Match, MatchResult, Tournament,
                      TournamentFormat, TournamentPlayer, TournamentStatus, User)
from ..swiss import MatchRec, compute_standings, default_rounds, pair_round

router = APIRouter(prefix="/tournaments", tags=["tournaments"])


DeckPolicy = Literal["none", "optional", "required"]


class TournamentIn(BaseModel):
    club_id: int
    name: str = Field(min_length=2, max_length=128)
    game: Literal["mtg", "berserk"] = "mtg"
    format: TournamentFormat = TournamentFormat.swiss
    rounds: int | None = Field(default=None, ge=1, le=15)
    starts_at: datetime | None = None   # дата и время ивента; без часового пояса - APP_TIMEZONE
    description: str = Field(default="", max_length=5000)
    deck_policy: DeckPolicy = "optional"
    self_registration: bool = True       # False - игроков записывает только организатор
    max_players: int | None = Field(default=None, ge=2, le=512)
    league_id: int | None = None


class TournamentPatch(BaseModel):
    """Правка настроек до старта."""
    name: str | None = Field(default=None, min_length=2, max_length=128)
    rounds: int | None = Field(default=None, ge=1, le=15)
    starts_at: datetime | None = None
    description: str | None = Field(default=None, max_length=5000)
    deck_policy: DeckPolicy | None = None
    self_registration: bool | None = None
    max_players: int | None = Field(default=None, ge=2, le=512)
    league_id: int | None = None


class PlayerAdd(BaseModel):
    """Организатор добавляет игрока: существующего (user_id) или гостя по имени (nickname)."""
    user_id: int | None = None
    nickname: str | None = Field(default=None, min_length=2, max_length=64)
    bracket: int = Field(default=2, ge=1, le=5)


class DropIn(BaseModel):
    dropped: bool = True


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=ZoneInfo(settings.app_timezone))


async def _check_league(session: AsyncSession, league_id: int | None, club_id: int, game: str, fmt) -> None:
    if league_id is None:
        return
    league = await session.get(League, league_id)
    if not league or league.club_id != club_id:
        raise HTTPException(400, "Сезон лиги не найден в этом клубе")
    if leagues.status(league, datetime.now(ZoneInfo(settings.app_timezone)).date()) == "finished":
        raise HTTPException(400, "Сезон лиги уже завершён")
    if not leagues.fits(league, game, fmt.value if hasattr(fmt, "value") else fmt):
        raise HTTPException(400, "Формат турнира не подходит этому сезону: EDH-сезон - только EDH, "
                                 "сезон «Берсерка» - швейцарки по «Берсерку»")


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
    rows = res.all()
    players = {tp.user_id: (float(lp or 0), tp.seed) for tp, lp in rows}
    t._active = {tp.user_id for tp, _ in rows if not tp.dropped}   # для паринга: без выбывших
    ms = (await session.execute(select(Match).where(Match.tournament_id == t.id))).scalars().all()
    recs = [MatchRec(m.p1_user_id, m.p2_user_id, m.result.value if m.result else None) for m in ms]
    return players, ms, recs


async def _make_round(session: AsyncSession, t: Tournament, players, recs):
    active = getattr(t, "_active", None)
    if active is not None and len(active) < 2:
        raise HTTPException(400, "В турнире осталось меньше двух игроков: завершите его")
    pairs = pair_round(players, recs, active)
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
    await _check_league(session, data.league_id, data.club_id, data.game, data.format)
    rounds = None if data.format == TournamentFormat.edh else (
        data.rounds or (1 if data.format == TournamentFormat.fast_swiss else None))
    extra = {"starts_at": _aware(data.starts_at)} if data.starts_at else {}
    t = Tournament(club_id=data.club_id, name=data.name.strip(), game=data.game, format=data.format,
                   rounds_total=rounds, created_by=user.id, description=data.description.strip(),
                   deck_policy=data.deck_policy, self_registration=data.self_registration,
                   max_players=data.max_players, league_id=data.league_id, **extra)
    session.add(t)
    await session.flush()
    await notify.on_tournament_created(session, t)
    await session.commit()
    return {"id": t.id}


def _t_out(t: Tournament, club: Club | None, players: int | None = None) -> dict:
    return {"id": t.id, "club_id": t.club_id, "club": club.name if club else None, "club_slug": club.slug if club else None,
            "name": t.name, "game": t.game, "format": t.format, "status": t.status, "round": t.current_round,
            "rounds_total": t.rounds_total, "starts_at": t.starts_at, "players": players,
            "league_id": t.league_id, "deck_policy": t.deck_policy, "self_registration": t.self_registration,
            "max_players": t.max_players}


@router.get("")
async def list_tournaments(club_id: int | None = None, status: TournamentStatus | None = None,
                           limit: int = Query(100, ge=1, le=200), session: AsyncSession = Depends(get_session)):
    counts = (select(TournamentPlayer.tournament_id, func.count().label("n"))
              .group_by(TournamentPlayer.tournament_id).subquery())
    q = (select(Tournament, Club, counts.c.n).join(Club, Club.id == Tournament.club_id)
         .outerjoin(counts, counts.c.tournament_id == Tournament.id))
    if club_id:
        q = q.where(Tournament.club_id == club_id)
    if status:
        q = q.where(Tournament.status == status)
    order = Tournament.starts_at.asc() if status == TournamentStatus.registration else Tournament.starts_at.desc()
    rows = (await session.execute(q.order_by(order).limit(limit))).all()
    return [_t_out(t, c, n or 0) for t, c, n in rows]


@router.get("/{tid}")
async def get_tournament(tid: int, session: AsyncSession = Depends(get_session)):
    """Карточка турнира: клуб и участники (с брекетом и отметкой о приходе для EDH)."""
    t = await _get(session, tid)
    club = await session.get(Club, t.club_id)
    rows = (await session.execute(select(TournamentPlayer, User.nickname, User.is_guest)
                                  .join(User, User.id == TournamentPlayer.user_id)
                                  .where(TournamentPlayer.tournament_id == tid).order_by(User.nickname))).all()
    league = await session.get(League, t.league_id) if t.league_id else None
    return {**_t_out(t, club, len(rows)), "description": t.description,
            "league": {"id": league.id, "name": league.name, "kind": league.kind.value} if league else None,
            "participants": [{"user_id": tp.user_id, "nickname": nick, "guest": guest, "bracket": tp.bracket,
                              "checked_in": tp.checked_in, "dropped": tp.dropped,
                              "has_deck": tp.deck_id is not None} for tp, nick, guest in rows]}


@router.patch("/{tid}", status_code=204)
async def update_tournament(tid: int, data: TournamentPatch, user: User = Depends(current_user),
                            session: AsyncSession = Depends(get_session)):
    t = await _get(session, tid)
    await _require_org(session, t, user)
    if t.status != TournamentStatus.registration:
        raise HTTPException(400, "Настройки меняются только до старта")
    f = data.model_dump(exclude_unset=True)
    if "league_id" in f:
        await _check_league(session, f["league_id"], t.club_id, t.game, t.format)
        t.league_id = f["league_id"]
    for k in ("name", "description", "deck_policy", "self_registration", "max_players"):
        if k in f and (f[k] is not None or k == "max_players"):
            setattr(t, k, f[k].strip() if isinstance(f[k], str) and k in ("name", "description") else f[k])
    if "rounds" in f and t.format != TournamentFormat.edh:
        t.rounds_total = f["rounds"]
    if f.get("starts_at"):
        t.starts_at = _aware(f["starts_at"])
    await session.commit()


async def _ensure_member(session: AsyncSession, club_id: int, user_id: int) -> None:
    exists = (await session.execute(select(ClubMember).where(
        ClubMember.club_id == club_id, ClubMember.user_id == user_id))).scalar_one_or_none()
    if not exists:
        session.add(ClubMember(club_id=club_id, user_id=user_id))


async def _count_players(session: AsyncSession, tid: int) -> int:
    return (await session.execute(select(func.count()).select_from(TournamentPlayer).where(
        TournamentPlayer.tournament_id == tid))).scalar_one()


@router.post("/{tid}/players", status_code=201)
async def add_player(tid: int, data: PlayerAdd, user: User = Depends(current_user),
                     session: AsyncSession = Depends(get_session)):
    """Организатор записывает игрока сам. Гость по имени переиспользуется в этом клубе (тот же ник - тот же гость)."""
    t = await _get(session, tid)
    await _require_org(session, t, user)
    late_edh = t.format == TournamentFormat.edh and t.status == TournamentStatus.running   # опоздавший на EDH
    if t.status != TournamentStatus.registration and not late_edh:
        raise HTTPException(400, "Игроков можно добавлять только до старта")
    if t.max_players and await _count_players(session, tid) >= t.max_players:
        raise HTTPException(400, f"Достигнут лимит участников: {t.max_players}")
    if data.user_id:
        player = await session.get(User, data.user_id)
        if not player:
            raise HTTPException(404, "Игрок не найден")
    elif data.nickname and data.nickname.strip():
        nick = " ".join(data.nickname.split())
        player = (await session.execute(select(User).where(
            User.is_guest.is_(True), User.guest_club_id == t.club_id,
            func.lower(User.nickname) == nick.lower()))).scalars().first()
        if not player:
            player = User(nickname=nick, is_guest=True, guest_club_id=t.club_id)
            session.add(player)
            await session.flush()
    else:
        raise HTTPException(422, "Укажите игрока или имя гостя")
    if (await session.execute(select(TournamentPlayer).where(
            TournamentPlayer.tournament_id == tid, TournamentPlayer.user_id == player.id))).scalar_one_or_none():
        raise HTTPException(409, f"{player.nickname} уже в списке")
    await _ensure_member(session, t.club_id, player.id)
    session.add(TournamentPlayer(tournament_id=tid, user_id=player.id, seed=random.randint(0, 10**9),
                                 bracket=data.bracket, checked_in=late_edh))
    await session.commit()
    return {"user_id": player.id, "nickname": player.nickname, "guest": player.is_guest}


@router.delete("/{tid}/players/{uid}", status_code=204)
async def remove_player(tid: int, uid: int, user: User = Depends(current_user),
                        session: AsyncSession = Depends(get_session)):
    t = await _get(session, tid)
    await _require_org(session, t, user)
    if t.status != TournamentStatus.registration:
        raise HTTPException(400, "После старта игрока можно только снять с турнира (выбыл)")
    tp = (await session.execute(select(TournamentPlayer).where(
        TournamentPlayer.tournament_id == tid, TournamentPlayer.user_id == uid))).scalar_one_or_none()
    if tp:
        await session.delete(tp)
        await session.commit()


@router.post("/{tid}/players/{uid}/drop", status_code=204)
async def drop_player(tid: int, uid: int, data: DropIn, user: User = Depends(current_user),
                      session: AsyncSession = Depends(get_session)):
    """Игрок выбыл: остаётся в таблице, но в следующих турах пар не получает (EDH - не садится за столы)."""
    t = await _get(session, tid)
    await _require_org(session, t, user)
    if t.status != TournamentStatus.running:
        raise HTTPException(400, "Снять игрока можно только во время турнира")
    tp = (await session.execute(select(TournamentPlayer).where(
        TournamentPlayer.tournament_id == tid, TournamentPlayer.user_id == uid))).scalar_one_or_none()
    if not tp:
        raise HTTPException(404, "Игрок не в турнире")
    tp.dropped = data.dropped
    await session.commit()


@router.post("/{tid}/register", status_code=204)
async def register(tid: int, bracket: int = Query(2, ge=1, le=5), user: User = Depends(current_user),
                   session: AsyncSession = Depends(get_session)):
    t = await _get(session, tid)
    if t.status != TournamentStatus.registration:
        raise HTTPException(400, "Регистрация закрыта")
    if not t.self_registration:
        raise HTTPException(403, "На этот турнир игроков записывает организатор")
    if t.max_players and await _count_players(session, tid) >= t.max_players:
        raise HTTPException(400, f"Мест нет: лимит {t.max_players} участников")
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
async def start(tid: int, force: bool = Query(False), user: User = Depends(current_user),
                session: AsyncSession = Depends(get_session)):
    t = await _get(session, tid)
    await _require_org(session, t, user)
    if t.format == TournamentFormat.edh:
        raise HTTPException(400, "Для EDH используйте POST /edh/{id}/round")
    if t.status != TournamentStatus.registration:
        raise HTTPException(400, "Турнир уже запущен")
    if t.deck_policy == "required" and not force:
        missing = (await session.execute(select(User.nickname).join(
            TournamentPlayer, TournamentPlayer.user_id == User.id).where(
            TournamentPlayer.tournament_id == tid, TournamentPlayer.deck_id.is_(None)))).scalars().all()
        if missing:
            raise HTTPException(409, "Деклист не подан: " + ", ".join(sorted(missing)))
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
    ms = res.scalars().all()
    ids = {m.p1_user_id for m in ms} | {m.p2_user_id for m in ms if m.p2_user_id}
    names = dict((await session.execute(select(User.id, User.nickname).where(User.id.in_(ids)))).all())
    return [{"match_id": m.id, "table": m.table_no, "p1_id": m.p1_user_id, "p1": names.get(m.p1_user_id),
             "p2_id": m.p2_user_id, "p2": names.get(m.p2_user_id) if m.p2_user_id else None, "result": m.result}
            for m in ms]


@router.post("/matches/{match_id}/result", status_code=204)
async def report_result(match_id: int, data: ResultIn, user: User = Depends(current_user),
                        session: AsyncSession = Depends(get_session)):
    m = await session.get(Match, match_id)
    if not m:
        raise HTTPException(404, "Матч не найден")
    t = await _get(session, m.tournament_id)
    await _require_org(session, t, user)
    if t.status != TournamentStatus.running:
        raise HTTPException(400, "Результаты вводятся, пока турнир идёт")
    # прошлый тур можно исправить (как в AetherHub): таблица пересчитается, уже сделанные пары не меняются
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
    names = dict((await session.execute(select(User.id, User.nickname).where(User.id.in_(list(players))))).all())
    active = getattr(t, "_active", set())
    return [{"rank": r.rank, "player": names.get(r.player_id), "user_id": r.player_id, "points": r.points,
             "wins": r.wins, "owp": round(r.owp, 3), "buchholz": r.buchholz,
             "dropped": r.player_id not in active} for r in compute_standings(players, recs)]


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
