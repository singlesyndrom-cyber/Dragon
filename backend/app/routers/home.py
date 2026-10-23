"""Главная страница: расписание на неделю, мета месяца, сезон и клубы для выбранной игры;
для вошедшего - его турниры, колоды, место в сезоне и сводка клуба организатора."""
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import leagues as L
from ..bkmeta import archetype_key
from ..db import get_session
from ..deps import current_user
from ..meta import Entry, commander_stats
from ..models import (Club, ClubMember, ClubRole, Deck, DeckCard, League, LeagueKind, TableBooking, Tournament,
                      TournamentPlayer, TournamentStatus, User)
from .meta import load_scope
from .tournaments import _t_out

router = APIRouter(prefix="/home", tags=["home"])

GAME = "^(mtg|berserk)$"
LEAGUE_KIND = {"mtg": LeagueKind.edh, "berserk": LeagueKind.berserk}
META_TOP = 5


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _counts(session: AsyncSession, tids: list[int]) -> dict[int, int]:
    if not tids:
        return {}
    return dict((await session.execute(select(TournamentPlayer.tournament_id, func.count())
                                       .where(TournamentPlayer.tournament_id.in_(tids))
                                       .group_by(TournamentPlayer.tournament_id))).all())


async def week_events(session: AsyncSession, game: str, now: datetime) -> list[dict]:
    """Идущие турниры и открытые на ближайшие 7 дней (с запасом 6 часов назад: ивент мог задержаться)."""
    q = (select(Tournament, Club).join(Club, Club.id == Tournament.club_id)
         .where(Tournament.game == game, Tournament.silent.is_(False),
                or_(Tournament.status == TournamentStatus.running,
                    (Tournament.status == TournamentStatus.registration)
                    & (Tournament.starts_at >= now - timedelta(hours=6))
                    & (Tournament.starts_at < now + timedelta(days=7))))
         .order_by(Tournament.starts_at).limit(40))
    rows = (await session.execute(q)).all()
    n = await _counts(session, [t.id for t, _ in rows])
    out = [_t_out(t, c, n.get(t.id, 0)) for t, c in rows]
    return sorted(out, key=lambda r: (r["status"] != TournamentStatus.running, r["starts_at"]))


async def month_meta(session: AsyncSession, game: str) -> dict:
    """Топ архетипов по завершённым турнирам: за 30 дней, а если турниров не было - за 90.
    MTG: командир для EDH, иначе название колоды; «Берсерк» - название колоды (архетип)."""
    for days in (30, 90):
        entries, games = await load_scope(session, None, game, None, days)
        if entries:
            break
    if not entries:
        return {"since_days": 90, "decks": 0, "rows": []}
    names = dict((await session.execute(
        select(TournamentPlayer.id, Deck.name).join(Deck, Deck.id == TournamentPlayer.deck_id)
        .where(TournamentPlayer.id.in_([e.id for e in entries])))).all())
    shown: dict[str, Counter] = defaultdict(Counter)
    keyed = []
    for e in entries:
        label = e.commander or (names.get(e.id) or "").strip() or "(без названия)"
        key = archetype_key(label)
        shown[key][label] += 1
        keyed.append(Entry(e.id, key, {}))
    rows = commander_stats(keyed, games, 3)[:META_TOP]
    return {"since_days": days, "decks": len(entries),
            "rows": [{"name": shown[r["commander"]].most_common(1)[0][0], "decks": r["decks"], "share": r["pick_rate"],
                      "games": r["games"], "win_rate": r["win_rate"], "edge": r["edge"], "reliable": r["reliable"]}
                     for r in rows]}


async def _table(session: AsyncSession, league: League) -> list[dict]:
    """Строки сезона в одном виде: value - очки («Берсерк») или банк (EDH)."""
    if league.kind == LeagueKind.edh:
        rows = [r for r in await L.edh_table(session, league) if not r["guest"]]
        out = [{"user_id": r["user_id"], "nickname": r["nickname"], "value": r["bank"], "events": r["events"]} for r in rows]
    else:
        out = [{"user_id": r["user_id"], "nickname": r["nickname"], "value": r["points"], "events": r["events"]}
               for r in await L.berserk_table(session, league)]
    nos = dict((await session.execute(select(User.id, User.player_no)
                                      .where(User.id.in_([r["user_id"] for r in out])))).all()) if out else {}
    for i, r in enumerate(out):
        r["place"] = i + 1
        r["player_no"] = nos.get(r["user_id"])
    return out


