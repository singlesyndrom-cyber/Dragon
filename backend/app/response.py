"""База карт ККИ «Респонс» из API разработчика (response-league.ru).

Формат API: {"data": [карта, ...], "meta": {"current_page", "last_page", "per_page", "total", "catalog_version"}}.
Карта: id (слаг), name, types, supertypes, subtypes, factions, keywords, is_hero, cost, strength, durability,
text, levels (уровни героя: influence, text), rulings (разъяснения), printings (издания с картинками).

Ключ API хранится только в .env сервера (RESPONSE_API_KEY) и в браузер не отдаётся; картинки идут через наш
сервер (/img/rs/<uuid>). Без ключа базу можно загрузить файлом выгрузки API в админке.
"""
import asyncio
import logging
import re
from datetime import datetime, timezone

import httpx
from sqlalchemy import delete, select, text

from .cardimport import _finalize
from .config import settings
from .db import SessionLocal
from .models import Card, SyncRun

log = logging.getLogger("response")

SOURCE = "response"
SITE = "https://response-league.ru"
IMAGES = SITE + "/api/v1/card-images/"
LOCK_ID = 74200417
PAUSE = 1.0
CREDIT = "Данные и изображения карт: «Респонс» (response-league.ru), с разрешения правообладателя"
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

FACTIONS = ["Порядок", "Хаос", "Жизнь", "Смерть", "Природа", "Технологии"]
TYPES = ["Герой", "Юнит", "Заклинание", "Усиление", "Ловушка", "Локация"]
RARITIES = ["Бронза", "Серебро", "Золото"]


class SyncBusy(Exception):
    pass


def _image_id(url: str | None) -> str | None:
    if url and url.startswith(IMAGES):
        tail = url[len(IMAGES):].split("?")[0].strip("/")
        return tail if UUID.match(tail) else None
    return None


def to_card(item: dict) -> dict | None:
    """Карта API -> строка таблицы cards (game="response")."""
    cid, name = str(item.get("id") or "").strip(), str(item.get("name") or "").strip()
    if not cid or not name:
        return None
    types, supers, subs = item.get("types") or [], item.get("supertypes") or [], item.get("subtypes") or []
    head = " ".join([*supers, *types])
    type_line = f"{head} — {', '.join(subs)}" if subs else head
    levels = [{"influence": lv.get("influence"), "text": lv.get("text")} for lv in item.get("levels") or []]
    body = item.get("text")
    if not body and levels:          # у героя текст - на уровнях
        body = "\n".join(f"Уровень {i + 1} (влияние {lv['influence']}): {lv['text']}" for i, lv in enumerate(levels))
    printings = []
    for p in item.get("printings") or []:
        imgs = sorted(p.get("images") or [], key=lambda x: x.get("position") or 0)
        printings.append({"id": p.get("id"), "set": p.get("set"), "number": p.get("number"), "rarity": p.get("rarity"),
                          "images": [{"face": i.get("face"), "medium": _image_id(i.get("medium_url")),
                                      "thumb": _image_id(i.get("thumb_url"))} for i in imgs]})
    first = printings[0] if printings else {}
    img = next((i["medium"] or i["thumb"] for i in first.get("images", []) if i["medium"] or i["thumb"]), None)
    cost = item.get("cost")
    card = {
        "external_id": cid[:64], "name": name,
        "set_code": (str(first.get("id") or "").split("-")[0] or None) if first else None,
        "set_name": first.get("set"), "type_line": type_line or None,
        "mana_cost": str(cost) if cost is not None else None, "cmc": float(cost) if cost is not None else None,
        "text": body, "rarity": first.get("rarity"),
        "image_url": IMAGES + img if img else None,
        "extra": {"factions": item.get("factions") or [], "types": types, "supertypes": supers, "subtypes": subs,
                  "keywords": item.get("keywords") or [], "hero": bool(item.get("is_hero")),
                  "order": "Приказ" in supers, "legendary": "Легендарный" in supers,
                  "strength": item.get("strength"), "durability": item.get("durability"),
                  "levels": levels, "rulings": [r.get("body") for r in item.get("rulings") or [] if r.get("body")],
                  "printings": printings, "source": "response-league.ru"},
    }
    return _finalize(card, "response")


