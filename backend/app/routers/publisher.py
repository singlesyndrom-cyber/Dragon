"""Кабинет издателя: статистика своих игр по всем клубам платформы.

Что видит издатель без согласия игроков: то, что и так публично или обезличено - число турниров и участников,
клубы, итоги турниров (они открыты на сайте всем), мету по завершённым турнирам и колодам «в мете» без имён.
Деклисты с ником - только игроков, давших отдельное согласие (User.publisher_consent).
"""
import csv
import io
from collections import defaultdict
from datetime import date, datetime, time, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import current_user, require_admin
from ..meta import card_usage, commander_stats
from ..models import (Club, Deck, DeckCard, EdhSeat, EdhTable, EdhTableStatus, GlobalRole, Publisher, Tournament,
                      TournamentFormat, TournamentPlayer, TournamentStatus, User)
from ..notify import site_url
from ..swiss import compute_standings
from .meta import load_scope

router = APIRouter(tags=["publisher"])
GAMES = {"mtg": "Magic: The Gathering", "berserk": "Берсерк"}


def _games(p: Publisher | None) -> list[str]:
    return [g for g in (p.games or "").split(",") if g in GAMES] if p else []


async def _publisher(session: AsyncSession, user: User) -> Publisher | None:
    return (await session.execute(select(Publisher).where(Publisher.user_id == user.id))).scalar_one_or_none()


async def _access(session: AsyncSession, user: User, game: str) -> None:
    if game not in GAMES:
        raise HTTPException(404, "Игра не найдена")
    if user.role == GlobalRole.admin:
        return
    if game not in _games(await _publisher(session, user)):
        raise HTTPException(403, "Статистика этой игры доступна её издателю")


def _range(frm: date | None, to: date | None) -> tuple[datetime | None, datetime | None]:
    a = datetime.combine(frm, time.min, tzinfo=timezone.utc) if frm else None
    b = datetime.combine(to, time.max, tzinfo=timezone.utc) if to else None
    return a, b


def _finished(game: str, frm: date | None, to: date | None):
    a, b = _range(frm, to)
    q = select(Tournament).where(Tournament.game == game, Tournament.status == TournamentStatus.finished)
    if a:
        q = q.where(Tournament.starts_at >= a)
    if b:
        q = q.where(Tournament.starts_at <= b)
    return q.order_by(Tournament.starts_at.desc())


async def places(session: AsyncSession, t: Tournament) -> list[int]:
    """Игроки турнира по местам: швейцарка - итоговая таблица, EDH - по итогу банка за вечер."""
    if t.format == TournamentFormat.edh:
        rows = (await session.execute(
            select(EdhSeat.user_id, func.sum(EdhSeat.delta)).join(EdhTable, EdhTable.id == EdhSeat.table_id)
            .where(EdhTable.tournament_id == t.id, EdhTable.status == EdhTableStatus.finished)
            .group_by(EdhSeat.user_id))).all()
        return [u for u, _ in sorted(rows, key=lambda r: -(r[1] or 0))]
    from .tournaments import _state
    players, _, recs = await _state(session, t)
    return [r.player_id for r in compute_standings(players, recs)]


async def _tournament_rows(session: AsyncSession, game: str, frm, to, limit: int | None = None) -> list[dict]:
    ts = (await session.execute(_finished(game, frm, to).limit(limit) if limit else _finished(game, frm, to))).scalars().all()
    if not ts:
        return []
    clubs = dict((await session.execute(select(Club.id, Club.name).where(Club.id.in_({t.club_id for t in ts})))).all())
    counts = dict((await session.execute(select(TournamentPlayer.tournament_id, func.count()).where(
        TournamentPlayer.tournament_id.in_([t.id for t in ts])).group_by(TournamentPlayer.tournament_id))).all())
    winners = {}
    for t in ts:
        order = await places(session, t)
        winners[t.id] = order[0] if order else None
    names = dict((await session.execute(select(User.id, User.nickname).where(
        User.id.in_([w for w in winners.values() if w])))).all())
    return [{"id": t.id, "date": t.starts_at, "club": clubs.get(t.club_id), "club_id": t.club_id, "name": t.name,
             "format": t.format.value, "participants": counts.get(t.id, 0),
             "winner": names.get(winners[t.id]), "url": site_url(f"/tournaments/{t.id}")} for t in ts]


