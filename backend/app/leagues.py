"""Сезоны лиг: даты, статус, банк EDH сезона и таблицы.

EDH: у каждого участника сезона свой банк, на старте сезона 1000; турниры сезона двигают именно его.
     Недельная надбавка +150 начисляется раз в неделю в рамках сезона. Таблица - по банку.
Берсерк: таблица - сумма очков (3/1/0) всех завершённых турниров сезона.
"""
import calendar
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (ClubMember, League, LeagueKind, LeagueMember, Match, Tournament, TournamentPlayer,
                     TournamentStatus, User)
from .swiss import MatchRec, compute_standings

MONTH_CHOICES = (1, 2, 3)


def add_months(d: date, months: int) -> date:
    m = d.month - 1 + months
    y, m = d.year + m // 12, m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def season_end(start: date, months: int) -> date:
    """Последний день сезона: 1 октября + 1 месяц -> 31 октября."""
    return date.fromordinal(add_months(start, months).toordinal() - 1)


def status(league: League, today: date) -> str:
    if league.closed or today > league.ends_on:
        return "finished"
    if today < league.starts_on:
        return "upcoming"
    return "active"


def fits(league: League, t_game: str, t_format: str) -> bool:
    """Подходит ли турнир сезону: EDH-сезон - только EDH; сезон «Берсерка» - швейцарки по «Берсерку»."""
    if league.kind == LeagueKind.edh:
        return t_format == "edh"
    return t_game == "berserk" and t_format in ("swiss", "fast_swiss")


async def bank_holders(session: AsyncSession, t: Tournament, user_ids: list[int],
                       lock: bool = False) -> dict[int, ClubMember | LeagueMember]:
    """Где хранится банк EDH игроков этого турнира: в сезоне лиги или (без лиги) в клубе.
    Недостающие записи создаются (банк 1000)."""
    if t.league_id:
        q = select(LeagueMember).where(LeagueMember.league_id == t.league_id, LeagueMember.user_id.in_(user_ids))
        rows = {m.user_id: m for m in (await session.execute(q.with_for_update() if lock else q)).scalars()}
        for uid in user_ids:
            if uid not in rows:
                rows[uid] = LeagueMember(league_id=t.league_id, user_id=uid, edh_bank=1000.0, events_played=0)
                session.add(rows[uid])
    else:
        q = select(ClubMember).where(ClubMember.club_id == t.club_id, ClubMember.user_id.in_(user_ids))
        rows = {m.user_id: m for m in (await session.execute(q.with_for_update() if lock else q)).scalars()}
        for uid in user_ids:
            if uid not in rows:
                rows[uid] = ClubMember(club_id=t.club_id, user_id=uid, edh_bank=1000.0, events_played=0, league_points=0)
                session.add(rows[uid])
    if any(m.id is None for m in rows.values()):
        await session.flush()
    return rows


async def edh_table(session: AsyncSession, league: League) -> list[dict]:
    rows = (await session.execute(select(LeagueMember, User.nickname, User.is_guest)
                                  .join(User, User.id == LeagueMember.user_id)
                                  .where(LeagueMember.league_id == league.id)
                                  .order_by(LeagueMember.edh_bank.desc(), User.nickname))).all()
    return [{"user_id": m.user_id, "nickname": nick, "guest": guest, "bank": round(m.edh_bank, 1),
             "delta": round(m.edh_bank - 1000, 1), "events": m.events_played} for m, nick, guest in rows]


async def berserk_table(session: AsyncSession, league: League) -> list[dict]:
    """Сумма очков по завершённым турнирам сезона; при равенстве - больше побед, затем меньше турниров."""
    tids = (await session.execute(select(Tournament.id).where(
        Tournament.league_id == league.id, Tournament.status == TournamentStatus.finished))).scalars().all()
    total: dict[int, dict] = {}
    for tid in tids:
        players = {uid: (0.0, seed) for uid, seed in (await session.execute(
            select(TournamentPlayer.user_id, TournamentPlayer.seed).where(TournamentPlayer.tournament_id == tid))).all()}
        ms = (await session.execute(select(Match).where(Match.tournament_id == tid))).scalars().all()
        recs = [MatchRec(m.p1_user_id, m.p2_user_id, m.result.value if m.result else None) for m in ms]
        for r in compute_standings(players, recs):
            row = total.setdefault(r.player_id, {"points": 0, "wins": 0, "events": 0, "best": None})
            row["points"] += r.points
            row["wins"] += r.wins
            row["events"] += 1
            row["best"] = r.rank if row["best"] is None else min(row["best"], r.rank)
    if not total:
        return []
    users = dict((await session.execute(select(User.id, User.nickname).where(User.id.in_(list(total))))).all())
    out = [{"user_id": uid, "nickname": users.get(uid), **v} for uid, v in total.items()]
    return sorted(out, key=lambda r: (-r["points"], -r["wins"], r["events"], r["nickname"] or ""))


async def summary(session: AsyncSession, league: League, today: date) -> dict:
    n = (await session.execute(select(func.count()).select_from(Tournament).where(
        Tournament.league_id == league.id))).scalar_one()
    return {"id": league.id, "club_id": league.club_id, "name": league.name, "kind": league.kind.value,
            "months": league.months, "starts_on": league.starts_on, "ends_on": league.ends_on,
            "description": league.description, "status": status(league, today), "events": n}
