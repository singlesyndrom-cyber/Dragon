"""Рейтинг силы: таблицы по дисциплинам, городам и клубам, карточка игрока, город игрока,
управление рейтингом для администратора."""
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import rating as R
from ..db import get_session
from ..deps import current_user, require_admin
from ..models import Club, ClubMember, PlayerRating, RatingChange, Tournament, TournamentPlayer, TournamentStatus, User

router = APIRouter(prefix="/ratings", tags=["ratings"])

DISC = "^(" + "|".join(R.DISCIPLINES) + ")$"
TOP_CITY = 8          # город сравнивается по среднему рейтингу лучших игроков
MIN_CITY = 3          # меньше активных игроков - город в таблице, но без места


def city_key(city: str | None) -> str:
    return " ".join((city or "").replace("ё", "е").split()).casefold()


async def cities_of(session: AsyncSession, user_ids: list[int]) -> dict[int, str | None]:
    """Город игрока: указанный в профиле, иначе город клуба, где он сыграл больше всего завершённых
    клубных и городских турниров (выезды на открытые турниры и чемпионаты город не меняют),
    иначе город клуба, где он состоит."""
    if not user_ids:
        return {}
    own = dict((await session.execute(select(User.id, User.city).where(User.id.in_(user_ids)))).all())
    out = {u: (own.get(u) or "").strip() or None for u in user_ids}
    need = [u for u in user_ids if not out[u]]
    if need:
        rows = (await session.execute(
            select(TournamentPlayer.user_id, Club.city, func.count(), func.max(Tournament.starts_at))
            .join(Tournament, Tournament.id == TournamentPlayer.tournament_id).join(Club, Club.id == Tournament.club_id)
            .where(TournamentPlayer.user_id.in_(need), Club.city.is_not(None), Club.city != "",
                   Tournament.status == TournamentStatus.finished, Tournament.tier.in_(["club", "city"]))
            .group_by(TournamentPlayer.user_id, Club.city))).all()
        best: dict[int, tuple] = {}
        for uid, city, n, last in rows:
            if uid not in best or (n, last) > best[uid][:2]:
                best[uid] = (n, last, city.strip())
        for uid, (*_, city) in best.items():
            out[uid] = city
        rest = [u for u in need if not out[u]]
        if rest:
            for uid, city in (await session.execute(
                    select(ClubMember.user_id, Club.city).join(Club, Club.id == ClubMember.club_id)
                    .where(ClubMember.user_id.in_(rest), Club.city.is_not(None), Club.city != "")
                    .order_by(ClubMember.events_played.desc(), Club.id))).all():
                out[uid] = out[uid] or city.strip()
    return out


def _row(r: PlayerRating, user: User, city: str | None, now: datetime) -> dict:
    last = r.last_played if r.last_played.tzinfo else r.last_played.replace(tzinfo=timezone.utc)
    return {"user_id": user.id, "nickname": user.nickname, "player_no": user.player_no, "city": city,
            "rating": round(r.rating), "rd": round(R.current_rd(r, now)), "games": r.games, "wins": r.wins,
            "draws": r.draws, "losses": r.losses, "events": r.events, "peak": round(r.peak),
            "last_played": r.last_played, "provisional": r.games < R.PROVISIONAL_GAMES,
            "inactive": (now - last).days > R.INACTIVE_DAYS}


@router.get("/disciplines")
async def disciplines():
    return {"disciplines": [{"key": k, "name": v} for k, v in R.DISCIPLINES.items()],
            "tiers": [{"key": k, "name": v, "admin_only": k in R.ADMIN_TIERS} for k, v in R.TIERS.items()],
            "rules": {"min_players": R.MIN_PLAYERS, "pair_cap": R.PAIR_CAP, "pair_window_days": R.PAIR_WINDOW.days,
                      "provisional_games": R.PROVISIONAL_GAMES, "inactive_days": R.INACTIVE_DAYS}}


