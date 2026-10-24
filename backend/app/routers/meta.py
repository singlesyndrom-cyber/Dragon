from collections import defaultdict
from datetime import datetime, timedelta, timezone
from itertools import batched

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..meta import Entry, Game, build_entry, card_usage, commander_stats
from ..models import (ClubMember, Deck, DeckCard, User, EdhSeat, EdhTable, EdhTableStatus, Match, Tournament, TournamentFormat,
                      TournamentPlayer, TournamentStatus)

router = APIRouter(prefix="/meta", tags=["meta"])


async def load_scope(session: AsyncSession, club_id: int | None, game: str | None,
                     fmt: TournamentFormat | None, since_days: int) -> tuple[list[Entry], list[Game]]:
    """Только ЗАВЕРШЁННЫЕ турниры; для EDH учитываются только пришедшие игроки."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
    q = (select(TournamentPlayer.id, TournamentPlayer.tournament_id, TournamentPlayer.user_id, TournamentPlayer.deck_id)
         .join(Tournament, Tournament.id == TournamentPlayer.tournament_id)
         .where(Tournament.status == TournamentStatus.finished, TournamentPlayer.deck_id.is_not(None),
                Tournament.starts_at >= cutoff,
                or_(Tournament.format != TournamentFormat.edh, TournamentPlayer.checked_in.is_(True))))
    if club_id:
        q = q.where(Tournament.club_id == club_id)
    if game:
        q = q.where(Tournament.game == game)
    if fmt:
        q = q.where(Tournament.format == fmt)
    ent = (await session.execute(q)).all()
    if not ent:
        return [], []

    rows_by_deck = defaultdict(list)
    for chunk in batched({r.deck_id for r in ent}, 5000):
        res = await session.execute(select(DeckCard.deck_id, DeckCard.name, DeckCard.is_commander, DeckCard.section)
                                    .where(DeckCard.deck_id.in_(chunk)))
        for d, name, is_c, sec in res.all():
            rows_by_deck[d].append((name, is_c, sec))
    entries = [build_entry(r.id, rows_by_deck.get(r.deck_id, [])) for r in ent]
    entry_of = {(r.tournament_id, r.user_id): r.id for r in ent}
    tids = {r.tournament_id for r in ent}

    games: list[Game] = []
    # швейцарка: bye и несыгранные матчи не считаются
    ms = (await session.execute(select(Match).where(Match.tournament_id.in_(tids), Match.p2_user_id.is_not(None),
                                                    Match.result.is_not(None)))).scalars()
    for m in ms:
        r = m.result.value
        e1, e2 = entry_of.get((m.tournament_id, m.p1_user_id)), entry_of.get((m.tournament_id, m.p2_user_id))
        if e1:
            games.append(Game(e1, {"p1": "win", "p2": "loss", "draw": "draw"}[r], 0.5))
        if e2:
            games.append(Game(e2, {"p1": "loss", "p2": "win", "draw": "draw"}[r], 0.5))
    # EDH: победа только у победителя; ничья и таймер - «draw» для всех, ожидание 1/число игроков
    tables = (await session.execute(select(EdhTable.id, EdhTable.tournament_id, EdhTable.winner_user_id, EdhTable.outcome)
                                    .where(EdhTable.tournament_id.in_(tids),
                                           EdhTable.status == EdhTableStatus.finished))).all()
    info = {t.id: t for t in tables}
    seats = defaultdict(list)
    for chunk in batched(list(info), 5000):
        for table_id, user_id in (await session.execute(
                select(EdhSeat.table_id, EdhSeat.user_id).where(EdhSeat.table_id.in_(chunk)))).all():
            seats[table_id].append(user_id)
    for table_id, users in seats.items():
        t = info[table_id]
        for uid in users:
            eid = entry_of.get((t.tournament_id, uid))
            if not eid:
                continue
            out = "win" if t.winner_user_id == uid else ("loss" if t.outcome == "win" else "draw")
            games.append(Game(eid, out, 1 / len(users)))
    return entries, games


def _scope(club_id, game, fmt, since_days):
    return {"club_id": club_id, "game": game, "format": fmt, "since_days": since_days, "finished_only": True}


@router.get("/commanders")
async def commanders(club_id: int | None = None, game: str | None = None, format: TournamentFormat | None = None,
                     since_days: int = Query(90, ge=1, le=3650), min_games: int = Query(5, ge=0),
                     limit: int = Query(50, ge=1, le=200), session: AsyncSession = Depends(get_session)):
    """Популярность командиров (pick_rate) и винрейты. `reliable=false` - мало партий для выводов.
    edge = винрейт минус ожидаемый (для стола из 4 игроков ожидание 25%)."""
    entries, games = await load_scope(session, club_id, game, format, since_days)
    return {"scope": _scope(club_id, game, format, since_days), "entries": len(entries),
            "commanders": commander_stats(entries, games, min_games)[:limit]}


@router.get("/cards")
async def staples(club_id: int | None = None, game: str | None = None, format: TournamentFormat | None = None,
                  since_days: int = Query(90, ge=1, le=3650), commander: str | None = None,
                  min_decks: int = Query(2, ge=1), limit: int = Query(50, ge=1, le=300),
                  session: AsyncSession = Depends(get_session)):
    """Мета-стейплы: в каком проценте колод встречается карта. Базовые земли и командиры не учитываются.
    С параметром commander - стейплы конкретного командира."""
    entries, _ = await load_scope(session, club_id, game, format, since_days)
    return {"scope": _scope(club_id, game, format, since_days), "commander": commander,
            **card_usage(entries, commander, min_decks, limit)}



@router.get("/pool")
async def pool(game: str = Query("mtg", pattern="^(mtg|berserk|response)$"), club_id: int | None = None,
               commander: str | None = None, limit: int = Query(40, ge=1, le=200),
               session: AsyncSession = Depends(get_session)):
    """«Популярное у игроков»: колоды из пулов, которые владельцы отметили «Учитывать в мете».
    Без имён и без винрейта (это не турнирные результаты) - только частота командиров и карт.
    С club_id - колоды участников этого клуба."""
    q = (select(Deck.id).join(User, User.id == Deck.user_id)
         .where(Deck.in_meta.is_(True), Deck.game == game, User.is_banned.is_(False)))
    if club_id:
        q = q.where(Deck.user_id.in_(select(ClubMember.user_id).where(ClubMember.club_id == club_id)))
    ids = (await session.execute(q)).scalars().all()
    rows_by_deck = defaultdict(list)
    for chunk in batched(ids, 5000):
        res = await session.execute(select(DeckCard.deck_id, DeckCard.name, DeckCard.is_commander, DeckCard.section)
                                    .where(DeckCard.deck_id.in_(chunk)))
        for d, name, is_c, sec in res.all():
            rows_by_deck[d].append((name, is_c, sec))
    entries = [build_entry(d, rows_by_deck.get(d, [])) for d in ids]
    cmd = [{"commander": c["commander"], "decks": c["decks"], "pick_rate": c["pick_rate"]}
           for c in commander_stats(entries, [], 0)] if game in ("mtg", "response") else []
    return {"game": game, "club_id": club_id, "decks": len(entries), "commanders": cmd[:limit],
            **card_usage(entries, commander, 1, limit)}


async def berserk_meta(session: AsyncSession, entries, games_, club_id: int | None = None) -> dict:
    """«Берсерк»: связки стихий, архетипы и профиль колод - по турнирам (с результатами)
    и по колодам «в мете» игроков (club_id - участники клуба)."""
    from .. import bkmeta
    deck_of = dict((await session.execute(select(TournamentPlayer.id, TournamentPlayer.deck_id)
                                          .where(TournamentPlayer.id.in_([e.id for e in entries])))).all()) if entries else {}
    prof = await bkmeta.deck_profiles(session, deck_of.values())
    tournaments = bkmeta.summarize({e: prof[d] for e, d in deck_of.items() if d in prof}, games_, 3)
    q = (select(Deck.id).join(User, User.id == Deck.user_id)
         .where(Deck.in_meta.is_(True), Deck.game == "berserk", User.is_banned.is_(False)))
    if club_id:
        q = q.where(Deck.user_id.in_(select(ClubMember.user_id).where(ClubMember.club_id == club_id)))
    pool_prof = await bkmeta.deck_profiles(session, (await session.execute(q)).scalars().all())
    return {"tournaments": tournaments, "pool": bkmeta.summarize(pool_prof, [], 0)}


@router.get("/berserk")
async def berserk(club_id: int | None = None, format: TournamentFormat | None = None,
                  since_days: int = Query(90, ge=1, le=3650), session: AsyncSession = Depends(get_session)):
    """Мета «Берсерка» для всех: связки стихий, архетипы, профиль колод, стейплы."""
    entries, games_ = await load_scope(session, club_id, "berserk", format, since_days)
    return {"scope": _scope(club_id, "berserk", format, since_days), "entries": len(entries),
            **await berserk_meta(session, entries, games_, club_id), "cards": card_usage(entries, None, 2, 40)}
