"""Рейтинг силы игроков: Glicko-2 по дисциплинам, с защитой от накрутки.

Один турнир - один рейтинговый период для его участников: все партии турнира считаются от рейтингов
на начало турнира. Пока игрок не играет, неуверенность (RD) растёт по неделям. Рейтинг каждый раз
пересчитывается целиком по истории (recompute): исправления, исключённые турниры и баны учитываются честно.

Защита от накрутки:
- только завершённые, не тестовые турниры, которые администратор не исключил из рейтинга;
- в турнире не меньше MIN_PLAYERS игроков с аккаунтами, у которых были партии;
- партии с гостями (без аккаунта), bye и партии заблокированных игроков не считаются;
- одна и та же пара за PAIR_WINDOW дней засчитывается не больше PAIR_CAP раз
  (кроме региональных чемпионатов и про-туров: их назначает только администратор);
- в таблицах рейтинга игрок появляется после PROVISIONAL_GAMES партий.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (EdhSeat, EdhTable, EdhTableStatus, Match, PlayerRating, RatingChange, Tournament,
                     TournamentFormat, TournamentPlayer, TournamentStatus, User)

START_RATING = 1500.0
START_RD = 350.0
START_VOL = 0.06
TAU = 0.5
SCALE = 173.7178
MIN_PLAYERS = 4
PAIR_CAP = 3
PAIR_WINDOW = timedelta(days=30)
PROVISIONAL_GAMES = 10
INACTIVE_DAYS = 180

DISCIPLINES: dict[str, str] = {
    "mtg_constructed": "Magic: констракт",
    "mtg_draft": "Magic: драфт",
    "mtg_edh": "Magic: EDH",
    "berserk_constructed": "Берсерк: констракт",
    "berserk_draft": "Берсерк: драфт",
}

TIERS: dict[str, str] = {
    "club": "Клубный", "city": "Городской", "open": "Открытый",
    "regional": "Региональный чемпионат", "pro": "Про-тур",
}
ADMIN_TIERS = {"regional", "pro"}           # назначает только администратор
OPEN_TIERS = {"open", "regional", "pro"}    # игроки из других городов записываются без вступления в клуб


def discipline(game: str, fmt, draft) -> str:
    fmt = getattr(fmt, "value", fmt)
    if game == "berserk":
        return "berserk_draft" if draft else "berserk_constructed"
    if fmt == TournamentFormat.edh.value:
        return "mtg_edh"
    return "mtg_draft" if draft else "mtg_constructed"


# ---------- Glicko-2 ----------

@dataclass
class Player:
    rating: float = START_RATING
    rd: float = START_RD
    vol: float = START_VOL
    games: int = 0
    wins: int = 0
    draws: int = 0
    losses: int = 0
    events: int = 0
    peak: float = 0.0                # лучший рейтинг после предварительных партий
    last: datetime | None = None


def idle_rd(rd: float, vol: float, weeks: float) -> float:
    """RD после `weeks` недель без игр: phi* = sqrt(phi^2 + n * sigma^2), не больше стартового."""
    if weeks <= 0:
        return rd
    phi = rd / SCALE
    return min(START_RD, math.sqrt(phi * phi + weeks * vol * vol) * SCALE)


def _g(phi: float) -> float:
    return 1 / math.sqrt(1 + 3 * phi * phi / math.pi ** 2)


def _e(mu: float, mu_j: float, phi_j: float) -> float:
    return 1 / (1 + math.exp(-_g(phi_j) * (mu - mu_j)))


def glicko2(rating: float, rd: float, vol: float, games: list[tuple[float, float, float]]) -> tuple[float, float, float]:
    """Один период. games: (рейтинг соперника, RD соперника, результат 1 / 0.5 / 0). Возвращает (рейтинг, RD, волатильность)."""
    mu, phi = (rating - START_RATING) / SCALE, rd / SCALE
    if not games:
        return rating, min(START_RD, math.sqrt(phi * phi + vol * vol) * SCALE), vol
    v_inv = 0.0
    delta_sum = 0.0
    for r_j, rd_j, s in games:
        mu_j, phi_j = (r_j - START_RATING) / SCALE, rd_j / SCALE
        e = _e(mu, mu_j, phi_j)
        g = _g(phi_j)
        v_inv += g * g * e * (1 - e)
        delta_sum += g * (s - e)
    v = 1 / v_inv
    delta = v * delta_sum
    # волатильность: итерация Illinois по Glickman (2013)
    a = math.log(vol * vol)

    def f(x: float) -> float:
        ex = math.exp(x)
        return ex * (delta * delta - phi * phi - v - ex) / (2 * (phi * phi + v + ex) ** 2) - (x - a) / TAU ** 2

    big_a = a
    if delta * delta > phi * phi + v:
        big_b = math.log(delta * delta - phi * phi - v)
    else:
        k = 1
        while f(a - k * TAU) < 0:
            k += 1
        big_b = a - k * TAU
    fa, fb = f(big_a), f(big_b)
    while abs(big_b - big_a) > 1e-6:
        c = big_a + (big_a - big_b) * fa / (fb - fa)
        fc = f(c)
        if fc * fb <= 0:
            big_a, fa = big_b, fb
        else:
            fa /= 2
        big_b, fb = c, fc
    new_vol = math.exp(big_a / 2)
    phi_star = math.sqrt(phi * phi + new_vol * new_vol)
    new_phi = 1 / math.sqrt(1 / (phi_star * phi_star) + 1 / v)
    new_mu = mu + new_phi * new_phi * delta_sum
    return new_mu * SCALE + START_RATING, min(START_RD, new_phi * SCALE), new_vol


# ---------- сбор партий ----------

@dataclass
class Event:
    id: int
    discipline: str
    at: datetime
    tier: str
    games: list[tuple[int, int, float]] = field(default_factory=list)   # (игрок A, игрок B, очки A)


async def load_events(session: AsyncSession) -> list[Event]:
    """Партии рейтинговых турниров по порядку дат. Гости, bye и заблокированные игроки отброшены."""
    ts = (await session.execute(select(Tournament).where(
        Tournament.status == TournamentStatus.finished, Tournament.silent.is_(False), Tournament.rated.is_(True))
        .order_by(Tournament.starts_at, Tournament.id))).scalars().all()
    if not ts:
        return []
    real = set((await session.execute(select(User.id).where(User.is_guest.is_(False), User.is_banned.is_(False))))
               .scalars().all())
    ids = [t.id for t in ts]
    matches = defaultdict(list)
    for m in (await session.execute(select(Match).where(Match.tournament_id.in_(ids), Match.p2_user_id.is_not(None),
                                                         Match.result.is_not(None)).order_by(Match.round_no, Match.id))).scalars():
        matches[m.tournament_id].append(m)
    tables = (await session.execute(select(EdhTable.id, EdhTable.tournament_id, EdhTable.outcome, EdhTable.winner_user_id)
                                    .where(EdhTable.tournament_id.in_(ids), EdhTable.status == EdhTableStatus.finished)
                                    .order_by(EdhTable.round_no, EdhTable.table_no))).all()
    seats = defaultdict(list)
    if tables:
        for table_id, uid in (await session.execute(select(EdhSeat.table_id, EdhSeat.user_id).where(
                EdhSeat.table_id.in_([x.id for x in tables])).order_by(EdhSeat.id))).all():
            seats[table_id].append(uid)
    edh = defaultdict(list)
    for x in tables:
        edh[x.tournament_id].append(x)

    out = []
    for t in ts:
        ev = Event(t.id, discipline(t.game, t.format, t.draft), t.starts_at, t.tier or "club")
        for m in matches[t.id]:
            a, b = m.p1_user_id, m.p2_user_id
            if a in real and b in real and a != b:
                ev.games.append((a, b, {"p1": 1.0, "p2": 0.0, "draw": 0.5}[m.result.value]))
        for x in edh[t.id]:
            users = [u for u in seats[x.id] if u in real]
            if x.outcome == "win" and x.winner_user_id in users:
                # победитель стола выиграл у каждого; проигравшие между собой не сравниваются
                ev.games += [(x.winner_user_id, u, 1.0) for u in users if u != x.winner_user_id]
            elif x.outcome in ("draw", "timeout"):
                ev.games += [(a, b, 0.5) for i, a in enumerate(users) for b in users[i + 1:]]
        out.append(ev)
    return out


# ---------- расчёт ----------

@dataclass
class Result:
    players: dict[tuple[int, str], Player]
    changes: list[dict]
    skipped: dict[int, str]          # турнир -> почему не учтён


def compute(events: list[Event]) -> Result:
    players: dict[tuple[int, str], Player] = defaultdict(Player)
    pair_seen: dict[tuple[str, int, int], list[datetime]] = defaultdict(list)
    changes, skipped = [], {}
    for ev in events:
        counted: list[tuple[int, int, float]] = []
        ignored: dict[int, int] = defaultdict(int)
        used: dict[tuple[str, int, int], int] = defaultdict(int)     # партии пары в этом турнире
        for a, b, s in ev.games:
            key = (ev.discipline, min(a, b), max(a, b))
            recent = sum(1 for d in pair_seen[key] if ev.at - d < PAIR_WINDOW) + used[key]
            if ev.tier not in ("regional", "pro") and recent >= PAIR_CAP:
                ignored[a] += 1
                ignored[b] += 1
                continue
            used[key] += 1
            counted.append((a, b, s))
        people = {u for a, b, _ in counted for u in (a, b)}
        if len(people) < MIN_PLAYERS:
            skipped[ev.id] = f"меньше {MIN_PLAYERS} игроков с аккаунтами и засчитанными партиями"
            continue                          # пары не тратят лимит, если турнир не учтён
        for key, n in used.items():
            pair_seen[key] = [d for d in pair_seen[key] if ev.at - d < PAIR_WINDOW] + [ev.at] * n
        # рейтинги на начало турнира (с ростом RD за недели без игр)
        pre: dict[int, tuple[float, float, float]] = {}
        for u in people:
            p = players[(u, ev.discipline)]
            weeks = (ev.at - p.last).total_seconds() / 604800 if p.last else 0
            pre[u] = (p.rating, idle_rd(p.rd, p.vol, weeks), p.vol)
        per: dict[int, list[tuple[float, float, float]]] = defaultdict(list)
        for a, b, s in counted:
            per[a].append((pre[b][0], pre[b][1], s))
            per[b].append((pre[a][0], pre[a][1], 1 - s))
        for u, games in per.items():
            p = players[(u, ev.discipline)]
            before = p.rating
            p.rating, p.rd, p.vol = glicko2(pre[u][0], pre[u][1], pre[u][2], games)
            p.games += len(games)
            p.wins += sum(1 for *_, s in games if s == 1)
            p.draws += sum(1 for *_, s in games if s == 0.5)
            p.losses += sum(1 for *_, s in games if s == 0)
            p.events += 1
            if p.games >= PROVISIONAL_GAMES:
                p.peak = max(p.peak, p.rating)
            p.last = ev.at
            changes.append({"tournament_id": ev.id, "user_id": u, "discipline": ev.discipline, "before": before,
                            "after": p.rating, "rd_after": p.rd, "games": len(games), "ignored": ignored.get(u, 0),
                            "at": ev.at})
    return Result(dict(players), changes, skipped)


async def recompute(session: AsyncSession) -> dict:
    """Полный пересчёт по истории (без коммита). Вызывается после завершения или удаления турнира,
    исключения турнира из рейтинга и блокировки игрока."""
    res = compute(await load_events(session))
    await session.execute(delete(RatingChange))
    await session.execute(delete(PlayerRating))
    for (uid, disc), p in res.players.items():
        if p.last is None:
            continue
        session.add(PlayerRating(user_id=uid, discipline=disc, rating=p.rating, rd=p.rd, volatility=p.vol,
                                 games=p.games, wins=p.wins, draws=p.draws, losses=p.losses, events=p.events,
                                 peak=p.peak or p.rating,
                                 last_played=p.last))
    for c in res.changes:
        session.add(RatingChange(**c))
    await session.flush()
    return {"players": len(res.players), "changes": len(res.changes), "skipped": res.skipped}


def current_rd(r: PlayerRating, now: datetime | None = None) -> float:
    """RD на сегодня: растёт, пока игрок не играет."""
    now = now or datetime.now(timezone.utc)
    last = r.last_played if r.last_played.tzinfo else r.last_played.replace(tzinfo=timezone.utc)
    return idle_rd(r.rd, r.volatility, (now - last).total_seconds() / 604800)
