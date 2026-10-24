import gzip
from datetime import datetime, timezone
import json
import re

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from .. import berserk, cardsearch, response, scryfall
from ..cardimport import extract_rows, norm_name, normalize_generic
from ..db import get_session
from ..deps import require_admin
from ..models import Card, CardPrint, SyncRun, User

router = APIRouter(tags=["cards"])
MAX_UPLOAD = 50 * 1024 * 1024


async def upsert_cards(session: AsyncSession, rows: list[dict]) -> int:
    unique = {(r["game"], r["external_id"]): r for r in rows}  # дубли в одном INSERT ломают ON CONFLICT
    items = list(unique.values())
    for i in range(0, len(items), 1000):
        stmt = pg_insert(Card).values(items[i:i + 1000])
        cols = [c for c in items[0] if c not in ("game", "external_id")]
        stmt = stmt.on_conflict_do_update(index_elements=[Card.game, Card.external_id],
                                          set_={c: stmt.excluded[c] for c in cols})
        await session.execute(stmt)
    await session.commit()
    return len(items)


# ---------- публичный поиск ----------
def _print(p: CardPrint) -> dict:
    return {"id": p.id, "set": p.set_code, "set_name": p.set_name, "number": p.collector_number, "rarity": p.rarity,
            "released_at": p.released_at, "artist": p.artist, "image_url": p.image_url, "image_large": p.image_large,
            "back_image": p.back_image, "prices": p.prices or {}, "finishes": p.finishes or [], "promo": p.promo,
            "full_art": p.full_art, "lang": p.lang}


def _brief(c: Card) -> dict:
    return {"id": c.id, "game": c.game, "name": c.name, "name_ru": c.name_ru, "set": c.set_code,
            "type": c.type_line, "mana_cost": c.mana_cost, "rarity": c.rarity, "image_url": c.image_url,
            **({"bk": bk_fields(c.extra or {})} if c.game == "berserk" else {})}


@router.get("/cards")
async def search_cards(q: str = "", game: str | None = None, set_code: str | None = None,
                       limit: int = 30, offset: int = 0, session: AsyncSession = Depends(get_session)):
    """Поиск по названию на английском или русском."""
    limit = max(1, min(limit, 60))
    ql = norm_name(q)
    stmt = select(Card)
    if game:
        stmt = stmt.where(Card.game == game)
    if set_code:
        stmt = stmt.where(Card.set_code == set_code.lower())
    if ql:
        prefix = or_(Card.name_lower.startswith(ql), Card.name_ru_lower.startswith(ql))
        stmt = (stmt.where(or_(Card.name_lower.contains(ql), Card.name_ru_lower.contains(ql)))
                .order_by(prefix.desc(), Card.name_lower))
    else:
        stmt = stmt.order_by(Card.name_lower)
    rows = (await session.execute(stmt.limit(limit).offset(offset))).scalars()
    return [_brief(c) for c in rows]


@router.get("/cards/stats")
async def card_stats(session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(Card.game, func.count(), func.count(Card.name_ru)).group_by(Card.game))).all()
    last = await scryfall.last_run(session)
    prints = (await session.execute(select(func.count()).select_from(CardPrint))).scalar_one()
    bk = await berserk.last_run(session)
    rs = await response.last_run(session)
    return {"games": {g: {"cards": n, "russian": ru, **({"prints": prints} if g == "mtg" else {})} for g, n, ru in rows},
            "scryfall_updated": last.finished_at if last and last.cards else None,
            "berserk_updated": bk.finished_at if bk and bk.cards else None,
            "response_updated": rs.finished_at if rs and rs.cards else None}


def _back(ex: dict) -> str | None:
    """Картинка обратной стороны (трансформ, MDFC). У split/adventure второй картинки нет - None."""
    faces = ex.get("faces") or []
    back = faces[1].get("image") if len(faces) > 1 else None
    return back if back and back != (faces[0].get("image") if faces else None) else None