@router.get("")
async def table(discipline: str = Query("mtg_constructed", pattern=DISC), city: str | None = None,
                club_id: int | None = None, include_provisional: bool = False, include_inactive: bool = False,
                limit: int = Query(100, ge=1, le=500), session: AsyncSession = Depends(get_session)):
    """Таблица дисциплины: вся страна, город или участники клуба. По умолчанию без предварительных
    (меньше 10 партий) и без тех, кто не играл больше полугода."""
    q = (select(PlayerRating, User).join(User, User.id == PlayerRating.user_id)
         .where(PlayerRating.discipline == discipline, User.is_banned.is_(False)))
    if club_id:
        q = q.where(PlayerRating.user_id.in_(select(ClubMember.user_id).where(ClubMember.club_id == club_id)))
    rows = (await session.execute(q.order_by(PlayerRating.rating.desc()))).all()
    now = datetime.now(timezone.utc)
    cities = await cities_of(session, [u.id for _, u in rows])
    out = []
    for r, u in rows:
        row = _row(r, u, cities.get(u.id), now)
        if (row["provisional"] and not include_provisional) or (row["inactive"] and not include_inactive):
            continue
        if city and city_key(row["city"]) != city_key(city):
            continue
        out.append(row)
    for i, row in enumerate(out):
        row["place"] = i + 1
    return {"discipline": discipline, "name": R.DISCIPLINES[discipline], "city": city, "club_id": club_id,
            "total": len(out), "rows": out[:limit]}


@router.get("/cities")
async def cities(discipline: str = Query("mtg_constructed", pattern=DISC), session: AsyncSession = Depends(get_session)):
    """Сравнение городов: средний рейтинг 8 лучших активных игроков (не сумма - иначе большой город
    выигрывает числом). Плюс активность: игроки и турниры за 30 дней."""
    rows = (await session.execute(select(PlayerRating, User).join(User, User.id == PlayerRating.user_id)
                                  .where(PlayerRating.discipline == discipline, User.is_banned.is_(False)))).all()
    now = datetime.now(timezone.utc)
    cities_ = await cities_of(session, [u.id for _, u in rows])
    by_city: dict[str, list[dict]] = defaultdict(list)
    shown: dict[str, Counter] = defaultdict(Counter)
    for r, u in rows:
        row = _row(r, u, cities_.get(u.id), now)
        if row["provisional"] or row["inactive"] or not row["city"]:
            continue
        k = city_key(row["city"])
        shown[k][row["city"]] += 1
        by_city[k].append(row)
    month = now - timedelta(days=30)
    events = Counter()
    for t_city, n in (await session.execute(
            select(Club.city, func.count()).join(Tournament, Tournament.club_id == Club.id)
            .where(Tournament.starts_at >= month, Tournament.silent.is_(False), Club.city.is_not(None))
            .group_by(Club.city))).all():
        events[city_key(t_city)] += n
    out = []
    for k, players in by_city.items():
        players.sort(key=lambda r: -r["rating"])
        top = players[:TOP_CITY]
        out.append({"city": shown[k].most_common(1)[0][0], "players": len(players),
                    "top_avg": round(sum(p["rating"] for p in top) / len(top)), "top_n": len(top),
                    "ranked": len(players) >= MIN_CITY, "events_30d": events[k],
                    "best": {"nickname": top[0]["nickname"], "player_no": top[0]["player_no"], "rating": top[0]["rating"]}})
    out.sort(key=lambda c: (not c["ranked"], -c["top_avg"]))
    for i, c in enumerate(out):
        c["place"] = i + 1 if c["ranked"] else None
    return {"discipline": discipline, "name": R.DISCIPLINES[discipline], "top": TOP_CITY, "min_players": MIN_CITY,
            "cities": out}


