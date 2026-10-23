import re
import secrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..cardimport import front_face, norm_name
from .. import deckrules
from ..db import get_session
from ..decklist import ParsedCard, apply_commander, parse_decklist, resolve_tail, validate_edh
from ..deps import current_user, is_club_organizer, optional_user
from .cards import _back, bk_fields
from ..models import (Card, CardPrint, Deck, DeckCard, GlobalRole, Tournament, TournamentPlayer,
                      TournamentStatus, User)

router = APIRouter(prefix="/decks", tags=["decks"])

# Подсказка организатору по официальным брекетам: макс. число Game Changers.
# Правила брекетов обновляются Wizards - сверяйте значения с актуальными.
BRACKET_GC_LIMIT = {1: 0, 2: 0, 3: 3}


VISIBILITY = ("private", "link", "public")


class DeckIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    game: str = "mtg"
    text: str = Field(default="", max_length=20000)     # пусто - новая пустая колода для конструктора
    commander: str | None = None
    in_meta: bool | None = None
    format: str | None = None
    visibility: str | None = None


class DeckPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    in_meta: bool | None = None
    format: str | None = None
    visibility: str | None = None


class CardRow(BaseModel):
    card_id: int | None = None
    name: str | None = Field(default=None, max_length=255)   # для карт, которых нет в базе
    qty: int = Field(ge=1, le=250)
    section: str = "main"
    print_id: int | None = None          # выбранное издание карты


class CardsIn(BaseModel):
    cards: list[CardRow] = Field(max_length=400)


def _settings(deck: Deck, fmt: str | None, visibility: str | None):
    if fmt is not None:
        if fmt not in deckrules.FORMATS:
            raise HTTPException(400, "Неизвестный формат")
        if deckrules.FORMATS[fmt].get("game", "mtg") != deck.game and fmt != "casual":
            raise HTTPException(400, "Формат другой игры")
        deck.format = fmt
    if visibility is not None:
        if visibility not in VISIBILITY:
            raise HTTPException(400, "Видимость: private, link или public")
        deck.visibility = visibility
        if visibility == "link" and not deck.share_key:
            deck.share_key = secrets.token_urlsafe(12)


NXT_LINE = re.compile(r"^\s*(\d{1,3})\s+(\d{5,6})\s*$")