async def _active_leagues(session: AsyncSession, game: str, club_ids: list[int] | None = None) -> list[tuple[League, Club]]:
    today = L.today()
    q = (select(League, Club).join(Club, Club.id == League.club_id)
         .where(League.kind == LEAGUE_KIND[game], League.closed.is_(False),
                League.starts_on <= today, League.ends_on >= today))
    if club_ids is not None:
        q = q.where(League.club_id.in_(club_ids))
    return list((await session.execute(q)).all())


def _season_out(league: League, club: Club, rows: list[dict], top: int = 5) -> dict:
    return {"id": league.id, "name": league.name, "kind": league.kind.value, "club": club.name, "club_slug": club.slug,
            "ends_on": league.ends_on, "players": len(rows), "rows": rows[:top]}


async def current_season(session: AsyncSession, game: str) -> dict | None:
    """Активный сезон игры с наибольшим числом турниров (на главной - один, самый живой)."""
    leagues = await _active_leagues(session, game)
    if not leagues:
        return None
    n = dict((await session.execute(select(Tournament.league_id, func.count())
                                    .where(Tournament.league_id.in_([lg.id for lg, _ in leagues]))
                                    .group_by(Tournament.league_id))).all())
    league, club = max(leagues, key=lambda p: (n.get(p[0].id, 0), -p[0].id))
    return _season_out(league, club, await _table(session, league))


async def clubs_with_next(session: AsyncSession, game: str, now: datetime, limit: int = 6) -> list[dict]:
    clubs = (await session.execute(select(Club).order_by(Club.name))).scalars().all()
    nxt = {}
    for t in (await session.execute(select(Tournament).where(
            Tournament.game == game, Tournament.silent.is_(False),
            or_(Tournament.status == TournamentStatus.running,
                (Tournament.status == TournamentStatus.registration) & (Tournament.starts_at >= now - timedelta(hours=6))))
            .order_by(Tournament.starts_at))).scalars():
        nxt.setdefault(t.club_id, t)
    games = defaultdict(set)
    for cid, g in (await session.execute(select(Tournament.club_id, Tournament.game).distinct())).all():
        games[cid].add(g)
    far = datetime.max.replace(tzinfo=timezone.utc)
    clubs = sorted(clubs, key=lambda c: (c.id not in nxt, nxt[c.id].starts_at if c.id in nxt else far, c.name))
    return [{"id": c.id, "name": c.name, "slug": c.slug, "city": c.city,
             "games": sorted(games[c.id]),
             "next": ({"id": nxt[c.id].id, "name": nxt[c.id].name, "starts_at": nxt[c.id].starts_at,
                       "status": nxt[c.id].status, "format": nxt[c.id].format, "draft": bool(nxt[c.id].draft)}
                      if c.id in nxt else None)} for c in clubs[:limit]]


@router.get("")
async def home(game: str = Query("mtg", pattern=GAME), session: AsyncSession = Depends(get_session)):
    now = _now()
    return {"game": game, "now": now, "events": await week_events(session, game, now),
            "meta": await month_meta(session, game), "season": await current_season(session, game),
            "clubs": await clubs_with_next(session, game, now)}


