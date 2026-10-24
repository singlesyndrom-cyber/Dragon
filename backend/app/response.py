"""База карт ККИ «Респонс» из API разработчика (response-league.ru).

Формат API: {"data": [карта, ...], "meta": {"current_page", "last_page", "per_page", "total", "catalog_version"}}.
Карта: id (слаг), name, types, supertypes, subtypes, factions, keywords, is_hero, cost, strength, durability,
text, levels (уровни героя: influence, text), rulings (разъяснения), printings (издания с картинками).

Доступ: OAuth 2 client credentials (RESPONSE_CLIENT_ID и RESPONSE_CLIENT_SECRET в .env) - сайт сам получает
временный токен на /oauth/token; запасной вариант - статический ключ (RESPONSE_API_KEY). Секреты в браузер не
отдаются; картинки идут через наш сервер (/img/rs/<uuid>). Версия каталога (X-Catalog-Version / ETag)
запоминается: если не изменилась, повторная загрузка ничего не качает. Без доступа к API базу можно загрузить
файлом выгрузки в админке.
"""
import asyncio
import logging
import re
import time
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


class NotChanged(Exception):
    """Версия каталога та же, что при прошлой загрузке: качать нечего."""


STATUS_KEY = "response_catalog"           # ServiceStatus: версия каталога последней полной загрузки
_token: dict = {"value": None, "until": 0.0}


def auth_mode() -> str:
    if settings.response_client_id and settings.response_client_secret:
        return "oauth"
    return "key" if settings.response_api_key else "none"


async def access_token(client: httpx.AsyncClient | None = None) -> str | None:
    """OAuth client credentials: токен кэшируется до истечения (минус минута)."""
    if auth_mode() != "oauth":
        return None
    if _token["value"] and time.time() < _token["until"]:
        return _token["value"]
    data = {"grant_type": "client_credentials", "client_id": settings.response_client_id,
            "client_secret": settings.response_client_secret}
    if settings.response_oauth_scope:
        data["scope"] = settings.response_oauth_scope
    own = client is None
    http = client or httpx.AsyncClient(timeout=httpx.Timeout(15, read=30))
    try:
        r = await http.post(settings.response_oauth_url, data=data, headers={"Accept": "application/json"})
    finally:
        if own:
            await http.aclose()
    if r.status_code in (400, 401, 403):
        raise ValueError("OAuth «Респонса» не принял client_id и секрет: проверьте RESPONSE_CLIENT_ID и RESPONSE_CLIENT_SECRET")
    r.raise_for_status()
    body = r.json()
    _token["value"] = body["access_token"]
    _token["until"] = time.time() + max(60, int(body.get("expires_in") or 3600) - 60)
    return _token["value"]


def api_headers(token: str | None = None) -> dict:
    h = {"Accept": "application/json", "User-Agent": "DragonClub/1.0 (+https://dragonclub.games)"}
    if token:
        h["Authorization"] = "Bearer " + token
    elif settings.response_api_key:
        h[settings.response_api_header] = settings.response_api_prefix + settings.response_api_key
    return h


async def _page(client: httpx.AsyncClient, page: int) -> httpx.Response:
    token = await access_token(client)
    r = await client.get(settings.response_api_url, params={"page": page}, headers=api_headers(token))
    if r.status_code == 401 and token:          # токен отозвали раньше срока - берём новый один раз
        _token["value"] = None
        r = await client.get(settings.response_api_url, params={"page": page}, headers=api_headers(await access_token(client)))
    if r.status_code in (401, 403):
        raise ValueError("API «Респонса» отказал в доступе: нужна авторизация (RESPONSE_CLIENT_ID и RESPONSE_CLIENT_SECRET в .env)")
    r.raise_for_status()
    return r


def catalog_version(r: httpx.Response, meta: dict) -> str | None:
    return r.headers.get("x-catalog-version") or meta.get("catalog_version") or (r.headers.get("etag") or "").strip('"') or None


async def fetch_all(client: httpx.AsyncClient, pause: float = PAUSE, known: str | None = None) -> tuple[list[dict], dict]:
    """Все страницы каталога. known - версия прошлой загрузки: если не изменилась, NotChanged после первой страницы."""
    cards, page, last, meta, version = [], 1, 1, {}, None
    while page <= last:
        r = await _page(client, page)
        got, meta = parse_payload(r.json())
        v = catalog_version(r, meta)
        if page == 1:
            version = v
            if known and v and v == known:
                raise NotChanged(v)
        elif v and version and v != version:
            raise ValueError("Каталог «Респонса» обновился во время загрузки — запустите ещё раз")
        cards += got
        last = int(meta.get("last_page") or page)
        page += 1
        if page <= last:
            await asyncio.sleep(pause)
    if not cards:
        raise ValueError("API «Респонса» ответило, но карт в ответе нет")
    meta["catalog_version"] = version
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


async def sync(trigger: str = "admin", client: httpx.AsyncClient | None = None, pause: float = PAUSE,
               force: bool = False) -> SyncRun | None:
    """Полная загрузка каталога. Без force и при той же версии каталога ничего не качает и возвращает None."""
    from . import system
    from .scryfall import explain
    async with SessionLocal() as lock_session:
        if not (await lock_session.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": LOCK_ID})).scalar():
            raise SyncBusy("Загрузка уже идёт")
        try:
            async with SessionLocal() as s:
                st = await system.get_status(s, STATUS_KEY)
                known = None if force or not await count(s) else (st.value if st else None)
                own = client is None
                http = client or httpx.AsyncClient(timeout=httpx.Timeout(15, read=60), follow_redirects=True)
                run = SyncRun(source=SOURCE, trigger=trigger)
                try:
                    cards, meta = await fetch_all(http, pause, known)
                    s.add(run)
                    total = int(meta.get("total") or 0)
                    # убираем пропавшие карты только если пришло всё, что API обещало
                    run.cards = await store(s, cards, full=not total or len(cards) >= total)
                    if meta.get("catalog_version"):
                        await system.set_status(s, STATUS_KEY, meta["catalog_version"])
                        await s.commit()
                except NotChanged:
                    return None
                except Exception as e:  # noqa: BLE001
                    await s.rollback()
                    s.add(run)
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


async def auto_sync_loop() -> None:
    """Бот: при пустой базе и затем раз в 6 часов сверяет версию каталога; изменилась - обновляет базу."""
    await asyncio.sleep(120)
    while True:
        try:
            run = await sync(trigger="auto")
            if run:
                log.info("Респонс: загружено %s карт%s", run.cards, f", ошибка: {run.error}" if run.error else "")
        except SyncBusy:
            pass
        except Exception:  # noqa: BLE001
            log.exception("автообновление «Респонса»")
        await asyncio.sleep(6 * 3600)


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
