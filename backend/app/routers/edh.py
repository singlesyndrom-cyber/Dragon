import asyncio
import random
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .. import edh, leagues, notify
from ..db import SessionLocal, get_session
from ..deps import current_user, is_club_organizer
from ..models import (ClubMember, EdhSeat, League, EdhTable, EdhTableStatus, Tournament,
                      TournamentFormat, TournamentPlayer, TournamentStatus, User)
from .tournaments import _recompute_club_stats

router = APIRouter(prefix="/edh", tags=["edh"])


class PlayerPatch(BaseModel):
    bracket: int | None = None
    checked_in: bool | None = None


class WinIn(BaseModel):
    winner_id: int
    force: bool = False  # победа зафиксирована вовремя, но внесена после таймера


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _edh(session: AsyncSession, tid: int) -> Tournament:
    t = await session.get(Tournament, tid)
    if not t or t.format != TournamentFormat.edh:
        raise HTTPException(404, "EDH-ивент не найден")
    return t


async def _require_org(session: AsyncSession, t: Tournament, user: User):
    if not await is_club_organizer(session, t.club_id, user):
        raise HTTPException(403, "Нужны права организатора клуба")


async def _tp(session: AsyncSession, tid: int, user_id: int) -> TournamentPlayer:
    res = await session.execute(select(TournamentPlayer).where(
        TournamentPlayer.tournament_id == tid, TournamentPlayer.user_id == user_id))
    tp = res.scalar_one_or_none()
    if not tp:
        raise HTTPException(404, "Игрок не зарегистрирован на ивент")
    return tp


# ---------- расчёт стола ----------
async def settle_table(session: AsyncSession, table_id: int, outcome: str, winner_id: int | None = None):
    """Закрывает стол и двигает банки. Строки блокируются, повторное закрытие невозможно."""
    table = (await session.execute(select(EdhTable).where(EdhTable.id == table_id)
                                   .with_for_update())).scalar_one_or_none()
    if not table:
        raise HTTPException(404, "Стол не найден")
    if table.status != EdhTableStatus.playing:
        raise HTTPException(409, "Стол уже закрыт")
    t = await session.get(Tournament, table.tournament_id)
    seats = (await session.execute(select(EdhSeat).where(EdhSeat.table_id == table.id))).scalars().all()
    members = await leagues.bank_holders(session, t, [s.user_id for s in seats], lock=True)  # банк сезона или клуба
    banks = {s.user_id: members[s.user_id].edh_bank for s in seats}
    if outcome == "win" and winner_id not in banks:
        raise HTTPException(400, "Победитель не сидит за этим столом")
    deltas = edh.settle(banks, winner_id if outcome == "win" else None)
    for s in seats:
        m = members[s.user_id]
        s.bank_before = m.edh_bank
        m.edh_bank = round(m.edh_bank + deltas[s.user_id], 2)
        s.bank_after, s.delta = m.edh_bank, deltas[s.user_id]
    table.status = EdhTableStatus.finished
    table.outcome = outcome
    table.winner_user_id = winner_id if outcome == "win" else None


async def expire_overdue_loop():
    """Фоновая задача: стол, у которого истёк таймер, закрывается как проигранный всеми."""
    while True:
        try:
            async with SessionLocal() as s:
                ids = (await s.execute(select(EdhTable.id).where(
                    EdhTable.status == EdhTableStatus.playing, EdhTable.ends_at < _now()))).scalars().all()
                for i in ids:
                    try:
                        await settle_table(s, i, "timeout")
                        await s.commit()
                    except Exception:
                        await s.rollback()
        except Exception:
            pass
        await asyncio.sleep(30)


# ---------- брекеты и отметка о приходе ----------
@router.patch("/{tid}/me/bracket", status_code=204)
async def set_my_bracket(tid: int, bracket: int = Query(ge=1, le=5), user: User = Depends(current_user),
                         session: AsyncSession = Depends(get_session)):
    t = await _edh(session, tid)
    if t.status != TournamentStatus.registration:
        raise HTTPException(400, "Брекет можно менять только до начала ивента")
    (await _tp(session, tid, user.id)).bracket = bracket
    await session.commit()


