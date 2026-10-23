"""Картинки оповещений клуба: пул, выбор «давно не использованной», подготовка файлов и вложения VK.

purpose: announce - анонсы турниров (свои картинки и арты карт); other - итоги и новости.
game: mtg / berserk / any. Для турнира подходят картинки его игры и «любой игры».
"""
import io
import re
from datetime import datetime, timezone

import httpx
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from . import vk
from .config import settings
from .models import NoticeImage

PURPOSES = {"announce": "Анонсы турниров", "other": "Итоги и новости"}
GAMES = {"any": "Любая игра", "mtg": "Magic: The Gathering", "berserk": "Берсерк"}
MAX_SIDE = 1600
MAX_UPLOAD = 15 * 1024 * 1024
MEDIA_RE = re.compile(r"/media/notice/(\d+)\.jpg$")


def art_crop(image_url: str | None) -> str | None:
    """Scryfall: та же картинка карты, но только арт без рамки (…/normal/… -> …/art_crop/…)."""
    if not image_url or "/normal/" not in image_url:
        return None
    return image_url.replace("/normal/", "/art_crop/", 1)


def prepare_upload(raw: bytes) -> tuple[bytes, int, int]:
    """Любая картинка -> JPEG не больше 1600 px по длинной стороне (повёрнутый по EXIF, без прозрачности)."""
    from PIL import Image, ImageOps, UnidentifiedImageError
    try:
        img = Image.open(io.BytesIO(raw))
        img = ImageOps.exif_transpose(img)
    except (UnidentifiedImageError, OSError) as e:
        raise ValueError("Это не картинка или формат не поддерживается") from e
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (20, 24, 38))
        bg.paste(img, mask=img.split()[-1])
        img = bg
    else:
        img = img.convert("RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=85, optimize=True, progressive=True)
    return out.getvalue(), img.width, img.height


def public_url(img: NoticeImage) -> str | None:
    if img.source_url:
        return img.source_url
    base = settings.public_base_url.rstrip("/")
    return f"{base}/api/media/notice/{img.id}.jpg" if base else None


async def pick(session: AsyncSession, club_id: int, purpose: str, game: str | None) -> NoticeImage | None:
    """Давно не использованная картинка (впервые - раньше всех), среди равных - случайная."""
    q = select(NoticeImage).where(NoticeImage.club_id == club_id, NoticeImage.purpose == purpose,
                                  NoticeImage.enabled.is_(True))
    if game:
        q = q.where(or_(NoticeImage.game == game, NoticeImage.game == "any"))
    img = (await session.execute(q.order_by(NoticeImage.last_used_at.asc().nulls_first(), func.random())
                                 .limit(1))).scalar_one_or_none()
    if img:
        img.uses = (img.uses or 0) + 1
        img.last_used_at = datetime.now(timezone.utc)
    return img


async def for_notice(session: AsyncSession, club_id: int, purpose: str, game: str | None,
                     text: str) -> tuple[str | None, str]:
    """(адрес картинки, текст с подписью художника) для оповещения; без картинки - (None, текст)."""
    img = await pick(session, club_id, purpose, game)
    url = public_url(img) if img else None
    if not url:
        return None, text
    return url, (f"{text}\n\n🎨 {img.credit}" if img.credit else text)


async def find_by_url(session: AsyncSession, club_id: int, url: str) -> NoticeImage | None:
    m = MEDIA_RE.search(url)
    if m:
        img = await session.get(NoticeImage, int(m.group(1)))
        return img if img and img.club_id == club_id else None
    return (await session.execute(select(NoticeImage).where(
        NoticeImage.club_id == club_id, NoticeImage.source_url == url).limit(1))).scalar_one_or_none()


async def image_bytes(img: NoticeImage) -> bytes:
    if img.data:
        return img.data
    async with vk.client() as c:          # тот же клиент, что для VK (в тестах - подменённый транспорт)
        # Scryfall без осмысленного User-Agent отвечает 400 - те же заголовки, что при загрузке базы карт
        from .scryfall import HEADERS
        r = await c.get(img.source_url, follow_redirects=True,
                        headers={"User-Agent": HEADERS["User-Agent"], "Accept": "image/*"})
    r.raise_for_status()
    return r.content


async def vk_attachment(session: AsyncSession, club_id: int, group_id: int, token: str, peer_id: int,
                        url: str) -> str | None:
    """Вложение VK для картинки: загружаем один раз на сообщество и запоминаем photo<owner>_<id>_<key>."""
    img = await find_by_url(session, club_id, url)
    if not img:
        return None
    if img.vk_attachment and img.vk_group_id == group_id:
        return img.vk_attachment
    srv = await vk.call("photos.getMessagesUploadServer", token, peer_id=peer_id)
    data = await image_bytes(img)
    try:
        async with vk.client() as c:
            up = (await c.post(srv["upload_url"], files={"photo": ("image.jpg", data, "image/jpeg")})).json()
    except (httpx.HTTPError, ValueError) as e:
        raise vk.VkError(0, f"не удалось загрузить картинку в VK ({e})")
    saved = await vk.call("photos.saveMessagesPhoto", token, server=up.get("server"), photo=up.get("photo"),
                          hash=up.get("hash"))
    p = saved[0]
    att = f"photo{p['owner_id']}_{p['id']}" + (f"_{p['access_key']}" if p.get("access_key") else "")
    img.vk_attachment, img.vk_group_id = att, group_id
    return att