def _row(c: Card) -> dict:
    """Карта в выдаче Картотеки: хватает для сетки, списка и текстового вида."""
    ex = c.extra or {}
    return {**_brief(c), "set_name": c.set_name, "cmc": c.cmc, "text": c.text, "type_ru": c.type_ru,
            "text_ru": c.text_ru, "power": ex.get("power"), "toughness": ex.get("toughness"),
            "loyalty": ex.get("loyalty"), "colors": ex.get("colors"), "prices": c.prices or {},
            "color_identity": ex.get("color_identity") or [], "legalities": c.legalities or {},
            "back_image": _back(ex),
            "is_game_changer": c.is_game_changer, **({"bk": bk_fields(ex)} if c.game == "berserk" else {}),
            **({"rs": response.rs_fields(ex)} if c.game == "response" else {})}


def bk_fields(ex: dict) -> dict:
    """Свойства карты «Берсерка» для плиток и конструктора."""
    return {k: ex.get(k) for k in ("number", "elements", "elite", "unique", "class", "kind", "health", "move",
                                   "strike", "icons")}


@router.get("/cards/search")
async def search_cards_query(q: str = "", game: str | None = None, order: str | None = None, dir: str | None = None,
                             page: int = 1, per_page: int = 60, session: AsyncSession = Depends(get_session)):
    """Поиск Картотеки на языке запросов в духе Scryfall (см. app/cardsearch.py)."""
    per_page = max(1, min(per_page, 120))
    page = max(1, min(page, 500))
    parsed = cardsearch.parse(q[:500])
    game = parsed.game or game
    where = parsed.where if not game else (Card.game == game) & parsed.where
    total = (await session.execute(select(func.count()).select_from(Card).where(where))).scalar_one()
    order = cardsearch.ORDERS.get((order or "").lower()) or parsed.order
    direction = (dir if dir in ("asc", "desc") else None) or parsed.direction
    ranking = cardsearch.relevance(parsed.words) if not order else []   # явная сортировка - без «релевантности»
    rows = (await session.execute(select(Card).where(where).order_by(*ranking, *cardsearch.order_by(order, direction))
                                  .limit(per_page).offset((page - 1) * per_page))).scalars()
    return {"total": total, "page": page, "per_page": per_page, "order": order or "name",
            "dir": direction or "asc", "warnings": parsed.warnings, "items": [_row(c) for c in rows]}


@router.get("/cards/sets")
async def card_sets(game: str = "mtg", session: AsyncSession = Depends(get_session)):
    """Сеты игры для расширенного поиска: код, название, сколько карт."""
    if game == "mtg" and (await session.execute(select(CardPrint.id).limit(1))).first():
        # все сеты, где карты печатались: новые сверху
        rows = (await session.execute(select(CardPrint.set_code, func.max(CardPrint.set_name),
                                             func.count(func.distinct(CardPrint.card_id)), func.max(CardPrint.released_at))
                                      .group_by(CardPrint.set_code)
                                      .order_by(func.max(CardPrint.released_at).desc().nulls_last()))).all()
        return [{"code": s, "name": n or s, "cards": k, "released": r} for s, n, k, r in rows]
    rows = (await session.execute(select(Card.set_code, func.max(Card.set_name), func.count())
                                  .where(Card.game == game, Card.set_code.is_not(None))
                                  .group_by(Card.set_code).order_by(func.coalesce(func.max(Card.set_name), Card.set_code)))).all()
    return [{"code": s, "name": n or s, "cards": k} for s, n, k in rows]


@router.get("/cards/{card_id}")
async def get_card(card_id: int, session: AsyncSession = Depends(get_session)):
    c = await session.get(Card, card_id)
    if not c:
        raise HTTPException(404, "Карта не найдена")
    prints = (await session.execute(select(CardPrint).where(CardPrint.card_id == c.id)
                                    .order_by(CardPrint.released_at.desc().nulls_last(), CardPrint.collector_number)
                                    .limit(400))).scalars().all()
    return {**_brief(c), "set_name": c.set_name, "text": c.text, "type_ru": c.type_ru, "text_ru": c.text_ru,
            "cmc": c.cmc, "commander_legal": c.commander_legal, "is_game_changer": c.is_game_changer,
            "legalities": c.legalities or {}, "prices": c.prices or {}, "scryfall_uri": c.scryfall_uri,
            "extra": c.extra or {}, "back_image": _back(c.extra or {}), "prints": [_print(p) for p in prints],
            **({"bk": bk_fields(c.extra or {})} if c.game == "berserk" else {}),
            **({"rs": response.rs_fields(c.extra or {})} if c.game == "response" else {})}


