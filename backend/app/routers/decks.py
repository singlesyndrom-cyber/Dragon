from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..cardimport import front_face, norm_name
from ..db import get_session
from ..decklist import ParsedCard, apply_commander, parse_decklist, validate_edh
from ..deps import current_user, is_club_organizer
from ..models import (Card, Deck, DeckCard, GlobalRole, Tournament, TournamentPlayer,
                      TournamentStatus, User)

router = APIRouter(prefix="/decks", tags=["decks"])

# Подсказка организатору по официальным брекетам: макс. число Game Changers.
# Правила брекетов обновляются Wizards - сверяйте значения с актуальными.
BRACKET_GC_LIMIT = {1: 0, 2: 0, 3: 3}


class DeckIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    game: str = "mtg"
    text: str = Field(min_length=1, max_length=20000)
    commander: str | None = None
    in_meta: bool = False


class DeckPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    in_meta: bool | None = None


async def _fill(session: AsyncSession, deck: Deck, data: DeckIn) -> dict:
    parsed, errors = parse_decklist(data.text)
    parsed = apply_commander(parsed, data.commander)
    if not parsed:
        raise HTTPException(400, "Не удалось разобрать ни одной карты")
    names = set()
    for c in parsed:
        names |= {norm_name(c.name), norm_name(front_face(c.name))}
    found = (await session.execute(select(Card).where(
        Card.game == deck.game,
        or_(Card.name_lower.in_(names), Card.name_front.in_(names), Card.name_ru_lower.in_(names),
            Card.name_ru_front.in_(names))))).scalars()
    by_full, by_front = {}, {}
    for card in found:
        by_full[card.name_lower] = card
        by_front.setdefault(card.name_front, card)
        if card.name_ru_lower:                      # деклист на русском: «1 Кольцо Сола»
            by_full.setdefault(card.name_ru_lower, card)
            by_front.setdefault(card.name_ru_front or norm_name(front_face(card.name_ru)), card)

    await session.execute(delete(DeckCard).where(DeckCard.deck_id == deck.id))
    unmatched = []
    for c in parsed:
        n = norm_name(c.name)
        card = by_full.get(n) or by_front.get(n) or by_front.get(norm_name(front_face(c.name)))
        if not card:
            unmatched.append(c.name)
        session.add(DeckCard(deck_id=deck.id, card_id=card.id if card else None,
                             name=card.name if card else c.name, qty=c.qty,
                             is_commander=c.is_commander, section=c.section))
    warnings = validate_edh(parsed) if deck.game == "mtg" else []
    if unmatched:
        warnings.append(f"Не найдено в базе карт: {len(unmatched)} шт.")
    return {"cards": sum(c.qty for c in parsed if c.section != "side"), "unmatched": unmatched,
            "unparsed_lines": errors, "warnings": warnings}


async def _locked(session: AsyncSession, deck_id: int) -> bool:
    """Колода заблокирована, если привязана к начавшемуся турниру."""
    n = (await session.execute(select(func.count()).select_from(TournamentPlayer)
         .join(Tournament, Tournament.id == TournamentPlayer.tournament_id)
         .where(TournamentPlayer.deck_id == deck_id, Tournament.status != TournamentStatus.registration))).scalar_one()
    return n > 0


async def _can_view(session: AsyncSession, deck: Deck, user: User) -> bool:
    if user.id == deck.user_id or user.role == GlobalRole.admin:
        return True
    clubs = (await session.execute(select(Tournament.club_id).join(
        TournamentPlayer, TournamentPlayer.tournament_id == Tournament.id)
        .where(TournamentPlayer.deck_id == deck.id))).scalars().all()
    return any([await is_club_organizer(session, c, user) for c in clubs])


