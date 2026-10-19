import asyncio
import json
import tempfile
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..cardimport import extract_rows, normalize_generic, normalize_scryfall
from ..db import SessionLocal, get_session
from ..deps import require_admin
from ..models import Card, User

router = APIRouter(tags=["cards"])
MAX_UPLOAD = 50 * 1024 * 1024
sync_state: dict = {"running": False, "started": None, "finished": None, "count": 0, "error": None}


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
@router.get("/cards")
async def search_cards(q: str = "", game: str | None = None, set_code: str | None = None,
                       limit: int = 30, offset: int = 0, session: AsyncSession = Depends(get_session)):
    limit = max(1, min(limit, 50))
    ql = q.strip().lower()
    stmt = select(Card)
    if game:
        stmt = stmt.where(Card.game == game)
    if set_code:
        stmt = stmt.where(Card.set_code == set_code)
    if ql:
        stmt = stmt.where(Card.name_lower.contains(ql)).order_by(Card.name_lower.startswith(ql).desc(), Card.name_lower)
    else:
        stmt = stmt.order_by(Card.name_lower)
    rows = (await session.execute(stmt.limit(limit).offset(offset))).scalars()
    return [{"id": c.id, "game": c.game, "name": c.name, "set": c.set_code, "type": c.type_line,
             "mana_cost": c.mana_cost, "rarity": c.rarity, "image_url": c.image_url} for c in rows]


@router.get("/cards/{card_id}")
async def get_card(card_id: int, session: AsyncSession = Depends(get_session)):
    c = await session.get(Card, card_id)
    if not c:
        raise HTTPException(404, "Карта не найдена")
    return {"id": c.id, "game": c.game, "name": c.name, "set": c.set_code, "set_name": c.set_name,
            "type": c.type_line, "mana_cost": c.mana_cost, "text": c.text, "rarity": c.rarity,
            "image_url": c.image_url, "commander_legal": c.commander_legal, "extra": c.extra}


# ---------- админка: Scryfall ----------
def _parse_bulk(path: str) -> list[dict]:
    import ijson
    out = []
    with open(path, "rb") as f:
        for obj in ijson.items(f, "item"):
            card = normalize_scryfall(obj)
            if card:
                out.append(card)
    return out


async def run_scryfall_sync():
    import httpx
    sync_state.update(running=True, started=datetime.now(timezone.utc).isoformat(), error=None, count=0)
    headers = {"User-Agent": "KKIPlatform/1.0", "Accept": "application/json;q=0.9,*/*;q=0.8"}
    try:
        async with httpx.AsyncClient(headers=headers, timeout=180, follow_redirects=True) as client:
            meta = (await client.get("https://api.scryfall.com/bulk-data")).json()
            uri = next(x["download_uri"] for x in meta["data"] if x["type"] == "oracle_cards")
            with tempfile.NamedTemporaryFile(suffix=".json") as tmp:
                async with client.stream("GET", uri) as resp:
                    resp.raise_for_status()
                    async for chunk in resp.aiter_bytes():
                        tmp.write(chunk)
                tmp.flush()
                rows = await asyncio.to_thread(_parse_bulk, tmp.name)  # разбор не блокирует event loop
        async with SessionLocal() as session:
            sync_state["count"] = await upsert_cards(session, rows)
    except Exception as e:  # noqa: BLE001
        sync_state["error"] = repr(e)
    finally:
        sync_state.update(running=False, finished=datetime.now(timezone.utc).isoformat())


@router.post("/admin/cards/sync/scryfall", status_code=202)
async def sync_scryfall(bg: BackgroundTasks, admin: User = Depends(require_admin)):
    if sync_state["running"]:
        raise HTTPException(409, "Синхронизация уже идёт")
    bg.add_task(run_scryfall_sync)
    return {"status": "started"}


@router.get("/admin/cards/sync/status")
async def sync_status(admin: User = Depends(require_admin)):
    return sync_state


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
