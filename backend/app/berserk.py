"""База карт классического «Берсерка» с ProBerserk.ru (https://proberserk.ru).

Права на игру и изображения принадлежат «Миру Хобби» (у клуба есть разрешение на изображения); база собрана
сообществом ProBerserk - на сайте и в карточках указываем источник со ссылкой.

Бережная загрузка: все данные карт есть в таблице на странице выпуска, поэтому запросов всего по одному на
выпуск (~13), по одному за раз с паузой. Картинки отдельно не качаем: наш сервер забирает картинку по первому
просмотру и дальше отдаёт из своего кэша (/img/bk/...). Сбой ответа - загрузка останавливается.
"""
import asyncio
import html
import logging
import re
from datetime import datetime, timezone

import httpx
from sqlalchemy import delete, select, text

from .cardimport import _finalize
from .db import SessionLocal
from .models import Card, SyncRun

log = logging.getLogger("berserk")

SITE = "https://proberserk.ru"
SOURCE = "proberserk"
HEADERS = {"User-Agent": "DragonClub/1.0 (+https://dragonclub.games; card base of the club, source credited)",
           "Accept": "text/html"}
LOCK_ID = 7_420_002
PAUSE = 3.0                                  # секунд между запросами: нагрузка как у читающего человека
START = "/edition/aa7e3"                     # любая страница выпуска: в меню - список всех выпусков

EDITION_LINK = re.compile(r'href="(/edition/[A-Za-z0-9]+)"[^>]*>([^<]+)</a>')
TABLE = re.compile(r'<table id="datatable".*?<tbody[^>]*>(.*?)</tbody>', re.S)
ROW = re.compile(r"<tr>(.*?)</tr>", re.S)
CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
CARD_LINK = re.compile(r'href="/card/([A-Za-z0-9-]+)".*?/images/cards/([^\']+)\'[^"]*"\s*>([^<]+)</a>', re.S)
HIDDEN = re.compile(r'<span class="d-none">(.*?)</span>', re.S)
ALT = re.compile(r'<img[^>]*src="([^"]+)"[^>]*alt="([^"]*)"', re.S)
TAGS = re.compile(r"<[^>]+>")

RARITY = {"обычная": "common", "необычная": "uncommon", "редкая": "rare", "ультраредкая": "ultra",
          "промо": "special", "фойл": "special"}
# значки в тексте карт (на сайте - картинки с этими именами)
ICONS = ("tap", "counter", "instant", "first", "second", "strike", "health", "move", "armor", "ova", "ovz", "ovs",
         "uchr", "direct", "regen", "stamina", "zom", "zoz", "zor", "zov", "zot", "zoo", "zoal", "elite", "ordinary",
         "wolf", "human")
LATIN_RUN = re.compile(r"(?<![A-Za-z])[a-z]+(?![A-Za-z])")     # значки иногда слиты: «countertap», «4counter»


def _split_icons(run: str) -> list[str] | None:
    """«countertap» -> ["counter", "tap"]; None, если это не цепочка значков (обычное латинское слово)."""
    if not run:
        return []
    for icon in sorted(ICONS, key=len, reverse=True):
        if run.startswith(icon):
            rest = _split_icons(run[len(icon):])
            if rest is not None:
                return [icon, *rest]
    return None


class SyncBusy(Exception):
    pass


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(TAGS.sub(" ", s))).strip()


def mark_icons(s: str) -> str:
    """«tap: Выстрел» -> «{tap}: Выстрел», «ova1» -> «{ova}1»: значки отрисует сайт."""
    s = html.unescape(s).replace("\r", "")
    s = LATIN_RUN.sub(lambda m: "".join("{" + t + "}" for t in parts) if (parts := _split_icons(m.group(0)))
                      else m.group(0), s)
    return "\n".join(re.sub(r"[ \t]+", " ", ln).strip() for ln in s.split("\n")).strip()


def parse_editions(page: str) -> list[tuple[str, str]]:
    """[(путь, название)] выпусков из меню, по порядку, без повторов."""
    out: dict[str, str] = {}
    for path, title in EDITION_LINK.findall(page):
        out.setdefault(path, re.sub(r"^\d+\.\s*", "", html.unescape(title).replace("\xa0", " ").strip()))
    return list(out.items())