# ---------- издатель ----------
@router.get("/publisher/me")
async def publisher_me(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    p = await _publisher(session, user)
    if not p and user.role != GlobalRole.admin:
        raise HTTPException(403, "Это кабинет издателя")
    games = list(GAMES) if user.role == GlobalRole.admin and not p else _games(p)
    return {"name": p.name if p else "Администратор", "games": [{"code": g, "title": GAMES[g]} for g in games]}


@router.get("/publisher/{game}/overview")
async def overview(game: str, frm: date | None = Query(None, alias="from"), to: date | None = None,
                   user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    await _access(session, user, game)
    sub = _finished(game, frm, to).with_only_columns(Tournament.id, Tournament.club_id, Tournament.starts_at,
                                                    Tournament.format).subquery()
    rows = (await session.execute(select(sub.c.id, sub.c.club_id, sub.c.starts_at, sub.c.format))).all()
    tp = (await session.execute(select(TournamentPlayer.tournament_id, TournamentPlayer.user_id).where(
        TournamentPlayer.tournament_id.in_([r.id for r in rows])))).all() if rows else []
    per_t = defaultdict(int)
    for tid, _ in tp:
        per_t[tid] += 1
    months: dict[str, dict] = {}
    for r in rows:
        m = months.setdefault(f"{r.starts_at:%Y-%m}", {"month": f"{r.starts_at:%Y-%m}", "tournaments": 0, "participants": 0})
        m["tournaments"] += 1
        m["participants"] += per_t[r.id]
    formats = defaultdict(int)
    for r in rows:
        formats[r.format.value if hasattr(r.format, "value") else r.format] += 1
    total = sum(per_t.values())
    return {"game": game, "title": GAMES[game], "tournaments": len(rows), "participations": total,
            "players": len({u for _, u in tp}), "clubs": len({r.club_id for r in rows}),
            "avg_participants": round(total / len(rows), 1) if rows else 0,
            "formats": dict(formats), "by_month": sorted(months.values(), key=lambda m: m["month"])}


@router.get("/publisher/{game}/clubs")
async def clubs(game: str, frm: date | None = Query(None, alias="from"), to: date | None = None,
                user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    await _access(session, user, game)
    return await _club_rows(session, game, frm, to)


async def _club_rows(session, game, frm, to) -> list[dict]:
    sub = _finished(game, frm, to).with_only_columns(Tournament.id, Tournament.club_id, Tournament.starts_at).subquery()
    rows = (await session.execute(
        select(Club.id, Club.name, Club.city, Club.slug, func.count(func.distinct(sub.c.id)),
               func.count(TournamentPlayer.id), func.count(func.distinct(TournamentPlayer.user_id)),
               func.max(sub.c.starts_at))
        .join(sub, sub.c.club_id == Club.id).outerjoin(TournamentPlayer, TournamentPlayer.tournament_id == sub.c.id)
        .group_by(Club.id).order_by(func.count(func.distinct(sub.c.id)).desc()))).all()
    return [{"id": i, "name": n, "city": c, "url": site_url(f"/clubs/{s}"), "tournaments": t, "participations": p,
             "players": u, "last": last} for i, n, c, s, t, p, u, last in rows]


@router.get("/publisher/{game}/tournaments")
async def tournaments(game: str, frm: date | None = Query(None, alias="from"), to: date | None = None,
                      limit: int = Query(200, ge=1, le=2000), user: User = Depends(current_user),
                      session: AsyncSession = Depends(get_session)):
    await _access(session, user, game)
    return await _tournament_rows(session, game, frm, to, limit)


@router.get("/publisher/{game}/meta")
async def meta(game: str, since_days: int = Query(90, ge=1, le=3650), user: User = Depends(current_user),
               session: AsyncSession = Depends(get_session)):
    """Мета без имён: колоды завершённых турниров (с винрейтами командиров) и колоды «в мете» игроков."""
    await _access(session, user, game)
    entries, games_ = await load_scope(session, None, game, None, since_days)
    from .meta import pool
    opt_in = await pool(game=game, club_id=None, commander=None, limit=40, session=session)
    return {"tournament_decks": len(entries),
            "commanders": commander_stats(entries, games_, 3)[:40] if game == "mtg" else [],
            "cards": card_usage(entries, None, 2, 60), "players_pool": opt_in}


async def _decklists(session, game, frm, to) -> list[dict]:
    """Деклисты с турниров - только игроков, согласившихся на передачу издателю."""
    ts = (await session.execute(_finished(game, frm, to))).scalars().all()
    if not ts:
        return []
    tps = (await session.execute(
        select(TournamentPlayer, User.nickname, User.player_no).join(User, User.id == TournamentPlayer.user_id)
        .where(TournamentPlayer.tournament_id.in_([t.id for t in ts]), TournamentPlayer.deck_id.is_not(None),
               User.publisher_consent.is_(True)))).all()
    if not tps:
        return []
    by_t = {t.id: t for t in ts}
    clubs = dict((await session.execute(select(Club.id, Club.name).where(Club.id.in_({t.club_id for t in ts})))).all())
    cards = defaultdict(list)
    for dc in (await session.execute(select(DeckCard).where(DeckCard.deck_id.in_({tp.deck_id for tp, _, _ in tps}))
                                     .order_by(DeckCard.section, DeckCard.name))).scalars():
        cards[dc.deck_id].append({"qty": dc.qty, "name": dc.name, "section": dc.section})
    decks = dict((await session.execute(select(Deck.id, Deck.name).where(Deck.id.in_({tp.deck_id for tp, _, _ in tps})))).all())
    place_cache: dict[int, list[int]] = {}
    out = []
    for tp, nick, no in tps:
        t = by_t[tp.tournament_id]
        if t.id not in place_cache:
            place_cache[t.id] = await places(session, t)
        order = place_cache[t.id]
        out.append({"date": t.starts_at, "club": clubs.get(t.club_id), "tournament": t.name, "tournament_id": t.id,
                    "format": t.format.value, "player": nick, "player_no": no,
                    "place": order.index(tp.user_id) + 1 if tp.user_id in order else None,
                    "deck": decks.get(tp.deck_id), "cards": cards.get(tp.deck_id, [])})
    return sorted(out, key=lambda d: (d["date"], d["tournament_id"], d["place"] or 999), reverse=False)


@router.get("/publisher/{game}/decklists")
async def decklists(game: str, frm: date | None = Query(None, alias="from"), to: date | None = None,
                    user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    await _access(session, user, game)
    rows = await _decklists(session, game, frm, to)
    consented = (await session.execute(select(func.count()).select_from(User).where(User.publisher_consent.is_(True)))).scalar_one()
    return {"consented_players": consented, "items": rows}


@router.get("/publisher/{game}/export/{kind}.csv")
async def export(game: str, kind: str, frm: date | None = Query(None, alias="from"), to: date | None = None,
                 user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    """CSV для Excel (UTF-8 с BOM, разделитель «;»): tournaments, clubs, decklists."""
    await _access(session, user, game)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    if kind == "tournaments":
        w.writerow(["Дата", "Клуб", "Турнир", "Формат", "Участников", "Победитель", "Ссылка"])
        for r in await _tournament_rows(session, game, frm, to):
            w.writerow([f"{r['date']:%Y-%m-%d}", r["club"], r["name"], r["format"], r["participants"], r["winner"] or "", r["url"] or ""])
    elif kind == "clubs":
        w.writerow(["Клуб", "Город", "Турниров", "Участий", "Игроков", "Последний турнир"])
        for r in await _club_rows(session, game, frm, to):
            w.writerow([r["name"], r["city"], r["tournaments"], r["participations"], r["players"],
                        f"{r['last']:%Y-%m-%d}" if r["last"] else ""])
    elif kind == "decklists":
        w.writerow(["Дата", "Клуб", "Турнир", "Формат", "Игрок", "Номер игрока", "Место", "Раздел", "Кол-во", "Карта"])
        for d in await _decklists(session, game, frm, to):
            for c in d["cards"]:
                w.writerow([f"{d['date']:%Y-%m-%d}", d["club"], d["tournament"], d["format"], d["player"], d["player_no"] or "",
                            d["place"] or "", c["section"], c["qty"], c["name"]])
    else:
        raise HTTPException(404, "Выгрузка: tournaments, clubs или decklists")
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{game}-{kind}.csv"'})


# ---------- согласие игрока ----------
class ConsentIn(BaseModel):
    enabled: bool


@router.put("/me/publisher-consent")
async def set_consent(data: ConsentIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    user.publisher_consent = data.enabled
    user.publisher_consent_at = datetime.now(timezone.utc) if data.enabled else None
    await session.commit()
    return {"publisher_consent": user.publisher_consent, "publisher_consent_at": user.publisher_consent_at}


# ---------- администратор: издатели ----------
class PublisherIn(BaseModel):
    player_no: int = Field(ge=1)
    name: str = Field(min_length=2, max_length=128)
    games: list[str] = Field(min_length=1)


@router.get("/admin/publishers")
async def list_publishers(admin: User = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(Publisher, User.nickname, User.player_no).join(User, User.id == Publisher.user_id)
                                  .order_by(Publisher.id))).all()
    return [{"id": p.id, "name": p.name, "games": _games(p), "nickname": n, "player_no": no} for p, n, no in rows]


@router.put("/admin/publishers")
async def put_publisher(data: PublisherIn, admin: User = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    """Назначить игрока издателем (или поменять название и игры)."""
    bad = [g for g in data.games if g not in GAMES]
    if bad:
        raise HTTPException(422, "Игры: " + ", ".join(GAMES))
    target = (await session.execute(select(User).where(User.player_no == data.player_no))).scalar_one_or_none()
    if not target:
        raise HTTPException(404, f"Игрока с номером {data.player_no} нет")
    p = await _publisher(session, target) or Publisher(user_id=target.id)
    p.name, p.games = data.name.strip(), ",".join(g for g in GAMES if g in data.games)
    session.add(p)
    await session.commit()
    return {"id": p.id, "name": p.name, "games": _games(p), "nickname": target.nickname, "player_no": target.player_no}


@router.delete("/admin/publishers/{pid}", status_code=204)
async def delete_publisher(pid: int, admin: User = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    p = await session.get(Publisher, pid)
    if not p:
        raise HTTPException(404, "Издатель не найден")
    await session.delete(p)
    await session.commit()