# ---------- админка: Scryfall ----------
async def _run_sync():
    try:
        await scryfall.sync(trigger="admin")
    except scryfall.SyncBusy:
        pass


@router.post("/admin/cards/sync/scryfall", status_code=202)
async def sync_scryfall(bg: BackgroundTasks, admin: User = Depends(require_admin),
                        session: AsyncSession = Depends(get_session)):
    if await scryfall.is_running(session):
        raise HTTPException(409, "Загрузка уже идёт")
    bg.add_task(_run_sync)
    return {"status": "started"}


@router.get("/admin/cards/sync/status")
async def sync_status(admin: User = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    last = await scryfall.last_run(session)
    return {"running": await scryfall.is_running(session),
            "last": None if not last else {"started": last.started_at, "finished": last.finished_at,
                                           "trigger": last.trigger, "cards": last.cards,
                                           "russian": last.russian, "prints": last.prints or 0, "error": last.error}}


# ---------- админка: «Берсерк» с ProBerserk.ru ----------
async def _run_berserk():
    try:
        await berserk.sync(trigger="admin")
    except berserk.SyncBusy:
        pass


@router.post("/admin/cards/sync/berserk", status_code=202)
async def sync_berserk(bg: BackgroundTasks, admin: User = Depends(require_admin),
                       session: AsyncSession = Depends(get_session)):
    if await berserk.is_running(session):
        raise HTTPException(409, "Загрузка уже идёт")
    bg.add_task(_run_berserk)
    return {"status": "started"}


@router.get("/admin/cards/sync/berserk")
async def berserk_status(admin: User = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    last = await berserk.last_run(session)
    return {"running": await berserk.is_running(session), "cards": await berserk.count(session),
            "last": None if not last else {"started": last.started_at, "finished": last.finished_at,
                                           "cards": last.cards, "error": last.error}}


# ---------- админка: «Берсерк» и любые другие JSON-базы ----------
@router.post("/admin/cards/import/{game}")
async def import_cards(game: str, file: UploadFile = File(...), mapping: str | None = Form(None),
                       dry_run: bool = Form(False), admin: User = Depends(require_admin),
                       session: AsyncSession = Depends(get_session)):
    """JSON-массив карт (или {"cards": [...]}). Поля угадываются по названиям (рус/англ),
    свои соответствия можно передать в mapping: {"name": "title", "image_url": "pic"}.
    dry_run=true ничего не пишет и показывает, как будут разобраны первые карты."""
    raw = await file.read(MAX_UPLOAD + 1)
    if len(raw) > MAX_UPLOAD:
        raise HTTPException(413, "Файл больше 50 МБ")
    try:
        rows = extract_rows(json.loads(raw))
        mp = json.loads(mapping) if mapping else None
    except json.JSONDecodeError as e:
        raise HTTPException(400, f"Некорректный JSON: {e}")
    if not rows:
        raise HTTPException(400, "В файле нет карт (ожидается массив объектов)")
    cards, skipped = [], 0
    for r in rows:
        c = normalize_generic(r, mp, game)
        cards.append(c) if c else None
        skipped += c is None
    if dry_run:
        return {"total": len(rows), "would_import": len(cards), "skipped_no_name": skipped,
                "sample": [{k: c[k] for k in ("external_id", "name", "set_code", "type_line", "mana_cost",
                                              "text", "rarity", "image_url", "extra")} for c in cards[:3]]}
    if not cards:
        raise HTTPException(400, "Не удалось найти поле с названием карты: передайте mapping")
    return {"imported": await upsert_cards(session, cards), "skipped_no_name": skipped}



# ---------- русские названия из файла (когда Scryfall недоступен) ----------
_COPY_ESC = re.compile(r"\\(.)")
_COPY_MAP = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "\\": "\\"}


def _copy_field(v: str) -> str | None:
    """Поле в текстовом формате COPY PostgreSQL: \\N - пусто, \\n - перенос строки и т.д."""
    if v == "\\N":
        return None
    return _COPY_ESC.sub(lambda m: _COPY_MAP.get(m.group(1), m.group(1)), v)


def parse_russian_file(raw: bytes) -> dict[str, dict]:
    """Файл ru-names.sql(.gz) или TSV из 6 колонок: oracle_id, название, его нижний регистр, лицевая сторона,
    тип, текст. Возвращает oracle_id -> русские поля (как их пишет загрузка из Scryfall)."""
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    lines = raw.decode("utf-8").splitlines()
    if any(line.startswith("COPY ru FROM stdin") for line in lines):
        start = next(i for i, line in enumerate(lines) if line.startswith("COPY ru FROM stdin")) + 1
        end = next((i for i in range(start, len(lines)) if lines[i] == "\\."), len(lines))
        lines = lines[start:end]
    out = {}
    for line in lines:
        parts = line.split("\t")
        if len(parts) != 6 or not parts[1] or parts[1] == "\\N":
            continue
        oid, name, low, front, typ, txt = (_copy_field(p) for p in parts)
        out[oid] = {"oracle_id": oid, "name_ru": name, "name_ru_lower": low or name.lower(),
                    "name_ru_front": front or (low or name.lower()).split(" // ")[0], "type_ru": typ, "text_ru": txt}
    return out


@router.post("/admin/cards/russian")
async def upload_russian(file: UploadFile = File(...), admin: User = Depends(require_admin),
                         session: AsyncSession = Depends(get_session)):
    """Русские названия MTG из файла: дописывает к картам, которые уже есть в базе, ничего не удаляет."""
    raw = await file.read(MAX_UPLOAD + 1)
    if len(raw) > MAX_UPLOAD:
        raise HTTPException(413, "Файл больше 50 МБ")
    try:
        ru = parse_russian_file(raw)
    except (OSError, UnicodeDecodeError, StopIteration) as e:
        raise HTTPException(400, f"Не удалось прочитать файл: {e}")
    if not ru:
        raise HTTPException(400, "В файле нет русских названий: нужен ru-names.sql.gz или TSV из 6 колонок")
    updated = await scryfall._apply_russian(session, ru)
    total = (await session.execute(select(func.count()).select_from(Card).where(
        Card.game == "mtg", Card.name_ru.is_not(None)))).scalar_one()
    return {"in_file": len(ru), "updated": updated, "cards_with_russian": total}


# ---------- «Респонс»: API разработчика или файл выгрузки ----------
async def _run_response():
    try:
        await response.sync(trigger="admin", force=True)
    except response.SyncBusy:
        pass


@router.post("/admin/cards/sync/response", status_code=202)
async def sync_response(bg: BackgroundTasks, admin: User = Depends(require_admin),
                        session: AsyncSession = Depends(get_session)):
    if await response.is_running(session):
        raise HTTPException(409, "Загрузка уже идёт")
    bg.add_task(_run_response)
    return {"started": True}


@router.get("/admin/cards/sync/response")
async def response_status(admin: User = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    from .. import system
    last = await response.last_run(session)
    st = await system.get_status(session, response.STATUS_KEY)
    return {"running": await response.is_running(session), "cards": await response.count(session),
            "auth": response.auth_mode(), "key_configured": response.auth_mode() != "none",
            "catalog_version": st.value[:12] if st and st.value else None,
            "last": {"started_at": last.started_at, "finished_at": last.finished_at, "cards": last.cards,
                     "error": last.error, "trigger": last.trigger} if last else None}


@router.post("/admin/cards/response/import")
async def import_response(file: UploadFile, admin: User = Depends(require_admin),
                          session: AsyncSession = Depends(get_session)):
    """Файл выгрузки API (одна страница или список страниц). Карты добавляются и обновляются, ничего не удаляется."""
    import json
    raw = await file.read(30 * 1024 * 1024 + 1)
    if len(raw) > 30 * 1024 * 1024:
        raise HTTPException(413, "Файл больше 30 МБ")
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        raise HTTPException(422, "Это не JSON-выгрузка API «Респонса»")
    cards, meta = response.parse_payload(data)
    if not cards:
        raise HTTPException(422, "В файле не нашлось карт «Респонса»")
    n = await response.store(session, cards, full=False)
    session.add(SyncRun(source=response.SOURCE, trigger="file", cards=n, finished_at=datetime.now(timezone.utc)))
    await session.commit()
    return {"cards": n, "total_in_api": meta.get("total"), "page": meta.get("current_page"),
            "last_page": meta.get("last_page"), "in_base": await response.count(session)}