def parse_edition(page: str, set_name: str) -> list[dict]:
    """Карты из таблицы выпуска: одна строка таблицы - одна карта."""
    m = TABLE.search(page)
    if not m:
        return []
    cards = []
    for row in ROW.findall(m.group(1)):
        cells = CELL.findall(row)
        if len(cells) < 11:
            continue
        link = CARD_LINK.search(cells[1])
        if not link:
            continue
        card_id, img, name = link.group(1), link.group(2), html.unescape(link.group(3)).strip()
        hidden = HIDDEN.search(cells[1])
        number = _clean(cells[0])
        set_code = img.split("/")[0].lower()
        cost_icons = ALT.findall(cells[3])
        elite = any(a == "Элитная" for _, a in cost_icons)
        unique = any("unique" in src for src, _ in cost_icons)
        cost = re.match(r"\s*(\d+)", TAGS.sub(" ", cells[3]))
        elements = [_clean(x) for x in HIDDEN.findall(cells[4]) if _clean(x)] or [a for _, a in ALT.findall(cells[4]) if a]
        rarity_ru = (HIDDEN.search(cells[5]).group(1) if HIDDEN.search(cells[5]) else "").split("-", 1)[-1].strip().lower()
        kind = _clean(cells[6])
        klass = _clean(cells[2])
        icons: dict[str, int | bool] = {}
        for token in (_clean(HIDDEN.search(cells[10]).group(1)) if HIDDEN.search(cells[10]) else "").split():
            k, _, v = token.partition(":")
            icons[k] = int(v) if v.isdigit() else True
        health, strike = _clean(cells[7]), _clean(cells[9])
        move = _clean(HIDDEN.sub(" ", cells[8]))          # у артефактов и местностей тут значок типа, не число
        c = {
            # номер карты на ProBerserk короткий и бывает одинаковым в разных выпусках - ключ по картинке выпуска
            "external_id": img.rsplit(".", 1)[0][:64], "name": name, "set_code": set_code, "set_name": set_name,
            "type_line": f"{kind} · {klass}" if klass else kind,
            "mana_cost": str(int(cost.group(1))) if cost else None, "cmc": float(cost.group(1)) if cost else None,
            "text": mark_icons(hidden.group(1)) if hidden else None,
            "rarity": RARITY.get(rarity_ru, rarity_ru or None),
            "image_url": f"{SITE}/images/cards/{img}",
            "scryfall_uri": f"{SITE}/card/{card_id}",           # ссылка на источник карты
            "extra": {"number": number, "elements": elements, "elite": elite, "unique": unique, "class": klass or None,
                      "kind": kind, "health": int(health) if health.isdigit() else None,
                      "move": int(move) if move.isdigit() else None, "strike": strike or None,
                      "icons": icons, "source": "ProBerserk.ru", "proberserk_id": card_id},
        }
        cards.append(_finalize(c, "berserk"))
    return cards


async def _get(client: httpx.AsyncClient, path: str) -> str:
    r = await client.get(SITE + path)
    r.raise_for_status()
    return r.text


async def fetch_all(client: httpx.AsyncClient, pause: float = PAUSE) -> list[dict]:
    editions = parse_editions(await _get(client, START))
    if not editions:
        raise ValueError("На ProBerserk не нашлось списка выпусков - возможно, изменилась вёрстка сайта")
    cards: list[dict] = []
    for path, title in editions:
        await asyncio.sleep(pause)
        got = parse_edition(await _get(client, path), title)
        log.info("ProBerserk %s: %d карт", title, len(got))
        cards += got
    if not cards:
        raise ValueError("Страницы выпусков загрузились, но карт в таблицах не найдено - изменилась вёрстка")
    return cards


async def sync(trigger: str = "admin", client: httpx.AsyncClient | None = None, pause: float = PAUSE) -> SyncRun:
    from .routers.cards import upsert_cards
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
                http = client or httpx.AsyncClient(headers=HEADERS, timeout=httpx.Timeout(15, read=60),
                                                   follow_redirects=True)
                try:
                    cards = await fetch_all(http, pause)
                    run.cards = await upsert_cards(s, cards)
                    # карты, которых больше нет в источнике (или со старым ключом), убираем; колоды теряют только ссылку
                    keep = {c["external_id"] for c in cards}
                    await s.execute(delete(Card).where(Card.game == "berserk", Card.external_id.not_in(keep)))
                    await s.commit()
                except Exception as e:  # noqa: BLE001
                    await s.rollback()
                    run.error = explain(e)[:2000]
                    log.exception("proberserk sync failed")
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
    return (await session.execute(select(func.count()).select_from(Card).where(Card.game == "berserk"))).scalar_one()
