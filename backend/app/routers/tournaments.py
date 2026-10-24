import logging
import random
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete, exists, func, null, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .. import leagues, notify, rating, waitlist
from ..config import settings
from ..db import get_session
from ..deps import can_judge, current_user, is_club_organizer
from ..models import GlobalRole
from ..models import (Club, ClubMember, ClubStats, Deck, EdhSeat, WaitlistEntry, EdhTable, EdhTableStatus, League, Match, MatchResult,
                      ResultEdit, Tournament, TournamentFormat, TournamentPlayer, TournamentStatus, User)
from .. import draft as draft_logic
from ..swiss import MatchRec, compute_standings, default_rounds, pair_round
from .decks import check_deck_for

router = APIRouter(prefix="/tournaments", tags=["tournaments"])
log = logging.getLogger("tournaments")


DeckPolicy = Literal["none", "optional", "required"]
Tier = Literal["club", "city", "open", "regional", "pro"]


class TournamentIn(BaseModel):
    club_id: int
    name: str = Field(min_length=2, max_length=128)
    game: Literal["mtg", "berserk", "response"] = "mtg"
    format: TournamentFormat = TournamentFormat.swiss
    rounds: int | None = Field(default=None, ge=1, le=15)
    starts_at: datetime | None = None   # дата и время ивента; без часового пояса - APP_TIMEZONE
    description: str = Field(default="", max_length=5000)
    deck_policy: DeckPolicy = "optional"
    self_registration: bool = True       # False - игроков записывает только организатор
    max_players: int | None = Field(default=None, ge=2, le=512)
    league_id: int | None = None
    silent: bool = False                 # тестовый турнир без оповещений
    draft: bool = False                  # бустерный драфт перед турами (рассадка, таймеры пиков, сборка колоды)
    draft_config: dict | None = None     # настройки драфта (см. app/draft.py); пусто - по умолчанию для игры
    tier: Tier = "club"                  # уровень; региональный чемпионат и про-тур - только администратор


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
    silent: bool | None = None
    tier: Tier | None = None


class PlayerAdd(BaseModel):
    """Организатор добавляет игрока: по номеру игрока (player_no), существующего (user_id) или гостя по имени."""
    user_id: int | None = None
    player_no: int | None = Field(default=None, ge=1)
    nickname: str | None = Field(default=None, min_length=2, max_length=64)
    bracket: int = Field(default=2, ge=1, le=5)
    deck_id: int | None = None           # гостю (без аккаунта): деклист из колод самого организатора


class DropIn(BaseModel):
    dropped: bool = True


def _check_tier(tier: str | None, user: User) -> None:
    if tier in rating.ADMIN_TIERS and user.role != GlobalRole.admin:
        raise HTTPException(403, f"Уровень «{rating.TIERS[tier]}» назначает администратор сайта")


def _visitors_welcome(t: Tournament) -> bool:
    """Открытые турниры, региональные чемпионаты и про-туры: игроки других клубов и городов
    записываются по своему номеру и не вступают в клуб-организатор."""
    return (t.tier or "club") in rating.OPEN_TIERS


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=ZoneInfo(settings.app_timezone))


async def _check_league(session: AsyncSession, league_id: int | None, club_id: int, game: str, fmt,
                        starts_at: datetime | None = None) -> None:
    if league_id is None:
        return
    league = await session.get(League, league_id)
    if not league or league.club_id != club_id:
        raise HTTPException(400, "Сезон лиги не найден в этом клубе")
    if leagues.status(league, leagues.today()) == "finished":
        raise HTTPException(400, "Сезон лиги уже завершён")
    if not leagues.fits(league, game, fmt.value if hasattr(fmt, "value") else fmt):
        raise HTTPException(400, "Формат турнира не подходит этому сезону: EDH-сезон - только EDH, "
                                 "сезон «Берсерка» - швейцарки по «Берсерку»")
    if starts_at is not None:
        day = leagues.local(starts_at).date()
        if not league.starts_on <= day <= league.ends_on:
            raise HTTPException(400, f"Дата ивента {day:%d.%m.%Y} вне сезона «{league.name}» "
                                     f"({league.starts_on:%d.%m.%Y}–{league.ends_on:%d.%m.%Y})")


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


