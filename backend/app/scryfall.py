"""Загрузка базы карт MTG из Scryfall (https://scryfall.com/docs/api) - открытый источник.

1. Bulk-файл «Oracle Cards»: одна запись на каждую карту (~35 тыс.), с текстом, типом, форматами,
   ценами и ссылками на изображения в CDN Scryfall.
2. Русские печати через поиск (lang:ru): печатное название, тип и текст, привязка по oracle_id.

Запуск: кнопка в админке или автоматически (бот: при пустой базе и раз в неделю).
Параллельные запуски исключены advisory-блокировкой PostgreSQL; результат пишется в sync_runs.
"""
import asyncio
import gzip
import json
import logging
import tempfile
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import bindparam, func, select, text

from .cardimport import normalize_print, normalize_ru, normalize_scryfall
from .config import settings
from .db import SessionLocal
from .models import Card, CardPrint, SyncRun

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


def proxy() -> str | None:
    """Прокси до Scryfall: auto - тот же, что для Telegram (если задан); direct - без прокси."""
    p = (settings.scryfall_proxy or "").strip()
    if p in ("", "direct", "none"):
        return None
    if p == "auto":
        return settings.telegram_proxy or None
    return p


def new_client(**kw) -> httpx.AsyncClient:
    return httpx.AsyncClient(headers=HEADERS, timeout=httpx.Timeout(60, read=300), follow_redirects=True,
                             proxy=proxy(), **kw)


def explain(e: Exception) -> str:
    """Понятное админу описание сбоя загрузки (сырой текст ошибки - в конце, для логов)."""
    raw = repr(e)[:500]
    if isinstance(e, httpx.ConnectError) and ("address" in raw.lower() or "name" in raw.lower()):
        return ("Сервер не может найти адрес api.scryfall.com: у контейнера не работает DNS или нет выхода "
                "в интернет. При локальном запуске в Docker Desktop помогает перезапуск Docker Desktop, "
                "отключение VPN или явные DNS в docker-compose.yml. " + raw)
    if isinstance(e, (httpx.ConnectError, httpx.ConnectTimeout)):
        return "Нет соединения с api.scryfall.com: проверьте выход сервера в интернет и фаервол. " + raw
    if isinstance(e, httpx.TimeoutException):
        return "Scryfall слишком долго отвечает, попробуйте позже. " + raw
    if isinstance(e, httpx.HTTPStatusError):
        return f"Scryfall ответил ошибкой {e.response.status_code}, попробуйте позже. " + raw
    return raw


def _open_bulk(path: str):
    """Файл выгрузки как текстовый поток: распаковывает gzip, если он сжат."""
    with open(path, "rb") as f:
        compressed = f.read(2) == b"\x1f\x8b"
    return gzip.open(path, "rt", encoding="utf-8") if compressed else open(path, encoding="utf-8")


def iter_bulk(path: str):
    """Карты из выгрузки Scryfall. Поддерживает оба формата: JSON-массив (старый download_uri)
    и JSON Lines, по объекту на строку (jsonl_download_uri, в т.ч. .jsonl.gz)."""
    with _open_bulk(path) as f:
        head = f.read(4096).lstrip()
    if head.startswith("["):
        import ijson
        with _open_bulk(path) as f:
            yield from ijson.items(f, "item")
        return
    with _open_bulk(path) as f:
        for line in f:
            line = line.strip().rstrip(",")
            if line and line not in ("[", "]"):
                yield json.loads(line)


def _parse_bulk(path: str) -> list[dict]:
    out = []
    for obj in iter_bulk(path):
        card = normalize_scryfall(obj)
        if card:
            out.append(card)
    return out


def bulk_url(meta: dict, kind: str = "oracle_cards") -> str:
    """Ссылка на выгрузку: новый формат (jsonl_download_uri) или старый (download_uri)."""
    item = next((x for x in meta.get("data", []) if x.get("type") == kind), None)
    if not item:
        raise ValueError(f"Scryfall не отдал выгрузку {kind}")
    url = item.get("jsonl_download_uri") or item.get("download_uri")
    if not url:
        raise ValueError(f"В описании выгрузки {kind} нет ссылки на файл: поля {sorted(item)}")
    return url


async def _download_oracle(client: httpx.AsyncClient) -> list[dict]:
    meta = (await client.get(f"{API}/bulk-data")).raise_for_status().json()
    uri = bulk_url(meta)
    with tempfile.NamedTemporaryFile(suffix=".bulk") as tmp:
        async with client.stream("GET", uri) as resp:
            resp.raise_for_status()
            async for chunk in resp.aiter_bytes():
                tmp.write(chunk)
        tmp.flush()
        cards = await asyncio.to_thread(_parse_bulk, tmp.name)   # разбор не блокирует event loop
    if not cards:
        raise ValueError("Выгрузка Scryfall скачалась, но карт в ней не найдено")
    return cards


PRINT_BATCH = 1000                         # 1000 строк × 17 полей - в пределах 32767 параметров asyncpg


async def _download_bulk(client: httpx.AsyncClient, kind: str, path: str) -> None:
    meta = (await client.get(f"{API}/bulk-data")).raise_for_status().json()
    uri = bulk_url(meta, kind)
    with open(path, "wb") as f:
        async with client.stream("GET", uri) as resp:
            resp.raise_for_status()
            async for chunk in resp.aiter_bytes():
                f.write(chunk)