@router.put("/{tid}/players/{user_id}", status_code=204)
async def organizer_set_player(tid: int, user_id: int, data: PlayerPatch, user: User = Depends(current_user),
                               session: AsyncSession = Depends(get_session)):
    """Организатор: отметить приход и/или исправить брекет колоды после проверки."""
    t = await _edh(session, tid)
    await _require_org(session, t, user)
    if t.status == TournamentStatus.finished:
        raise HTTPException(400, "Ивент завершён")
    tp = await _tp(session, tid, user_id)
    if data.bracket is not None:
        if not 1 <= data.bracket <= 5:
            raise HTTPException(422, "Брекет от 1 до 5")
        tp.bracket = data.bracket
    if data.checked_in is not None:
        tp.checked_in = data.checked_in
    await session.commit()


# ---------- туры ----------
@router.post("/{tid}/round")
async def new_round(tid: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    """Новый тур: случайная рассадка пришедших внутри брекетов + недельная надбавка (раз в неделю)."""
    t = await _edh(session, tid)
    await _require_org(session, t, user)
    if t.status == TournamentStatus.finished:
        raise HTTPException(400, "Ивент завершён")
    open_tables = (await session.execute(select(func.count()).select_from(EdhTable).where(
        EdhTable.tournament_id == tid, EdhTable.status == EdhTableStatus.playing))).scalar_one()
    if open_tables:
        raise HTTPException(400, "Есть незавершённые столы")
    if t.rounds_total and t.current_round >= t.rounds_total:
        raise HTTPException(400, "Все туры сыграны, завершите ивент")

    if t.league_id:
        league = await session.get(League, t.league_id)
        if league and leagues.status(league, _now().date()) == "finished":
            raise HTTPException(400, "Сезон лиги завершён: новые туры в нём не проводятся")
    tps = (await session.execute(select(TournamentPlayer).where(
        TournamentPlayer.tournament_id == tid, TournamentPlayer.checked_in.is_(True),
        TournamentPlayer.dropped.is_(False)))).scalars().all()
    if len(tps) < 3:
        raise HTTPException(400, "Нужно минимум 3 пришедших игрока")

    members = await leagues.bank_holders(session, t, [p.user_id for p in tps])
    iso = _now().isocalendar()
    week = f"{iso.year}-W{iso.week:02d}"
    for tp in tps:
        m = members[tp.user_id]
        if m.last_bonus_week != week:                      # надбавка только пришедшим и зарегистрированным
            m.edh_bank = round((m.edh_bank or edh.START_BANK) + edh.WEEKLY_BONUS, 2)
            m.last_bonus_week = week
    await session.flush()

    layout = edh.seat([(p.user_id, p.bracket) for p in tps], random.Random())
    t.status = TournamentStatus.running
    t.current_round += 1
    start = _now()
    for n, (bracket, ids) in enumerate(layout, 1):
        tbl = EdhTable(tournament_id=tid, round_no=t.current_round, table_no=n, bracket=bracket,
                       started_at=start, ends_at=start + timedelta(minutes=edh.MATCH_MINUTES))
        tbl.seats = [EdhSeat(user_id=i, bank_before=members[i].edh_bank) for i in ids]
        session.add(tbl)
    await session.commit()
    return {"round": t.current_round, "tables": len(layout), "ends_at": (start + timedelta(minutes=edh.MATCH_MINUTES))}


@router.get("/{tid}/tables")
async def tables(tid: int, round_no: int | None = None, session: AsyncSession = Depends(get_session)):
    t = await _edh(session, tid)
    q = (select(EdhTable).where(EdhTable.tournament_id == tid)
         .options(selectinload(EdhTable.seats).selectinload(EdhSeat.user)).order_by(EdhTable.round_no, EdhTable.table_no))
    q = q.where(EdhTable.round_no == (round_no or t.current_round))
    now = _now()
    return [{"table_id": x.id, "table": x.table_no, "bracket": x.bracket, "status": x.status, "outcome": x.outcome,
             "seconds_left": max(0, int((x.ends_at - now).total_seconds())) if x.status == EdhTableStatus.playing else 0,
             "seats": [{"user_id": s.user_id, "nickname": s.user.nickname, "bank_before": s.bank_before,
                        "delta": s.delta, "bank_after": s.bank_after} for s in x.seats]}
            for x in (await session.execute(q)).scalars()]


async def _table_for_org(session: AsyncSession, table_id: int, user: User) -> EdhTable:
    table = await session.get(EdhTable, table_id)
    if not table:
        raise HTTPException(404, "Стол не найден")
    await _require_org(session, await session.get(Tournament, table.tournament_id), user)
    return table


@router.post("/tables/{table_id}/win", status_code=204)
async def table_win(table_id: int, data: WinIn, user: User = Depends(current_user),
                    session: AsyncSession = Depends(get_session)):
    table = await _table_for_org(session, table_id, user)
    if _now() > table.ends_at and not data.force:
        raise HTTPException(409, "Таймер истёк: по правилам партия проиграна всеми. "
                                 "Если победа была зафиксирована вовремя, повторите с force=true")
    await settle_table(session, table_id, "win", data.winner_id)
    await session.commit()


@router.post("/tables/{table_id}/draw", status_code=204)
async def table_draw(table_id: int, user: User = Depends(current_user),
                     session: AsyncSession = Depends(get_session)):
    await _table_for_org(session, table_id, user)
    await settle_table(session, table_id, "draw")
    await session.commit()


@router.post("/tables/{table_id}/timeout", status_code=204)
async def table_timeout(table_id: int, user: User = Depends(current_user),
                        session: AsyncSession = Depends(get_session)):
    table = await _table_for_org(session, table_id, user)
    if _now() < table.ends_at:
        raise HTTPException(400, "Таймер ещё не истёк")
    await settle_table(session, table_id, "timeout")
    await session.commit()


@router.get("/{tid}/results")
async def results(tid: int, session: AsyncSession = Depends(get_session)):
    """Итог ивента: прирост банка каждого игрока и его текущий банк."""
    t = await _edh(session, tid)
    rows = (await session.execute(
        select(EdhSeat.user_id, func.sum(EdhSeat.delta), func.count())
        .join(EdhTable, EdhTable.id == EdhSeat.table_id)
        .where(EdhTable.tournament_id == tid, EdhTable.status == EdhTableStatus.finished)
        .group_by(EdhSeat.user_id))).all()
    uids = [r[0] for r in rows]
    names = dict((await session.execute(select(User.id, User.nickname).where(User.id.in_(uids)))).all()) if uids else {}
    banks = {uid: m.edh_bank for uid, m in (await leagues.bank_holders(session, t, uids)).items()} if uids else {}
    out = [{"user_id": uid, "nickname": names.get(uid), "net": round(net or 0, 2), "games": g,
            "bank": banks.get(uid)} for uid, net, g in rows]
    return sorted(out, key=lambda r: -r["net"])


@router.post("/{tid}/finish")
async def finish(tid: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    t = await _edh(session, tid)
    await _require_org(session, t, user)
    if t.status != TournamentStatus.running:
        raise HTTPException(400, "Ивент не идёт")
    if (await session.execute(select(func.count()).select_from(EdhTable).where(
            EdhTable.tournament_id == tid, EdhTable.status == EdhTableStatus.playing))).scalar_one():
        raise HTTPException(400, "Есть незавершённые столы")
    attended = (await session.execute(select(TournamentPlayer.user_id).where(
        TournamentPlayer.tournament_id == tid, TournamentPlayer.checked_in.is_(True)))).scalars().all()
    for m in (await session.execute(select(ClubMember).where(
            ClubMember.club_id == t.club_id, ClubMember.user_id.in_(attended)))).scalars():
        m.events_played += 1                                   # активность в клубе
    if t.league_id and attended:
        for m in (await leagues.bank_holders(session, t, list(attended))).values():
            m.events_played += 1                               # ивенты в сезоне
    t.status = TournamentStatus.finished
    await session.flush()
    await _recompute_club_stats(session, t.club_id)
    await notify.on_tournament_finished(session, t)
    await session.commit()
    return {"ok": True}