async def _require_judge(session: AsyncSession, t: Tournament, user: User):
    """Ведение турнира (участники, туры, результаты, завершение): организатор или судья клуба по этой игре."""
    if not await can_judge(session, t.club_id, t.game, t.format, user):
        raise HTTPException(403, "Нужны права организатора клуба или судьи клуба по этой игре")


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
    seating = None
    if t.draft and t.current_round == 0 and t.draft["config"].get("first_round") == "seats":
        rows = (await session.execute(select(TournamentPlayer.user_id, TournamentPlayer.pod, TournamentPlayer.seat)
                                      .where(TournamentPlayer.tournament_id == t.id,
                                             TournamentPlayer.seat.is_not(None)))).all()
        seating = [(u, p, st) for u, p, st in rows if active is None or u in active]
    in_play = set(active) if active is not None else set(players)
    if seating and {u for u, _, _ in seating} == in_play:
        pairs = draft_logic.first_round_pairs(seating)       # драфт: первый тур - с сидящим напротив
    else:
        pairs = pair_round(players, recs, active)
    t.round_started_at = datetime.now(timezone.utc)
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
    _check_tier(data.tier, user)
    await _check_league(session, data.league_id, data.club_id, data.game, data.format,
                        _aware(data.starts_at) if data.starts_at else None)
    t = _new_tournament(data, user, _aware(data.starts_at) if data.starts_at else datetime.now(timezone.utc))
    session.add(t)
    await session.flush()
    await notify.on_tournament_created(session, t)
    await session.commit()
    return {"id": t.id}


def _new_tournament(data: TournamentIn, user: User, starts_at: datetime, name: str | None = None) -> Tournament:
    rounds = None if data.format == TournamentFormat.edh else (
        data.rounds or (1 if data.format == TournamentFormat.fast_swiss else None))
    draft = None
    if data.draft:
        if data.format == TournamentFormat.edh:
            raise HTTPException(400, "Драфт проводится перед турами швейцарки, не для EDH")
        draft = {"config": draft_logic.clean_config(data.draft_config or {}, data.game), "state": {}}
    return Tournament(draft=draft, round_minutes=draft["config"]["round_minutes"] if draft else None,
                      club_id=data.club_id, name=(name or data.name).strip(), game=data.game, format=data.format,
                      rounds_total=rounds, created_by=user.id, description=data.description.strip(),
                      deck_policy=data.deck_policy, self_registration=data.self_registration,
                      max_players=data.max_players, league_id=data.league_id, starts_at=starts_at, announced=False,
                      silent=data.silent, tier=data.tier)


class SeriesIn(BaseModel):
    tournament: TournamentIn
    until: date                       # последний день серии (включительно)
    date_in_name: bool = True         # «Воскресный EDH 26.10» - чтобы турниры серии различались