def parse_payload(data) -> tuple[list[dict], dict]:
    """Одна страница API ({"data", "meta"}), список страниц или просто список карт."""
    pages = data if isinstance(data, list) and data and isinstance(data[0], dict) and "data" in data[0] else [data]
    cards, meta = [], {}
    for page in pages:
        items = page.get("data") if isinstance(page, dict) else page
        meta = (page.get("meta") if isinstance(page, dict) else None) or meta
        for it in items or []:
            if isinstance(it, dict) and (c := to_card(it)):
                cards.append(c)
    return cards, meta


def api_headers() -> dict:
    h = {"Accept": "application/json", "User-Agent": "DragonClub/1.0 (+https://dragonclub.games)"}
    if settings.response_api_key:
        h[settings.response_api_header] = settings.response_api_prefix + settings.response_api_key
    return h


async def fetch_all(client: httpx.AsyncClient, pause: float = PAUSE) -> tuple[list[dict], dict]:
    url = settings.response_api_url
    cards, page, last, meta = [], 1, 1, {}
    while page <= last:
        r = await client.get(url, params={"page": page})
        if r.status_code in (401, 403):
            raise ValueError("API «Респонса» не принял ключ: проверьте RESPONSE_API_KEY и способ передачи в .env")
        r.raise_for_status()
        got, meta = parse_payload(r.json())
        cards += got
        last = int(meta.get("last_page") or page)
        page += 1
        if page <= last:
            await asyncio.sleep(pause)
    if not cards:
        raise ValueError("API «Респонса» ответило, но карт в ответе нет")
    return cards, meta


async def store(session, cards: list[dict], full: bool) -> int:
    """Записать карты; при полной загрузке - убрать карты, которых больше нет в источнике."""
    from .routers.cards import upsert_cards
    n = await upsert_cards(session, cards)
    if full:
        keep = {c["external_id"] for c in cards}
        await session.execute(delete(Card).where(Card.game == "response", Card.external_id.not_in(keep)))
        await session.commit()
    return n


async def sync(trigger: str = "admin", client: httpx.AsyncClient | None = None, pause: float = PAUSE) -> SyncRun:
    from .scryfall import explain
    async with SessionLocal() as lock_session:
        if not (await lock_session.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": LOCK_ID})).scalar():
            raise SyncBusy("Загрузка уже идёт")
        try:
            async with SessionLocal() as s:
                run = SyncRun(source=SOURCE, trigger=trigger)
                s.add(run)
                await s.commit()
                own = client is None
                http = client or httpx.AsyncClient(headers=api_headers(), timeout=httpx.Timeout(15, read=60),
                                                   follow_redirects=True)
                try:
                    cards, meta = await fetch_all(http, pause)
                    total = int(meta.get("total") or 0)
                    # убираем пропавшие карты только если пришло всё, что API обещало
                    run.cards = await store(s, cards, full=not total or len(cards) >= total)
                except Exception as e:  # noqa: BLE001
                    await s.rollback()
                    run.error = explain(e)[:2000]
                    log.exception("response sync failed")
                finally:
                    if own:
                        await http.aclose()
                run.finished_at = datetime.now(timezone.utc)
                s.add(run)
                await s.commit()
                return run
        finally:
            await lock_session.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_ID})


async def is_running(session) -> bool:
    got = (await session.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": LOCK_ID})).scalar()
    if got:
        await session.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_ID})
    return not got


async def last_run(session) -> SyncRun | None:
    return (await session.execute(select(SyncRun).where(SyncRun.source == SOURCE)
                                  .order_by(SyncRun.id.desc()).limit(1))).scalar_one_or_none()


async def count(session) -> int:
    from sqlalchemy import func
    return (await session.execute(select(func.count()).select_from(Card).where(Card.game == "response"))).scalar_one()


def rs_fields(ex: dict) -> dict:
    """Свойства карты «Респонса» для плиток, страницы карты и конструктора."""
    return {k: ex.get(k) for k in ("factions", "types", "supertypes", "subtypes", "keywords", "hero", "order",
                                   "legendary", "strength", "durability", "levels", "rulings", "printings")}
