"""Картинки карт и символы маны Scryfall через наш сервер.

Из России CDN Scryfall (cards.scryfall.io, svgs.scryfall.io) отвечает медленно или не отвечает, и браузеры
посетителей не дожидаются картинок. Сервер скачивает картинку один раз (через прокси Scryfall, если он
настроен), кладёт на диск и дальше отдаёт сам - с долгим кэшем в браузере.

  /img/<размер>/<front|back>/<a>/<b>/<uuid>.jpg   - картинка карты (normal, large, small, art_crop, png, border_crop)
  /img/symbol/<код>.svg                           - символ маны ({W}, {2/U}, {T}…)
"""
import asyncio
import logging
import os
import re
import time
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from .. import scryfall
from ..config import settings

router = APIRouter(tags=["images"])
log = logging.getLogger("images")

KINDS = {"small", "normal", "large", "png", "art_crop", "border_crop"}
CARD_PATH = re.compile(r"^(front|back)/[0-9a-f]/[0-9a-f]/[0-9a-f-]{36}\.(jpg|png)$")
SYMBOL = re.compile(r"^[A-Z0-9½∞]{1,8}$")
CACHE_HEADERS = {"Cache-Control": "public, max-age=2592000, immutable"}
_locks: dict[str, asyncio.Lock] = {}
transport: httpx.AsyncBaseTransport | None = None     # подмена в тестах
_writes = 0


def _cache_path(*parts: str) -> Path:
    return Path(settings.image_cache_dir).joinpath(*parts)


async def _fetch(url: str) -> bytes:
    """Сначала через прокси Scryfall (если есть), при сбое - напрямую."""
    errors = []
    for prx in dict.fromkeys([scryfall.proxy(), None]):
        try:
            net = {"transport": transport} if transport else {"proxy": prx}
            async with httpx.AsyncClient(**net, timeout=httpx.Timeout(10, read=30), follow_redirects=True,
                                         headers={"User-Agent": scryfall.HEADERS["User-Agent"], "Accept": "image/*"}) as c:
                r = await c.get(url)
            r.raise_for_status()
            return r.content
        except httpx.HTTPError as e:
            errors.append(f"{'прокси' if prx else 'напрямую'}: {type(e).__name__}")
    raise HTTPException(502, "Scryfall не отдал картинку (" + "; ".join(errors) + ")")


def _prune() -> None:
    """Кэш больше лимита - удаляем давно не открывавшиеся файлы (по времени последнего доступа)."""
    root = Path(settings.image_cache_dir)
    limit = settings.image_cache_max_gb * 1024 ** 3
    files = [(p.stat().st_atime, p.stat().st_size, p) for p in root.rglob("*") if p.is_file()]
    total = sum(s for _, s, _ in files)
    for _, size, p in sorted(files):
        if total <= limit * 0.9:
            break
        try:
            p.unlink()
            total -= size
        except OSError:
            pass


async def _serve(key: tuple[str, ...], url: str, media: str) -> FileResponse:
    global _writes
    path = _cache_path(*key)
    if not path.exists():
        lock = _locks.setdefault(str(path), asyncio.Lock())
        async with lock:                               # одну картинку качаем один раз, даже если её просят 20 человек
            if not path.exists():
                data = await _fetch(url)
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
                tmp.write_bytes(data)
                tmp.replace(path)
                _writes += 1
                if _writes % 500 == 0:
                    await asyncio.to_thread(_prune)
        _locks.pop(str(path), None)
    else:
        try:
            os.utime(path, (time.time(), path.stat().st_mtime))   # отметка «недавно нужен» для очистки кэша
        except OSError:
            pass
    return FileResponse(path, media_type=media, headers=CACHE_HEADERS)


@router.get("/img/symbol/{code}.svg")
async def symbol(code: str):
    if not SYMBOL.match(code):
        raise HTTPException(404, "Нет такого символа")
    return await _serve(("symbols", f"{code}.svg"), f"https://svgs.scryfall.io/card-symbols/{code}.svg", "image/svg+xml")


@router.get("/img/{kind}/{path:path}")
async def card_image(kind: str, path: str):
    if kind not in KINDS or not CARD_PATH.match(path):
        raise HTTPException(404, "Нет такой картинки")
    media = "image/png" if path.endswith(".png") else "image/jpeg"
    return await _serve((kind, *path.split("/")), f"https://cards.scryfall.io/{kind}/{path}", media)
