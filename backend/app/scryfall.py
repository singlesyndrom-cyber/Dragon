"""Загрузка базы карт MTG из Scryfall (https://scryfall.com/docs/api) - открытый источник.

1. Bulk-файл «Oracle Cards»: одна запись на каждую карту (~35 тыс.), с текстом, типом, форматами,
   ценами и ссылками на изображения в CDN Scryfall.
2. Русские печати через поиск (lang:ru): печатное название, тип и текст, привязка по oracle_id.

Запуск: кнопка в админке или автоматически (бот: при пустой базе и раз в неделю).
Параллельные запуски исключены advisory-блокировкой PostgreSQL; результат пишется в sync_runs.
"""
import asyncio
import logging
import tempfile
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import bindparam, func, select, text

from .cardimport import normalize_ru, normalize_scryfall
from .db import SessionLocal
from .models import Card, SyncRun

log = logging.getLogger("scryfall")

API = "https://api.scryfall.com"
# Scryfall требует осмысленный User-Agent и Accept; без них отвечает 400.
HEADERS = {"User-Agent": "DragonTCGPlatform/1.0 (+https://github.com/singlesyndrom-cyber/Dragon)",
           "Accept": "application/json;q=0.9,*/*;q=0.8"}
LOCK_ID = 7_420_001                        # ключ advisory-блокировки PostgreSQL
REQUEST_PAUSE = 0.12                       # не больше ~10 запросов в секунду (правила Scryfall)
REFRESH_EVERY = timedelta(days=7)


class SyncBusy(Exception):
    pass


def _parse_bulk(path: str) -> list[dict]:
    import ijson
    out = []
    with open(path, "rb") as f:
        for obj in ijson.items(f, "item"):
            card = normalize_scryfall(obj)
            if card:
                out.append(card)
    return out


async def _download_oracle(client: httpx.AsyncClient) -> list[dict]:
    meta = (await client.get(f"{API}/bulk-data")).raise_for_status().json()
    uri = next(x["download_uri"] for x in meta["data"] if x["type"] == "oracle_cards")
    with tempfile.NamedTemporaryFile(suffix=".json") as tmp:
        async with client.stream("GET", uri) as resp:
            resp.raise_for_status()
            async for chunk in resp.aiter_bytes():
                tmp.write(chunk)
        tmp.flush()
        return await asyncio.to_thread(_parse_bulk, tmp.name)   # разбор ~150 МБ не блокирует event loop


async def _fetch_russian(client: httpx.AsyncClient, max_pages: int = 400) -> dict[str, dict]:
    """oracle_id -> русские поля. Берём первую найденную русскую печать каждой карты."""
    out: dict[str, dict] = {}
    url: str | None = f"{API}/cards/search"
    params: dict | None = {"q": "lang:ru", "unique": "cards", "order": "name"}
    for _ in range(max_pages):
        if not url:
            break
        r = await client.get(url, params=params)
        if r.status_code == 404:          # ничего не найдено
            break
        r.raise_for_status()
        page = r.json()
        for obj in page.get("data", []):
            ru = normalize_ru(obj)
            if ru:
                out.setdefault(ru["oracle_id"], ru)
        url, params = (page.get("next_page"), None) if page.get("has_more") else (None, None)
        await asyncio.sleep(REQUEST_PAUSE)
    return out


async def _apply_russian(session, ru: dict[str, dict]) -> int:
    if not ru:
        return 0
    stmt = (Card.__table__.update()
            .where(Card.__table__.c.game == "mtg", Card.__table__.c.external_id == bindparam("oid"))
            .values(name_ru=bindparam("nr"), name_ru_lower=bindparam("nrl"), name_ru_front=bindparam("nrf"),
                    type_ru=bindparam("tr"), text_ru=bindparam("xr")))
    keys = list(ru)
    known: set[str] = set()
    for i in range(0, len(keys), 5000):    # обновляем и считаем только карты, которые есть в нашей базе
        known |= set((await session.execute(select(Card.external_id).where(
            Card.game == "mtg", Card.external_id.in_(keys[i:i + 5000])))).scalars())
    rows = [{"oid": k, "nr": v["name_ru"], "nrl": v["name_ru_lower"], "nrf": v["name_ru_front"],
             "tr": v["type_ru"], "xr": v["text_ru"]}
            for k, v in ru.items() if k in known]
    if not rows:
        return 0
    conn = await session.connection()
    for i in range(0, len(rows), 2000):
        await conn.execute(stmt, rows[i:i + 2000])
    await session.commit()
    return len(rows)


async def sync(trigger: str = "admin", client: httpx.AsyncClient | None = None, russian: bool = True) -> SyncRun:
    """Полная загрузка. Бросает SyncBusy, если загрузка уже идёт (в любом процессе)."""
    from .routers.cards import upsert_cards   # одна функция upsert для импорта и синхронизации

    async with SessionLocal() as lock_session:
        got = (await lock_session.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": LOCK_ID})).scalar()
        if not got:
            raise SyncBusy("Загрузка уже идёт")
        try:
            async with SessionLocal() as s:
                run = SyncRun(source="scryfall", trigger=trigger)
                s.add(run)
                await s.commit()
                own = client is None
                http = client or httpx.AsyncClient(headers=HEADERS, timeout=httpx.Timeout(60, read=300),
                                                   follow_redirects=True)
                try:
                    rows = await _download_oracle(http)
                    run.cards = await upsert_cards(s, rows)
                    if russian:
                        try:
                            run.russian = await _apply_russian(s, await _fetch_russian(http))
                        except httpx.HTTPError as e:     # без русских названий база всё равно полезна
                            run.error = f"Русские названия не загружены: {e!r}"[:2000]
                except Exception as e:  # noqa: BLE001
                    await s.rollback()
                    run.error = repr(e)[:2000]
                    log.exception("scryfall sync failed")
                finally:
                    if own:
                        await http.aclose()
                run.finished_at = datetime.now(timezone.utc)
                s.add(run)
                await s.commit()
                return run
        finally:
            await lock_session.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_ID})


async def last_run(session) -> SyncRun | None:
    return (await session.execute(select(SyncRun).where(SyncRun.source == "scryfall")
                                  .order_by(SyncRun.id.desc()).limit(1))).scalar_one_or_none()


async def is_running(session) -> bool:
    """Свободна ли блокировка: пробуем взять и сразу отпускаем."""
    got = (await session.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": LOCK_ID})).scalar()
    if got:
        await session.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_ID})
    return not got


async def due(session, now: datetime | None = None) -> bool:
    """Пора загружать: в базе нет карт MTG или последняя успешная загрузка старше недели."""
    now = now or datetime.now(timezone.utc)
    has_cards = (await session.execute(select(func.count()).select_from(Card).where(Card.game == "mtg"))).scalar_one()
    if not has_cards:
        return True
    last_ok = (await session.execute(select(func.max(SyncRun.finished_at)).where(
        SyncRun.source == "scryfall", SyncRun.cards > 0))).scalar_one()
    return last_ok is None or now - last_ok > REFRESH_EVERY


async def auto_sync_loop(check_every: int = 3600) -> None:
    """Для процесса бота: раз в час проверяет, не пора ли обновить базу."""
    await asyncio.sleep(30)    # дать базе и API подняться
    while True:
        try:
            async with SessionLocal() as s:
                need = await due(s)
            if need:
                run = await sync(trigger="auto")
                log.info("scryfall auto sync: %s cards, %s russian, error=%s", run.cards, run.russian, run.error)
        except SyncBusy:
            pass
        except Exception:  # noqa: BLE001
            log.exception("scryfall auto sync loop")
        await asyncio.sleep(check_every)