async def _sync_prints(client: httpx.AsyncClient, session) -> int:
    """Все издания карт (выгрузка «Default Cards», ~100 тыс.): скачиваем во временный файл и пишем пачками,
    не держа весь файл в памяти. Привязка к карте - по oracle_id."""
    from itertools import islice

    from sqlalchemy.dialects.postgresql import insert as pg_insert
    ids = dict((await session.execute(select(Card.external_id, Card.id).where(Card.game == "mtg"))).all())
    total = 0
    with tempfile.NamedTemporaryFile(suffix=".bulk") as tmp:
        await _download_bulk(client, "default_cards", tmp.name)
        it = iter_bulk(tmp.name)
        while True:
            chunk = await asyncio.to_thread(lambda: list(islice(it, PRINT_BATCH)))   # чтение файла - в потоке
            if not chunk:
                break
            rows = []
            for obj in chunk:
                p = normalize_print(obj)
                cid = ids.get(p.pop("oracle_id")) if p else None
                if cid:
                    rows.append({**p, "card_id": cid})
            if not rows:
                continue
            stmt = pg_insert(CardPrint).values(rows)
            stmt = stmt.on_conflict_do_update(index_elements=[CardPrint.scryfall_id], set_={
                c: stmt.excluded[c] for c in rows[0] if c != "scryfall_id"})
            await session.execute(stmt)
            await session.commit()
            total += len(rows)
    return total


SEARCH_PAUSE = 0.6                         # поиск у Scryfall строже: не больше ~2 запросов в секунду
RETRIES = 6


async def _get_with_retry(client: httpx.AsyncClient, url: str, params: dict | None) -> httpx.Response:
    """429 (слишком часто) и 5xx - ждём (Retry-After или 2, 4, 8… секунд) и повторяем."""
    for attempt in range(RETRIES):
        r = await client.get(url, params=params)
        if r.status_code != 429 and r.status_code < 500:
            return r
        wait = float(r.headers.get("Retry-After") or 0) or 2 ** (attempt + 1)
        log.warning("Scryfall ответил %s, повтор через %.0f с", r.status_code, wait)
        await asyncio.sleep(min(wait, 60))
    return r


class PartialRussian(Exception):
    """Часть русских названий получена, но Scryfall перестал отвечать: применяем то, что есть."""

    def __init__(self, got: dict, cause: Exception):
        super().__init__(str(cause))
        self.got, self.cause = got, cause


async def _fetch_russian(client: httpx.AsyncClient, max_pages: int = 400) -> dict[str, dict]:
    """oracle_id -> русские поля. Берём первую найденную русскую печать каждой карты."""
    out: dict[str, dict] = {}
    url: str | None = f"{API}/cards/search"
    params: dict | None = {"q": "lang:ru", "unique": "cards", "order": "name"}
    for _ in range(max_pages):
        if not url:
            break
        r = await _get_with_retry(client, url, params)
        if r.status_code == 404:          # ничего не найдено
            break
        try:
            r.raise_for_status()
        except httpx.HTTPStatusError as e:
            if out:
                raise PartialRussian(out, e) from e
            raise
        page = r.json()
        for obj in page.get("data", []):
            ru = normalize_ru(obj)
            if ru:
                out.setdefault(ru["oracle_id"], ru)
        url, params = (page.get("next_page"), None) if page.get("has_more") else (None, None)
        await asyncio.sleep(SEARCH_PAUSE)
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
    await clear_fake_russian(conn)
    await session.commit()
    return len(rows)


CLEAR_FAKE_RU = text("UPDATE cards SET name_ru = NULL, name_ru_lower = NULL, name_ru_front = NULL "
                     "WHERE game = 'mtg' AND name_ru IS NOT NULL "
                     "AND (lower(btrim(name_ru)) = lower(btrim(name)) OR name_ru_lower = name_lower)")


async def clear_fake_russian(conn) -> int:
    """В части источников у split/двусторонних карт «русское» название = английское. Это не перевод: убираем,
    чтобы название не дублировалось, а поиск is:russian не считал такие карты русскими."""
    return (await conn.execute(CLEAR_FAKE_RU)).rowcount


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
                http = client or new_client()
                try:
                    rows = await _download_oracle(http)
                    run.cards = await upsert_cards(s, rows)
                    del rows
                    await s.commit()                     # карты сохранены, даже если издания не загрузятся
                    errors = []
                    try:
                        run.prints = await _sync_prints(http, s)
                    except Exception as e:  # noqa: BLE001  без изданий база карт всё равно полезна
                        await s.rollback()
                        errors.append(f"Издания не загружены. {explain(e)}")
                        log.exception("scryfall prints failed")
                    if russian:
                        try:
                            run.russian = await _apply_russian(s, await _fetch_russian(http))
                        except PartialRussian as p:      # часть получили - применяем, остальное в следующий раз
                            run.russian = await _apply_russian(s, p.got)
                            errors.append(f"Русские названия загружены частично. {explain(p.cause)}")
                        except httpx.HTTPError as e:     # без русских названий база всё равно полезна
                            errors.append(f"Русские названия не загружены. {explain(e)}")
                    run.error = " ".join(errors)[:2000] or None
                except Exception as e:  # noqa: BLE001
                    await s.rollback()
                    run.error = explain(e)[:2000]
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