@router.get("/player/{player_no}")
async def player(player_no: int, session: AsyncSession = Depends(get_session)):
    """Рейтинг игрока по всем дисциплинам: место в стране и городе, история по турнирам."""
    user = (await session.execute(select(User).where(User.player_no == player_no))).scalar_one_or_none()
    if not user:
        raise HTTPException(404, "Игрока с таким номером нет")
    city = (await cities_of(session, [user.id])).get(user.id)
    now = datetime.now(timezone.utc)
    mine = (await session.execute(select(PlayerRating).where(PlayerRating.user_id == user.id))).scalars().all()
    out = []
    for r in mine:
        row = _row(r, user, city, now)
        place = city_place = None
        if not row["provisional"] and not row["inactive"]:
            board = (await table(r.discipline, None, None, False, False, 500, session))["rows"]
            place = next((x["place"] for x in board if x["user_id"] == user.id), None)
            local = [x for x in board if city and city_key(x["city"]) == city_key(city)]
            city_place = next((i + 1 for i, x in enumerate(local) if x["user_id"] == user.id), None)
        hist = (await session.execute(
            select(RatingChange, Tournament.name).join(Tournament, Tournament.id == RatingChange.tournament_id)
            .where(RatingChange.user_id == user.id, RatingChange.discipline == r.discipline)
            .order_by(RatingChange.at, RatingChange.id))).all()
        out.append({**row, "discipline": r.discipline, "name": R.DISCIPLINES.get(r.discipline, r.discipline),
                    "place": place, "city_place": city_place,
                    "history": [{"tournament_id": c.tournament_id, "tournament": n, "at": c.at, "before": round(c.before),
                                 "after": round(c.after), "games": c.games, "ignored": c.ignored} for c, n in hist]})
    order = list(R.DISCIPLINES)
    out.sort(key=lambda x: order.index(x["discipline"]) if x["discipline"] in order else 99)
    return {"player_no": user.player_no, "nickname": user.nickname, "city": city, "city_own": bool((user.city or "").strip()),
            "provisional_games": R.PROVISIONAL_GAMES, "ratings": out}


class CityIn(BaseModel):
    city: str = Field(default="", max_length=64)


@router.put("/me/city")
async def set_city(data: CityIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    """Свой город для рейтинга. Пусто - город основного клуба."""
    user.city = " ".join(data.city.split()) or None
    await session.commit()
    return {"city": (await cities_of(session, [user.id])).get(user.id), "city_own": bool(user.city)}


@router.post("/recompute")
async def recompute(_: User = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    res = await R.recompute(session)
    await session.commit()
    return res


class RatedIn(BaseModel):
    rated: bool = True
    note: str = Field(default="", max_length=200)
    tier: Literal["club", "city", "open", "regional", "pro"] | None = None   # администратор может поправить уровень и после турнира


@router.put("/tournaments/{tid}")
async def set_rated(tid: int, data: RatedIn, _: User = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    """Исключить турнир из рейтинга (или вернуть). Причина видна в карточке турнира."""
    t = await session.get(Tournament, tid)
    if not t:
        raise HTTPException(404, "Турнир не найден")
    if not data.rated and not data.note.strip():
        raise HTTPException(422, "Укажите причину исключения")
    t.rated, t.rating_note = data.rated, data.note.strip() if not data.rated else ""
    if data.tier:
        t.tier = data.tier
    res = await R.recompute(session)
    await session.commit()
    return {"rated": t.rated, "note": t.rating_note, "tier": t.tier, **res}


@router.get("/tournaments/{tid}")
async def tournament_rating(tid: int, session: AsyncSession = Depends(get_session)):
    """Как турнир повлиял на рейтинг: изменения игроков и причина, если не учтён."""
    t = await session.get(Tournament, tid)
    if not t:
        raise HTTPException(404, "Турнир не найден")
    rows = (await session.execute(select(RatingChange, User.nickname, User.player_no)
                                  .join(User, User.id == RatingChange.user_id)
                                  .where(RatingChange.tournament_id == tid).order_by(RatingChange.after.desc()))).all()
    reason = None
    if not rows:
        if t.silent:
            reason = "тестовый турнир"
        elif not t.rated:
            reason = f"исключён администратором: {t.rating_note}" if t.rating_note else "исключён администратором"
        elif getattr(t.status, "value", t.status) != "finished":
            reason = "рейтинг считается после завершения турнира"
        else:
            reason = f"меньше {R.MIN_PLAYERS} игроков с аккаунтами и засчитанными партиями"
    return {"tournament_id": tid, "discipline": R.discipline(t.game, t.format, t.draft), "rated": t.rated,
            "tier": t.tier, "reason": reason,
            "changes": [{"user_id": c.user_id, "nickname": n, "player_no": no, "before": round(c.before),
                         "after": round(c.after), "delta": round(c.after - c.before), "games": c.games,
                         "ignored": c.ignored} for c, n, no in rows]}