@router.post("", status_code=201)
async def create_deck(data: DeckIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    deck = Deck(user_id=user.id, name=data.name, game=data.game, in_meta=data.in_meta)
    session.add(deck)
    await session.flush()
    report = await _fill(session, deck, data)
    await session.commit()
    return {"id": deck.id, **report}


@router.put("/{deck_id}")
async def replace_deck(deck_id: int, data: DeckIn, user: User = Depends(current_user),
                       session: AsyncSession = Depends(get_session)):
    deck = await session.get(Deck, deck_id)
    if not deck or deck.user_id != user.id:
        raise HTTPException(404, "Колода не найдена")
    if await _locked(session, deck_id):
        raise HTTPException(409, "Турнир уже начался: деклист изменить нельзя")
    deck.name, deck.game, deck.in_meta = data.name, data.game, data.in_meta
    report = await _fill(session, deck, data)
    await session.commit()
    return {"id": deck.id, **report}


@router.get("/mine")
async def my_decks(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    res = await session.execute(select(Deck).where(Deck.user_id == user.id).order_by(Deck.created_at.desc()))
    return [{"id": d.id, "name": d.name, "game": d.game, "in_meta": d.in_meta} for d in res.scalars()]


@router.patch("/{deck_id}")
async def patch_deck(deck_id: int, data: DeckPatch, user: User = Depends(current_user),
                     session: AsyncSession = Depends(get_session)):
    """Переименовать колоду или включить/выключить её учёт в мете - без перезаливки деклиста."""
    deck = await session.get(Deck, deck_id)
    if not deck or deck.user_id != user.id:
        raise HTTPException(404, "Колода не найдена")
    if data.name is not None:
        deck.name = data.name.strip()
    if data.in_meta is not None:
        deck.in_meta = data.in_meta
    await session.commit()
    return {"id": deck.id, "name": deck.name, "game": deck.game, "in_meta": deck.in_meta}


@router.get("/{deck_id}")
async def get_deck(deck_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    deck = await session.get(Deck, deck_id)
    if not deck or not await _can_view(session, deck, user):
        raise HTTPException(404, "Колода не найдена")
    rows = (await session.execute(select(DeckCard, Card.image_url).outerjoin(Card, Card.id == DeckCard.card_id)
                                  .where(DeckCard.deck_id == deck_id)
                                  .order_by(DeckCard.is_commander.desc(), DeckCard.name))).all()
    return {"id": deck.id, "name": deck.name, "game": deck.game, "in_meta": deck.in_meta,
            "cards": [{"name": c.name, "qty": c.qty, "section": c.section, "is_commander": c.is_commander,
                       "matched": c.card_id is not None, "image_url": img} for c, img in rows]}


@router.delete("/{deck_id}", status_code=204)
async def delete_deck(deck_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    deck = await session.get(Deck, deck_id)
    if not deck or deck.user_id != user.id:
        raise HTTPException(404, "Колода не найдена")
    if await _locked(session, deck_id):
        raise HTTPException(409, "Колода участвует в начавшемся турнире")
    await session.delete(deck)
    await session.commit()


def check_deck_for(deck: Deck | None, t: Tournament, user: User) -> Deck:
    """Колода игрока подходит турниру: своя, та же игра, турнир принимает деклисты и ещё не начался."""
    if not deck or deck.user_id != user.id:
        raise HTTPException(404, "Колода не найдена")
    if t.status != TournamentStatus.registration:
        raise HTTPException(400, "Деклист можно подать только до начала турнира")
    if t.deck_policy == "none":
        raise HTTPException(400, "На этот турнир деклисты не принимаются")
    if t.game != deck.game:
        raise HTTPException(400, f"Игра колоды ({deck.game}) не совпадает с игрой турнира ({t.game})")
    return deck


@router.put("/{deck_id}/attach/{tid}", status_code=204)
async def attach(deck_id: int, tid: int, user: User = Depends(current_user),
                 session: AsyncSession = Depends(get_session)):
    """Привязать колоду к своей заявке на турнир (до старта)."""
    t = await session.get(Tournament, tid)
    if not t:
        raise HTTPException(404, "Турнир не найден")
    check_deck_for(await session.get(Deck, deck_id), t, user)
    tp = (await session.execute(select(TournamentPlayer).where(
        TournamentPlayer.tournament_id == tid, TournamentPlayer.user_id == user.id))).scalar_one_or_none()
    if not tp:
        raise HTTPException(400, "Сначала зарегистрируйтесь на турнир")
    tp.deck_id = deck_id
    await session.commit()


@router.get("/tournament/{tid}")
async def tournament_decks(tid: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    """Организатору: деклисты участников, предупреждения и подсказки по брекету."""
    t = await session.get(Tournament, tid)
    if not t:
        raise HTTPException(404, "Турнир не найден")
    if not await is_club_organizer(session, t.club_id, user):
        raise HTTPException(403, "Нужны права организатора клуба")
    tps = (await session.execute(select(TournamentPlayer, User.nickname).join(User, User.id == TournamentPlayer.user_id)
                                 .where(TournamentPlayer.tournament_id == tid))).all()
    deck_ids = [tp.deck_id for tp, _ in tps if tp.deck_id]
    cards_by_deck: dict[int, list] = {}
    for dc, gc in (await session.execute(select(DeckCard, Card.is_game_changer)
                   .outerjoin(Card, Card.id == DeckCard.card_id).where(DeckCard.deck_id.in_(deck_ids)))).all():
        cards_by_deck.setdefault(dc.deck_id, []).append((dc, bool(gc)))
    out = []
    for tp, nick in tps:
        item = {"user_id": tp.user_id, "nickname": nick, "bracket": tp.bracket, "deck_id": tp.deck_id}
        if tp.deck_id:
            rows = cards_by_deck.get(tp.deck_id, [])
            parsed = [ParsedCard(dc.qty, dc.name, dc.section, dc.is_commander) for dc, _ in rows]
            gcs = sorted({dc.name for dc, gc in rows if gc})
            limit = BRACKET_GC_LIMIT.get(tp.bracket)
            item.update(
                commanders=[dc.name for dc, _ in rows if dc.is_commander],
                unmatched=sum(1 for dc, _ in rows if dc.card_id is None),
                game_changers=gcs,
                warnings=validate_edh(parsed) if t.game == "mtg" else [],
                bracket_hint=(f"Game Changers: {len(gcs)}, для брекета {tp.bracket} обычно не больше {limit}"
                              if limit is not None and len(gcs) > limit else None))
        else:
            item["warnings"] = ["Деклист не подан"]
        out.append(item)
    return out