@router.post("/series", status_code=201)
async def create_series(data: SeriesIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    """Еженедельная серия: тот же день недели и время, до даты until (не больше 26 турниров).
    Анонс в чат клуба уходит за неделю до каждого турнира, а не всеми сразу."""
    base = data.tournament
    if not await is_club_organizer(session, base.club_id, user):
        raise HTTPException(403, "Нужны права организатора клуба")
    if not base.starts_at:
        raise HTTPException(422, "Укажите дату и время первого турнира серии")
    first = _aware(base.starts_at)
    tz = ZoneInfo(settings.app_timezone)
    dates, d = [], first
    while d.astimezone(tz).date() <= data.until:
        dates.append(d)
        d = (d.astimezone(tz) + timedelta(days=7)).astimezone(timezone.utc)   # то же местное время, даже при смене часового пояса
    if not dates:
        raise HTTPException(400, "Дата окончания серии раньше первого турнира")
    if len(dates) > 26:
        raise HTTPException(400, f"Слишком длинная серия: {len(dates)} турниров, максимум 26 (полгода)")
    for when in dates:
        await _check_league(session, base.league_id, base.club_id, base.game, base.format, when)
    ids = []
    for when in dates:
        name = f"{base.name.strip()} {when.astimezone(tz):%d.%m}" if data.date_in_name else base.name
        t = _new_tournament(base, user, when, name)
        session.add(t)
        await session.flush()
        t.series_id = ids[0] if ids else t.id
        ids.append(t.id)
        await notify.on_tournament_created(session, t)
    await session.commit()
    return {"ids": ids, "count": len(ids), "first": dates[0], "last": dates[-1]}


def _t_out(t: Tournament, club: Club | None, players: int | None = None) -> dict:
    return {"id": t.id, "club_id": t.club_id, "club": club.name if club else None, "club_slug": club.slug if club else None,
            "name": t.name, "game": t.game, "format": t.format, "status": t.status, "round": t.current_round,
            "rounds_total": t.rounds_total, "starts_at": t.starts_at, "players": players,
            "league_id": t.league_id, "deck_policy": t.deck_policy, "self_registration": t.self_registration, "silent": t.silent,
            "draft": bool(t.draft), "draft_sets": (t.draft or {}).get("config", {}).get("sets") or None,
            "round_minutes": t.round_minutes, "round_started_at": t.round_started_at,
            "max_players": t.max_players, "tier": t.tier or "club", "rated": t.rated, "rating_note": t.rating_note}


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
    rows = (await session.execute(select(TournamentPlayer, User.nickname, User.is_guest, User.player_no)
                                  .join(User, User.id == TournamentPlayer.user_id)
                                  .where(TournamentPlayer.tournament_id == tid).order_by(User.nickname))).all()
    league = await session.get(League, t.league_id) if t.league_id else None
    judge = await session.get(User, t.judge_id) if t.judge_id else None
    wl = (await session.execute(select(WaitlistEntry.user_id, User.nickname, User.player_no)
                                .join(User, User.id == WaitlistEntry.user_id).where(WaitlistEntry.tournament_id == tid)
                                .order_by(WaitlistEntry.created_at, WaitlistEntry.id))).all() \
        if t.status == TournamentStatus.registration else []
    return {**_t_out(t, club, len(rows)), "description": t.description,
            "waitlist": [{"user_id": u, "nickname": n, "player_no": no, "position": i}
                         for i, (u, n, no) in enumerate(wl, 1)],
            "judge": {"user_id": judge.id, "nickname": judge.nickname, "player_no": judge.player_no} if judge else None,
            "league": {"id": league.id, "name": league.name, "kind": league.kind.value} if league else None,
            "participants": [{"user_id": tp.user_id, "nickname": nick, "guest": guest, "player_no": no,
                              "bracket": tp.bracket, "checked_in": tp.checked_in, "dropped": tp.dropped,
                              "has_deck": tp.deck_id is not None, "pod": tp.pod, "seat": tp.seat}
                             for tp, nick, guest, no in rows],
            "server_now": datetime.now(timezone.utc)}


@router.patch("/{tid}", status_code=204)
async def update_tournament(tid: int, data: TournamentPatch, user: User = Depends(current_user),
                            session: AsyncSession = Depends(get_session)):
    t = await _get(session, tid)
    await _require_org(session, t, user)
    if t.status != TournamentStatus.registration:
        raise HTTPException(400, "Настройки меняются только до старта")
    f = data.model_dump(exclude_unset=True)
    if "league_id" in f or f.get("starts_at"):
        league_id = f["league_id"] if "league_id" in f else t.league_id
        when = _aware(f["starts_at"]) if f.get("starts_at") else t.starts_at
        await _check_league(session, league_id, t.club_id, t.game, t.format, when)
        t.league_id = league_id
    if f.get("tier") and f["tier"] != t.tier:          # без изменения уровня права не проверяются
        _check_tier(f["tier"], user)
        if t.tier in rating.ADMIN_TIERS and user.role != GlobalRole.admin:
            raise HTTPException(403, "Уровень турнира назначил администратор: менять его может только он")
    for k in ("name", "description", "deck_policy", "self_registration", "max_players", "silent", "tier"):
        if k in f and (f[k] is not None or k == "max_players"):
            setattr(t, k, f[k].strip() if isinstance(f[k], str) and k in ("name", "description") else f[k])
    if "rounds" in f and t.format != TournamentFormat.edh:
        t.rounds_total = f["rounds"]
    if f.get("starts_at"):
        t.starts_at = _aware(f["starts_at"])
    await session.flush()
    await waitlist.promote(session, t)              # лимит подняли или сняли - записываем очередь
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
    await _require_judge(session, t, user)
    late_edh = t.format == TournamentFormat.edh and t.status == TournamentStatus.running   # опоздавший на EDH
    if t.status != TournamentStatus.registration and not late_edh:
        raise HTTPException(400, "Игроков можно добавлять только до старта")
    if t.max_players and await _count_players(session, tid) >= t.max_players:
        raise HTTPException(400, f"Достигнут лимит участников: {t.max_players}")
    if data.player_no:
        player = (await session.execute(select(User).where(User.player_no == data.player_no))).scalar_one_or_none()
        if not player:
            raise HTTPException(404, f"Игрока с номером {data.player_no} нет: проверьте номер в его кабинете")
    elif data.user_id:
        player = await session.get(User, data.user_id)
        if not player:
            raise HTTPException(404, "Игрок не найден")
    elif data.nickname and data.nickname.strip():
        nick = " ".join(data.nickname.split())
        player = (await session.execute(select(User).where(
            User.is_guest.is_(True), User.guest_club_id == t.club_id,
            func.lower(User.nickname) == nick.lower()))).scalars().first()
        if not player:
            # null(), а не None: на None ORM подставил бы номер из последовательности
            player = User(nickname=nick, is_guest=True, guest_club_id=t.club_id, player_no=null())
            session.add(player)
            await session.flush()
    else:
        raise HTTPException(422, "Укажите игрока или имя гостя")
    if (await session.execute(select(TournamentPlayer).where(
            TournamentPlayer.tournament_id == tid, TournamentPlayer.user_id == player.id))).scalar_one_or_none():
        raise HTTPException(409, f"{player.nickname} уже в списке")
    deck_id = None
    if data.deck_id is not None:
        if not player.is_guest:
            raise HTTPException(400, "Колоду организатора можно указать только гостю: игрок с аккаунтом подаёт свою")
        deck = await session.get(Deck, data.deck_id)
        if not deck or deck.user_id != user.id or deck.game != t.game:
            raise HTTPException(400, "Укажите свою колоду той же игры, что и турнир")
        deck_id = deck.id
    if player.is_guest or not _visitors_welcome(t):
        await _ensure_member(session, t.club_id, player.id)
    session.add(TournamentPlayer(tournament_id=tid, user_id=player.id, seed=random.randint(0, 10**9),
                                 bracket=data.bracket, checked_in=late_edh, deck_id=deck_id))
    await session.commit()
    return {"user_id": player.id, "nickname": player.nickname, "guest": player.is_guest,
            "player_no": None if player.is_guest else player.player_no}


class BulkAdd(BaseModel):
    user_ids: list[int] = Field(min_length=1, max_length=200)
    bracket: int = Field(default=2, ge=1, le=5)


@router.post("/{tid}/players/bulk")
async def add_players_bulk(tid: int, data: BulkAdd, user: User = Depends(current_user),
                           session: AsyncSession = Depends(get_session)):
    """Записать в турнир сразу несколько участников клуба (со страницы «Участники»).
    Уже записанные пропускаются; если мест не хватает - записываются первые по списку, остальные возвращаются."""
    t = await _get(session, tid)
    await _require_judge(session, t, user)
    late_edh = t.format == TournamentFormat.edh and t.status == TournamentStatus.running
    if t.status != TournamentStatus.registration and not late_edh:
        raise HTTPException(400, "Игроков можно добавлять только до старта")
    wanted = list(dict.fromkeys(data.user_ids))
    members = set((await session.execute(select(ClubMember.user_id).where(
        ClubMember.club_id == t.club_id, ClubMember.user_id.in_(wanted)))).scalars())
    already = set((await session.execute(select(TournamentPlayer.user_id).where(
        TournamentPlayer.tournament_id == tid))).scalars())
    room = None if not t.max_players else max(0, t.max_players - len(already))
    added, skipped, no_room = [], [], []
    for uid in wanted:
        if uid not in members or uid in already:
            skipped.append(uid)
        elif room is not None and len(added) >= room:
            no_room.append(uid)
        else:
            session.add(TournamentPlayer(tournament_id=tid, user_id=uid, seed=random.randint(0, 10**9),
                                         bracket=data.bracket, checked_in=late_edh))
            added.append(uid)
    await session.commit()
    return {"added": added, "skipped": skipped, "no_room": no_room}


@router.delete("/{tid}/players/{uid}", status_code=204)
async def remove_player(tid: int, uid: int, user: User = Depends(current_user),
                        session: AsyncSession = Depends(get_session)):
    t = await _get(session, tid)
    await _require_judge(session, t, user)
    if t.status != TournamentStatus.registration:
        raise HTTPException(400, "После старта игрока можно только снять с турнира (выбыл)")
    tp = (await session.execute(select(TournamentPlayer).where(
        TournamentPlayer.tournament_id == tid, TournamentPlayer.user_id == uid))).scalar_one_or_none()
    if tp:
        await session.delete(tp)
        await session.flush()
        await waitlist.promote(session, t)          # место освободилось - первому из очереди
        await session.commit()


@router.post("/{tid}/players/{uid}/drop", status_code=204)
async def drop_player(tid: int, uid: int, data: DropIn, user: User = Depends(current_user),
                      session: AsyncSession = Depends(get_session)):
    """Игрок выбыл: остаётся в таблице, но в следующих турах пар не получает (EDH - не садится за столы)."""
    t = await _get(session, tid)
    await _require_judge(session, t, user)
    if t.status != TournamentStatus.running:
        raise HTTPException(400, "Снять игрока можно только во время турнира")
    tp = (await session.execute(select(TournamentPlayer).where(
        TournamentPlayer.tournament_id == tid, TournamentPlayer.user_id == uid))).scalar_one_or_none()
    if not tp:
        raise HTTPException(404, "Игрок не в турнире")
    tp.dropped = data.dropped
    await session.commit()


class FullError(HTTPException):
    """Мест нет: можно встать в лист ожидания."""


async def self_register(session: AsyncSession, t: Tournament, user: User, bracket: int = 2,
                        deck_id: int | None = None) -> TournamentPlayer:
    """Самозапись (сайт и кнопка в Telegram), без коммита. Игрок сразу вступает в клуб."""
    if t.status != TournamentStatus.registration:
        raise HTTPException(400, "Регистрация закрыта")
    if not t.self_registration:
        raise HTTPException(403, "На этот турнир игроков записывает организатор")
    if user.is_banned:
        raise HTTPException(403, "Аккаунт заблокирован")
    exists = await session.execute(select(TournamentPlayer).where(
        TournamentPlayer.tournament_id == t.id, TournamentPlayer.user_id == user.id))
    if exists.scalar_one_or_none():
        raise HTTPException(409, "Вы уже зарегистрированы")
    if t.max_players and await _count_players(session, t.id) >= t.max_players:
        raise FullError(400, f"Мест нет: лимит {t.max_players} участников. Можно встать в лист ожидания")
    deck = None
    if deck_id is not None:
        deck = check_deck_for(await session.get(Deck, deck_id), t, user)
    if not _visitors_welcome(t):
        await _ensure_member(session, t.club_id, user.id)            # автовступление в клуб
    await session.execute(delete(WaitlistEntry).where(WaitlistEntry.tournament_id == t.id,
                                                      WaitlistEntry.user_id == user.id))
    tp = TournamentPlayer(tournament_id=t.id, user_id=user.id, seed=random.randint(0, 10**9), bracket=bracket,
                          deck_id=deck.id if deck else None)
    session.add(tp)
    return tp


async def self_unregister(session: AsyncSession, t: Tournament, user: User) -> bool:
    """Отмена своей записи до старта (без коммита); освободившееся место получает первый из листа ожидания."""
    if t.status != TournamentStatus.registration:
        raise HTTPException(400, "Турнир уже начался")
    tp = (await session.execute(select(TournamentPlayer).where(
        TournamentPlayer.tournament_id == t.id, TournamentPlayer.user_id == user.id))).scalar_one_or_none()
    if not tp:
        return False
    await session.delete(tp)
    await session.flush()
    await waitlist.promote(session, t)
    return True


async def join_waitlist(session: AsyncSession, t: Tournament, user: User, bracket: int = 2,
                        deck_id: int | None = None) -> int:
    """Встать в лист ожидания (без коммита). Возвращает место в очереди."""
    if t.status != TournamentStatus.registration:
        raise HTTPException(400, "Регистрация закрыта")
    if not t.self_registration:
        raise HTTPException(403, "На этот турнир игроков записывает организатор")
    if not t.max_players or await _count_players(session, t.id) < t.max_players:
        raise HTTPException(400, "Места ещё есть — просто запишитесь")
    if (await session.execute(select(TournamentPlayer.id).where(
            TournamentPlayer.tournament_id == t.id, TournamentPlayer.user_id == user.id))).first():
        raise HTTPException(409, "Вы уже записаны на турнир")
    pos = await waitlist.position(session, t.id, user.id)
    if pos:
        return pos
    deck = check_deck_for(await session.get(Deck, deck_id), t, user) if deck_id is not None else None
    session.add(WaitlistEntry(tournament_id=t.id, user_id=user.id, bracket=bracket, deck_id=deck.id if deck else None))
    await session.flush()
    return await waitlist.position(session, t.id, user.id)


@router.post("/{tid}/register", status_code=204)
async def register(tid: int, bracket: int = Query(2, ge=1, le=5), deck_id: int | None = Query(None),
                   user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    """Самозапись игрока. Сразу вступает в клуб (если ещё не участник); колоду из своего пула можно подать сразу."""
    await self_register(session, await _get(session, tid), user, bracket, deck_id)
    await session.commit()


@router.delete("/{tid}/register", status_code=204)
async def unregister(tid: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    if await self_unregister(session, await _get(session, tid), user):
        await session.commit()


@router.post("/{tid}/waitlist")
async def waitlist_join(tid: int, bracket: int = Query(2, ge=1, le=5), deck_id: int | None = Query(None),
                        user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    pos = await join_waitlist(session, await _get(session, tid), user, bracket, deck_id)
    await session.commit()
    return {"position": pos}


@router.delete("/{tid}/waitlist", status_code=204)
async def waitlist_leave(tid: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    await session.execute(delete(WaitlistEntry).where(WaitlistEntry.tournament_id == tid, WaitlistEntry.user_id == user.id))
    await session.commit()


@router.post("/{tid}/start")
async def start(tid: int, force: bool = Query(False), user: User = Depends(current_user),
                session: AsyncSession = Depends(get_session)):
    t = await _get(session, tid)
    await _require_judge(session, t, user)
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
    await _require_judge(session, t, user)
    if t.status != TournamentStatus.running:
        raise HTTPException(400, "Результаты вводятся, пока турнир идёт")
    # прошлый тур можно исправить (как в AetherHub): таблица пересчитается, уже сделанные пары не меняются
    if m.p2_user_id is None:
        raise HTTPException(400, "Это bye, результат не нужен")
    set_result(session, t, m, data.result, user)
    await session.commit()


def set_result(session: AsyncSession, t: Tournament, m: Match, result, user: User) -> None:
    """Записать результат матча; исправление уже введённого результата - в журнал."""
    before = getattr(m.result, "value", m.result)
    after = getattr(result, "value", result)
    if before is not None and before != after:
        session.add(ResultEdit(tournament_id=t.id, match_id=m.id, round_no=m.round_no, user_id=user.id,
                               before=before, after=after))
    m.result = MatchResult(after)


@router.get("/{tid}/edits")
async def result_edits(tid: int, session: AsyncSession = Depends(get_session)):
    """Журнал исправлений результатов: кто, когда, какой матч, было - стало."""
    await _get(session, tid)
    rows = (await session.execute(select(ResultEdit, Match).outerjoin(Match, Match.id == ResultEdit.match_id)
                                  .where(ResultEdit.tournament_id == tid).order_by(ResultEdit.id.desc()))).all()
    ids = {e.user_id for e, _ in rows} | {x for _, m in rows if m for x in (m.p1_user_id, m.p2_user_id)}
    ids.discard(None)
    names = dict((await session.execute(select(User.id, User.nickname).where(User.id.in_(ids)))).all()) if ids else {}
    return [{"round": e.round_no, "at": e.created_at, "by": names.get(e.user_id), "before": e.before, "after": e.after,
             "p1": names.get(m.p1_user_id) if m else None, "p2": names.get(m.p2_user_id) if m else None}
            for e, m in rows]


class JudgeIn(BaseModel):
    user_id: int | None = None


@router.put("/{tid}/judge", status_code=204)
async def set_judge(tid: int, data: JudgeIn, user: User = Depends(current_user),
                    session: AsyncSession = Depends(get_session)):
    """Главного судью назначает организатор: судья клуба по этой игре или организатор. null - снять."""
    t = await _get(session, tid)
    await _require_org(session, t, user)
    if data.user_id is not None:
        judge = await session.get(User, data.user_id)
        if not judge or judge.is_guest or not await can_judge(session, t.club_id, t.game, t.format, judge):
            raise HTTPException(400, "Главным судьёй может быть организатор или судья клуба по этой игре")
    t.judge_id = data.user_id
    await session.commit()


@router.post("/{tid}/next-round")
async def next_round(tid: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    t = await _get(session, tid)
    await _require_judge(session, t, user)
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
    await _require_judge(session, t, user)
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
    await rating.recompute(session)
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


# ---------- удаление турнира ----------
async def _revert_results(session: AsyncSession, t: Tournament) -> None:
    """Откатывает то, что турнир уже начислил: очки лиги и счётчик ивентов (швейцарка), банки EDH.
    Недельная надбавка EDH +150 не откатывается: она за посещение недели, а не за конкретный ивент."""
    if t.format != TournamentFormat.edh:
        if t.status != TournamentStatus.finished:
            return                                   # до завершения швейцарка ничего не начисляет
        players, _, recs = await _state(session, t)
        table = {r.player_id: r.points for r in compute_standings(players, recs)}
        for m in (await session.execute(select(ClubMember).where(
                ClubMember.club_id == t.club_id, ClubMember.user_id.in_(list(table))).with_for_update())).scalars():
            m.league_points = max(0, (m.league_points or 0) - table[m.user_id])
            m.events_played = max(0, (m.events_played or 0) - 1)
        return
    # EDH: банк двигается при закрытии каждого стола - возвращаем сумму изменений
    nets = dict((await session.execute(
        select(EdhSeat.user_id, func.sum(EdhSeat.delta)).join(EdhTable, EdhTable.id == EdhSeat.table_id)
        .where(EdhTable.tournament_id == t.id, EdhTable.status == EdhTableStatus.finished)
        .group_by(EdhSeat.user_id))).all())
    if nets:
        for uid, holder in (await leagues.bank_holders(session, t, list(nets), lock=True)).items():
            holder.edh_bank = round(holder.edh_bank - (nets[uid] or 0), 2)
    if t.status == TournamentStatus.finished:
        attended = (await session.execute(select(TournamentPlayer.user_id).where(
            TournamentPlayer.tournament_id == t.id, TournamentPlayer.checked_in.is_(True)))).scalars().all()
        if attended:
            for m in (await session.execute(select(ClubMember).where(
                    ClubMember.club_id == t.club_id, ClubMember.user_id.in_(attended)))).scalars():
                m.events_played = max(0, (m.events_played or 0) - 1)
            if t.league_id:
                for m in (await leagues.bank_holders(session, t, list(attended))).values():
                    m.events_played = max(0, (m.events_played or 0) - 1)


async def _remove_orphan_guests(session: AsyncSession, guest_ids: list[int]) -> int:
    """Гости без аккаунта, которые после удаления больше нигде не играли, удаляются вместе с турниром."""
    removed = 0
    for uid in guest_ids:
        played = (await session.execute(select(
            exists().where(TournamentPlayer.user_id == uid)
            | exists().where(EdhSeat.user_id == uid)
            | exists().where(or_(Match.p1_user_id == uid, Match.p2_user_id == uid))))).scalar()
        if played:
            continue
        try:
            async with session.begin_nested():
                await session.execute(delete(User).where(User.id == uid, User.is_guest.is_(True)))
            removed += 1
        except Exception:  # noqa: BLE001  гостя держит ещё что-то (колода и т.п.) - оставляем
            log.info("гость %s не удалён: на него есть ссылки", uid)
    return removed


@router.delete("/{tid}")
async def delete_tournament(tid: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    """Удаление турнира: организатор клуба или судья клуба по этой игре. Подтверждение - на стороне сайта.
    Начисленные турниром очки лиги и банки EDH откатываются, статистика клуба пересчитывается."""
    t = await _get(session, tid)
    await _require_judge(session, t, user)
    club_id, name = t.club_id, t.name
    await _revert_results(session, t)
    guest_ids = (await session.execute(select(User.id).join(TournamentPlayer, TournamentPlayer.user_id == User.id)
                                       .where(TournamentPlayer.tournament_id == tid, User.is_guest.is_(True)))).scalars().all()
    session.expunge(t)
    await session.execute(delete(Tournament).where(Tournament.id == tid))   # игроки, туры, столы - каскадом в БД
    await session.flush()
    guests_removed = await _remove_orphan_guests(session, list(guest_ids))
    await _recompute_club_stats(session, club_id)
    await rating.recompute(session)
    await session.commit()
    log.warning("турнир %s «%s» (клуб %s) удалён пользователем %s", tid, name, club_id, user.id)
    return {"deleted": tid, "guests_removed": guests_removed}
