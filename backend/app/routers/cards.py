import gzip
import json
import re

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from .. import scryfall
from ..cardimport import extract_rows, norm_name, normalize_generic
from ..db import get_session
from ..deps import require_admin
from ..models import Card, User

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
def _brief(c: Card) -> dict:
    return {"id": c.id, "game": c.game, "name": c.name, "name_ru": c.name_ru, "set": c.set_code,
            "type": c.type_line, "mana_cost": c.mana_cost, "rarity": c.rarity, "image_url": c.image_url}


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
    return {"games": {g: {"cards": n, "russian": ru} for g, n, ru in rows},
            "scryfall_updated": last.finished_at if last and last.cards else None}


@router.get("/cards/{card_id}")
async def get_card(card_id: int, session: AsyncSession = Depends(get_session)):
    c = await session.get(Card, card_id)
    if not c:
        raise HTTPException(404, "Карта не найдена")
    return {**_brief(c), "set_name": c.set_name, "text": c.text, "type_ru": c.type_ru, "text_ru": c.text_ru,
            "cmc": c.cmc, "commander_legal": c.commander_legal, "is_game_changer": c.is_game_changer,
            "legalities": c.legalities or {}, "prices": c.prices or {}, "scryfall_uri": c.scryfall_uri,
            "extra": c.extra or {}}


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
                                           "russian": last.russian, "error": last.error}}


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