async def nxt_to_text(session: AsyncSession, text: str) -> str | None:
    """Формат NXT «Берсерка» (выгрузка ProBerserk, клиенты): «3 60161» = 3 копии карты №161 выпуска 6.
    Код = выпуск × 10000 + номер. Возвращает обычный список «3 Название» или None, если это не NXT."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines or not all(NXT_LINE.match(ln) for ln in lines):
        return None
    codes = [(int(m.group(1)), int(m.group(2))) for m in map(NXT_LINE.match, lines)]
    want = {(str(c // 10000), str(c % 10000)) for _, c in codes}
    found = {}
    for card in (await session.execute(select(Card).where(
            Card.game == "berserk", Card.set_code.in_({s for s, _ in want})))).scalars():
        num = str((card.extra or {}).get("number") or "").lstrip("0")
        found.setdefault((card.set_code, num), card.name)
    out = []
    for qty, c in codes:
        name = found.get((str(c // 10000), str(c % 10000)))
        out.append(f"{qty} {name}" if name else f"{qty} Код {c}")      # неизвестный код - в «не найдено»
    return "\n".join(out)


async def _fill(session: AsyncSession, deck: Deck, data: DeckIn) -> dict:
    if deck.game == "berserk":
        data.text = await nxt_to_text(session, data.text) or data.text
    parsed, errors = parse_decklist(data.text)
    parsed = apply_commander(parsed, data.commander)
    if not parsed and data.text.strip():
        raise HTTPException(400, "Не удалось разобрать ни одной карты")
    names = set()
    for c in parsed:
        names |= {norm_name(c.name), norm_name(front_face(c.name))}
    found = (await session.execute(select(Card).where(
        Card.game == deck.game,
        or_(Card.name_lower.in_(names), Card.name_front.in_(names), Card.name_ru_lower.in_(names),
            Card.name_ru_front.in_(names))))).scalars() if names else []
    by_full, by_front = {}, {}
    for card in found:
        by_full[card.name_lower] = card
        by_front.setdefault(card.name_front, card)
        if card.name_ru_lower:                      # деклист на русском: «1 Кольцо Сола»
            by_full.setdefault(card.name_ru_lower, card)
            by_front.setdefault(card.name_ru_front or norm_name(front_face(card.name_ru)), card)

    def lookup(name: str):
        n = norm_name(name)
        return by_full.get(n) or by_front.get(n) or by_front.get(norm_name(front_face(name)))

    # экспорт Moxfield/MTGO без заголовков: командир (или сайдборд) - последним блоком после пустой строки
    parsed = resolve_tail(parsed, deck.format in ("commander", "duel", "brawl"),
                          lambda name: (card := lookup(name)) is not None and deckrules.can_be_commander(card, deck.format))

    # издания из строк «1 Sol Ring (CMM) 410»: точное по номеру, иначе первое в этом сете
    wanted = {(card.id, c.set_code) for c in parsed if c.set_code and (card := lookup(c.name))}
    prints: dict[tuple, CardPrint] = {}
    if wanted:
        for p in (await session.execute(select(CardPrint).where(
                CardPrint.card_id.in_({cid for cid, _ in wanted}), CardPrint.set_code.in_({sc for _, sc in wanted}))
                .order_by(CardPrint.collector_number))).scalars():
            prints.setdefault((p.card_id, p.set_code, (p.collector_number or "").lower()), p)
            prints.setdefault((p.card_id, p.set_code, None), p)

    await session.execute(delete(DeckCard).where(DeckCard.deck_id == deck.id))
    unmatched = []
    merged: dict[tuple, DeckCard] = {}              # одна строка на карту в разделе, даже если в тексте повторы
    for c in parsed:
        card = lookup(c.name)
        if not card:
            unmatched.append(c.name)
        key = (card.id if card else c.name.lower(), c.section)
        if key in merged:
            merged[key].qty += c.qty
            continue
        pr = None
        if card and c.set_code:
            pr = prints.get((card.id, c.set_code, (c.number or "").lower())) or prints.get((card.id, c.set_code, None))
        merged[key] = DeckCard(deck_id=deck.id, card_id=card.id if card else None,
                               name=card.name if card else c.name, qty=c.qty,
                               is_commander=c.is_commander, section=c.section, print_id=pr.id if pr else None)
        session.add(merged[key])
    deck.updated_at = func.now()
    warnings = validate_edh(parsed) if deck.game == "mtg" and deck.format in ("commander", "duel", "brawl") and parsed else []
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


async def _can_view(session: AsyncSession, deck: Deck, user: User | None, key: str | None = None) -> bool:
    if deck.visibility == "public" or (deck.visibility == "link" and key and key == deck.share_key):
        return True
    if user is None:
        return False
    if user.id == deck.user_id or user.role == GlobalRole.admin:
        return True
    clubs = (await session.execute(select(Tournament.club_id).join(
        TournamentPlayer, TournamentPlayer.tournament_id == Tournament.id)
        .where(TournamentPlayer.deck_id == deck.id))).scalars().all()
    return any([await is_club_organizer(session, c, user) for c in clubs])


async def _own(session: AsyncSession, deck_id: int, user: User, edit: bool = False) -> Deck:
    deck = await session.get(Deck, deck_id)
    if not deck or deck.user_id != user.id:
        raise HTTPException(404, "Колода не найдена")
    if edit and await _locked(session, deck_id):
        raise HTTPException(409, "Турнир уже начался: деклист изменить нельзя")
    return deck


def card_info(c: Card | None, p: CardPrint | None = None) -> dict | None:
    if c is None:
        return None
    ex = c.extra or {}
    info = {"id": c.id, "name": c.name, "name_ru": c.name_ru, "type": c.type_line, "type_ru": c.type_ru,
            "mana_cost": c.mana_cost, "cmc": c.cmc, "colors": ex.get("colors") or [],
            "color_identity": ex.get("color_identity") or [], "rarity": c.rarity, "set": c.set_code,
            "image_url": c.image_url, "image_large": ex.get("image_large"), "prices": c.prices or {},
            "legalities": c.legalities or {}, "is_game_changer": c.is_game_changer,
            "back_image": _back(ex), "print": None,
            **({"bk": bk_fields(ex), "text": c.text} if c.game == "berserk" else {})}
    if p is not None:                          # выбранное издание: его картинка, сет и цена
        if p.image_url:
            info.update(image_url=p.image_url, image_large=p.image_large or ex.get("image_large"), back_image=p.back_image)
        info.update(set=p.set_code, prices=p.prices or info["prices"], rarity=p.rarity or c.rarity,
                    print={"id": p.id, "set": p.set_code, "set_name": p.set_name, "number": p.collector_number})
    return info


async def _entries(session: AsyncSession, deck_id: int) -> list[tuple[DeckCard, Card | None, CardPrint | None]]:
    return (await session.execute(select(DeckCard, Card, CardPrint).outerjoin(Card, Card.id == DeckCard.card_id)
                                  .outerjoin(CardPrint, CardPrint.id == DeckCard.print_id)
                                  .where(DeckCard.deck_id == deck_id).order_by(DeckCard.name))).all()


def _problems(deck: Deck, rows) -> list[dict]:
    if deck.game != "mtg" and deckrules.FORMATS.get(deck.format, {}).get("game") != deck.game:
        return []
    return deckrules.check([deckrules.Entry(dc.name, dc.qty, dc.section, card) for dc, card, _ in rows], deck.format)


async def _detail(session: AsyncSession, deck: Deck, user: User | None) -> dict:
    rows = await _entries(session, deck.id)
    owner = await session.get(User, deck.user_id)
    mine = user is not None and user.id == deck.user_id
    return {"id": deck.id, "name": deck.name, "game": deck.game, "format": deck.format, "in_meta": deck.in_meta,
            "visibility": deck.visibility, "share_key": deck.share_key if mine else None,
            "owner": {"nickname": owner.nickname, "player_no": owner.player_no} if owner else None,
            "editable": mine, "locked": mine and await _locked(session, deck.id),
            "updated_at": deck.updated_at,
            "cards": [{"name": dc.name, "qty": dc.qty, "section": dc.section, "is_commander": dc.is_commander,
                       "matched": dc.card_id is not None,
                       "image_url": (pr.image_url if pr and pr.image_url else card.image_url) if card else None,
                       "card": card_info(card, pr)} for dc, card, pr in rows],
            "problems": _problems(deck, rows)}


@router.post("", status_code=201)
async def create_deck(data: DeckIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    deck = Deck(user_id=user.id, name=data.name.strip(), game=data.game, in_meta=bool(data.in_meta),
                format="commander" if data.game == "mtg" else deckrules.GAME_FORMATS.get(data.game, "casual"))
    _settings(deck, data.format, data.visibility)
    session.add(deck)
    await session.flush()
    report = await _fill(session, deck, data)
    await session.commit()
    return {"id": deck.id, **report}


@router.put("/{deck_id}")
async def replace_deck(deck_id: int, data: DeckIn, user: User = Depends(current_user),
                       session: AsyncSession = Depends(get_session)):
    """Импорт: заменить список колоды текстом."""
    deck = await _own(session, deck_id, user, edit=True)
    deck.name, deck.game = data.name.strip(), data.game
    if data.in_meta is not None:
        deck.in_meta = data.in_meta
    _settings(deck, data.format, data.visibility)
    report = await _fill(session, deck, data)
    await session.commit()
    return {"id": deck.id, **report}


@router.put("/{deck_id}/cards")
async def save_cards(deck_id: int, data: CardsIn, user: User = Depends(current_user),
                     session: AsyncSession = Depends(get_session)):
    """Конструктор: сохранить весь список карт. Отвечает замечаниями по формату."""
    deck = await _own(session, deck_id, user, edit=True)
    ids = {r.card_id for r in data.cards if r.card_id}
    cards = {c.id: c for c in (await session.execute(select(Card).where(Card.id.in_(ids), Card.game == deck.game))).scalars()} if ids else {}
    pids = {r.print_id for r in data.cards if r.print_id}
    print_card = dict((await session.execute(select(CardPrint.id, CardPrint.card_id).where(CardPrint.id.in_(pids)))).all()) if pids else {}
    merged: dict[tuple, DeckCard] = {}
    for r in data.cards:
        if r.section not in ("main", "side", "commander"):
            raise HTTPException(400, "Раздел: main, side или commander")
        card = cards.get(r.card_id) if r.card_id else None
        if r.card_id and card is None:
            raise HTTPException(400, "Карта не найдена в базе этой игры")
        name = card.name if card else (r.name or "").strip()
        if not name:
            raise HTTPException(400, "Нужна карта из базы или её название")
        key = (card.id if card else name.lower(), r.section)
        if key in merged:
            merged[key].qty += r.qty
        else:
            pid = r.print_id if card and r.print_id and print_card.get(r.print_id) == card.id else None   # чужое издание - игнорируем
            merged[key] = DeckCard(deck_id=deck.id, card_id=card.id if card else None, name=name, qty=r.qty,
                                   section=r.section, is_commander=r.section == "commander", print_id=pid)
    if sum(dc.qty for dc in merged.values()) > 1000:
        raise HTTPException(400, "Слишком много карт")
    await session.execute(delete(DeckCard).where(DeckCard.deck_id == deck.id))
    session.add_all(merged.values())
    deck.updated_at = func.now()
    await session.flush()
    problems = _problems(deck, await _entries(session, deck.id))
    await session.commit()
    return {"ok": True, "problems": problems}


@router.get("/mine")
async def my_decks(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    counts = dict((await session.execute(
        select(DeckCard.deck_id, func.sum(DeckCard.qty)).join(Deck, Deck.id == DeckCard.deck_id)
        .where(Deck.user_id == user.id, DeckCard.section != "side").group_by(DeckCard.deck_id))).all())
    res = await session.execute(select(Deck).where(Deck.user_id == user.id).order_by(Deck.updated_at.desc(), Deck.id.desc()))
    return [{"id": d.id, "name": d.name, "game": d.game, "in_meta": d.in_meta, "format": d.format,
             "visibility": d.visibility, "cards": int(counts.get(d.id) or 0), "updated_at": d.updated_at}
            for d in res.scalars()]


@router.get("/public")
async def public_decks(format: str | None = None, q: str = "", page: int = 1, session: AsyncSession = Depends(get_session)):
    """Каталог публичных колод: новые сверху, фильтр по формату и названию/командиру."""
    per = 30
    page = max(1, min(page, 200))
    stmt = (select(Deck, User.nickname).join(User, User.id == Deck.user_id)
            .where(Deck.visibility == "public", User.is_banned.is_(False)))
    if format:
        stmt = stmt.where(Deck.format == format)
    if q.strip():
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(or_(func.lower(Deck.name).like(like), Deck.id.in_(
            select(DeckCard.deck_id).where(DeckCard.section == "commander", func.lower(DeckCard.name).like(like)))))
    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await session.execute(stmt.order_by(Deck.updated_at.desc(), Deck.id.desc()).limit(per).offset((page - 1) * per))).all()
    ids = [d.id for d, _ in rows]
    cmd: dict[int, list] = {}
    sizes: dict[int, int] = {}
    price: dict[int, float] = {}
    if ids:
        for dc, card, pr in (await session.execute(select(DeckCard, Card, CardPrint).outerjoin(Card, Card.id == DeckCard.card_id)
                                                   .outerjoin(CardPrint, CardPrint.id == DeckCard.print_id)
                                                   .where(DeckCard.deck_id.in_(ids)))).all():
            if dc.section != "side":
                sizes[dc.deck_id] = sizes.get(dc.deck_id, 0) + dc.qty
            if dc.section == "commander":
                cmd.setdefault(dc.deck_id, []).append({"name": dc.name, "name_ru": card.name_ru if card else None,
                                                       "image_url": (pr.image_url if pr and pr.image_url else card.image_url) if card else None,
                                                       "color_identity": ((card.extra or {}).get("color_identity") if card else None) or []})
            usd = ((card.prices or {}).get("usd") if card else None)
            if usd:
                try:
                    price[dc.deck_id] = price.get(dc.deck_id, 0) + float(usd) * dc.qty
                except ValueError:
                    pass
    return {"total": total, "page": page, "per_page": per, "items": [
        {"id": d.id, "name": d.name, "format": d.format, "game": d.game, "author": nick, "updated_at": d.updated_at,
         "commanders": cmd.get(d.id, []), "cards": sizes.get(d.id, 0), "usd": round(price.get(d.id, 0), 2) or None}
        for d, nick in rows]}


@router.patch("/{deck_id}")
async def patch_deck(deck_id: int, data: DeckPatch, user: User = Depends(current_user),
                     session: AsyncSession = Depends(get_session)):
    """Название, формат, видимость, учёт в мете - без перезаливки деклиста."""
    deck = await _own(session, deck_id, user)
    if data.name is not None:
        deck.name = data.name.strip()
    if data.in_meta is not None:
        deck.in_meta = data.in_meta
    _settings(deck, data.format, data.visibility)
    await session.commit()
    rows = await _entries(session, deck.id)
    return {"id": deck.id, "name": deck.name, "game": deck.game, "in_meta": deck.in_meta, "format": deck.format,
            "visibility": deck.visibility, "share_key": deck.share_key, "problems": _problems(deck, rows)}


@router.get("/{deck_id}")
async def get_deck(deck_id: int, key: str | None = None, user: User | None = Depends(optional_user),
                   session: AsyncSession = Depends(get_session)):
    deck = await session.get(Deck, deck_id)
    if not deck or not await _can_view(session, deck, user, key):
        raise HTTPException(404, "Колода не найдена")
    return await _detail(session, deck, user)


@router.post("/{deck_id}/copy", status_code=201)
async def copy_deck(deck_id: int, key: str | None = None, user: User = Depends(current_user),
                    session: AsyncSession = Depends(get_session)):
    """Скопировать видимую колоду себе (как «Clone» на Moxfield)."""
    src = await session.get(Deck, deck_id)
    if not src or not await _can_view(session, src, user, key):
        raise HTTPException(404, "Колода не найдена")
    deck = Deck(user_id=user.id, name=f"{src.name} (копия)"[:128], game=src.game, format=src.format)
    session.add(deck)
    await session.flush()
    for dc, *_ in await _entries(session, src.id):
        session.add(DeckCard(deck_id=deck.id, card_id=dc.card_id, name=dc.name, qty=dc.qty, section=dc.section,
                             is_commander=dc.is_commander, print_id=dc.print_id))
    await session.commit()
    return {"id": deck.id}


@router.delete("/{deck_id}", status_code=204)
async def delete_deck(deck_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    deck = await _own(session, deck_id, user)
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