async def _organizer(session: AsyncSession, user: User, now: datetime) -> list[dict]:
    """Сводка по клубам, где пользователь организатор: турниры сегодня, недостающие колоды, брони."""
    clubs = (await session.execute(select(Club).join(ClubMember, ClubMember.club_id == Club.id).where(
        ClubMember.user_id == user.id, ClubMember.role == ClubRole.organizer).order_by(Club.name))).scalars().all()
    today = L.today()
    out = []
    for club in clubs[:5]:
        ts = (await session.execute(select(Tournament).where(
            Tournament.club_id == club.id,
            or_(Tournament.status == TournamentStatus.running,
                (Tournament.status == TournamentStatus.registration)
                & (Tournament.starts_at >= now - timedelta(hours=6)) & (Tournament.starts_at < now + timedelta(days=7))))
            .order_by(Tournament.starts_at))).scalars().all()
        n = await _counts(session, [t.id for t in ts])
        todays = [t for t in ts if t.status == TournamentStatus.running or L.local(t.starts_at).date() == today]
        need = [t.id for t in ts if t.status == TournamentStatus.registration and t.deck_policy == "required"]
        missing = (await session.execute(select(func.count()).select_from(TournamentPlayer).where(
            TournamentPlayer.tournament_id.in_(need), TournamentPlayer.deck_id.is_(None)))).scalar_one() if need else 0
        day0 = datetime.combine(today, datetime.min.time(), tzinfo=L.local(now).tzinfo)
        bookings = (await session.execute(select(func.count()).select_from(TableBooking).where(
            TableBooking.club_id == club.id, TableBooking.status == "active",
            TableBooking.starts_at >= day0, TableBooking.starts_at < day0 + timedelta(days=1)))).scalar_one()
        out.append({"id": club.id, "name": club.name, "slug": club.slug,
                    "today": [_t_out(t, club, n.get(t.id, 0)) for t in todays],
                    "today_players": sum(n.get(t.id, 0) for t in todays),
                    "week": len(ts), "missing_decks": missing, "bookings_today": bookings})
    return out


@router.get("/me")
async def home_me(game: str = Query("mtg", pattern=GAME), user: User = Depends(current_user),
                  session: AsyncSession = Depends(get_session)):
    now = _now()
    rows = (await session.execute(
        select(Tournament, Club, TournamentPlayer.deck_id, Deck.name)
        .join(TournamentPlayer, TournamentPlayer.tournament_id == Tournament.id)
        .join(Club, Club.id == Tournament.club_id)
        .outerjoin(Deck, Deck.id == TournamentPlayer.deck_id)
        .where(TournamentPlayer.user_id == user.id, Tournament.game == game,
               Tournament.status.in_([TournamentStatus.registration, TournamentStatus.running]))
        .order_by(Tournament.starts_at).limit(5))).all()
    mine = [{**_t_out(t, c), "deck_id": deck_id, "deck_name": deck_name} for t, c, deck_id, deck_name in rows]

    sizes = (select(DeckCard.deck_id, func.coalesce(func.sum(DeckCard.qty), 0).label("n"))
             .where(DeckCard.section != "side").group_by(DeckCard.deck_id).subquery())
    decks = [{"id": d.id, "name": d.name, "format": d.format, "cards": int(n or 0)}
             for d, n in (await session.execute(
                 select(Deck, sizes.c.n).outerjoin(sizes, sizes.c.deck_id == Deck.id)
                 .where(Deck.user_id == user.id, Deck.game == game)
                 .order_by(Deck.updated_at.desc()).limit(4))).all()]
    total_decks = (await session.execute(select(func.count()).select_from(Deck).where(
        Deck.user_id == user.id, Deck.game == game))).scalar_one()

    season = None
    my_clubs = (await session.execute(select(ClubMember.club_id).where(ClubMember.user_id == user.id))).scalars().all()
    for league, club in await _active_leagues(session, game, list(my_clubs)):
        table = await _table(session, league)
        me = next((r for r in table if r["user_id"] == user.id), None)
        if me:
            above = table[me["place"] - 2] if me["place"] > 1 else None
            season = {**_season_out(league, club, table, 0), "place": me["place"], "value": me["value"],
                      "events": me["events"], "gap": round(above["value"] - me["value"], 1) if above else None}
            break

    return {"game": game, "user": {"id": user.id, "nickname": user.nickname, "player_no": user.player_no},
            "tournaments": mine, "decks": decks, "decks_total": total_decks, "season": season,
            "organizer": await _organizer(session, user, now)}
