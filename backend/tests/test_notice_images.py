"""Картинки оповещений: пул (организаторы и судьи), арт карты с подписью, выбор давно не использованной,
картинка в Telegram и VK (загрузка один раз). RUN_INTEGRATION=1."""
import io
import json
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs

import httpx
import pytest

from app import noticeimages as ni

needs_db = pytest.mark.skipif(not os.getenv("RUN_INTEGRATION"), reason="нужен PostgreSQL (RUN_INTEGRATION=1)")


def png(w=2400, h=1200, mode="RGBA") -> bytes:
    from PIL import Image
    out = io.BytesIO()
    Image.new(mode, (w, h), (200, 30, 30, 128) if mode == "RGBA" else (200, 30, 30)).save(out, "PNG")
    return out.getvalue()


def test_prepare_and_art_crop():
    data, w, h = ni.prepare_upload(png())
    assert (w, h) == (1600, 800) and data[:3] == b"\xff\xd8\xff"           # JPEG, длинная сторона 1600
    with pytest.raises(ValueError):
        ni.prepare_upload(b"not an image")
    assert ni.art_crop("https://cards.scryfall.io/normal/front/a/b/x.jpg?1") == "https://cards.scryfall.io/art_crop/front/a/b/x.jpg?1"
    assert ni.art_crop(None) is None and ni.art_crop("https://example.com/x.jpg") is None


if os.getenv("RUN_INTEGRATION"):
    from sqlalchemy import select

    from app import vk
    from app.bot import vk as vk_bot
    from app.bot.worker import deliver
    from app.config import settings
    from app.db import Base, SessionLocal, engine
    from app.main import app
    from app.models import Card, ClubVk, ClubVkChat, NoticeImage, OutboxMessage
    from app.secretbox import encrypt
    from tests.helpers import make_creator


class Fake:
    def __init__(self):
        self.calls = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith("https://cards.scryfall.io/"):
            self.calls.append(("scryfall", url))
            return httpx.Response(200, content=png(10, 10, "RGB"), headers={"content-type": "image/png"})
        if url.startswith("https://upload.vk.test/"):
            self.calls.append(("upload", url))
            return httpx.Response(200, json={"server": 7, "photo": "[{\"p\":1}]", "hash": "h1"})
        method = url.rsplit("/", 1)[-1]
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        self.calls.append((method, form))
        resp = {"photos.getMessagesUploadServer": {"upload_url": "https://upload.vk.test/up"},
                "photos.saveMessagesPhoto": [{"id": 55, "owner_id": -4242, "access_key": "kk"}],
                "messages.send": 1}.get(method, 1)
        return httpx.Response(200, json={"response": resp})

    def of(self, name):
        return [f for m, f in self.calls if m == name]


@pytest.fixture
async def ctx(monkeypatch):
    fake = Fake()
    monkeypatch.setattr(vk, "transport", httpx.MockTransport(fake))
    monkeypatch.setattr(settings, "public_base_url", "https://dragon.test")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        async def reg(n):
            r = await c.post("/auth/register", json={"email": f"n{n}@example.com", "password": "password1", "nickname": f"Ник{n}"})
            h = {"Authorization": f"Bearer {r.json()['access_token']}"}
            return h, (await c.get("/auth/me", headers=h)).json()
        org, _ = await reg(1)
        await make_creator(c, org)
        cid = (await c.post("/clubs", json={"name": "Дракон", "telegram_chat_id": "-100500"}, headers=org)).json()["id"]
        async with SessionLocal() as s:
            card = Card(game="mtg", external_id="o1", name="Lightning Bolt", name_lower="lightning bolt",
                        name_front="lightning bolt", image_url="https://cards.scryfall.io/normal/front/1/2/bolt.jpg",
                        extra={"artist": "Christopher Moeller"})
            s.add(card)
            await s.commit()
            card_id = card.id
        yield c, fake, org, cid, card_id, reg
    await engine.dispose()


async def outbox():
    async with SessionLocal() as s:
        return (await s.execute(select(OutboxMessage).order_by(OutboxMessage.id))).scalars().all()


async def announce(c, org, cid, name, game="mtg", days=2):
    when = (datetime.now(timezone.utc) + timedelta(days=days)).replace(tzinfo=None, microsecond=0).isoformat()
    r = await c.post("/tournaments", json={"club_id": cid, "name": name, "game": game, "starts_at": when}, headers=org)
    assert r.status_code == 201, r.text
    return [m for m in await outbox() if m.dedup_key and m.dedup_key.startswith(f"t-announce:{r.json()['id']}:")]


@needs_db
async def test_pool_rotation_and_telegram(ctx):
    c, fake, org, cid, card_id, reg = ctx
    base = f"/clubs/{cid}/notice-images"
    # без картинок - как раньше, текстом
    assert [m.photo_url for m in await announce(c, org, cid, "Без картинки")] == [None]

    up = await c.post(base, files={"file": ("club.png", png(), "image/png")}, data={"purpose": "announce", "game": "any"},
                      headers=org)
    assert up.status_code == 201, up.text
    up = up.json()
    assert (up["kind"], up["width"], up["url"]) == ("upload", 1600, f"https://dragon.test/api/media/notice/{up['id']}.jpg")
    media = await c.get(f"/media/notice/{up['id']}.jpg")
    assert media.status_code == 200 and media.headers["content-type"] == "image/jpeg"
    art = (await c.post(f"{base}/card", json={"card_id": card_id}, headers=org)).json()
    assert art["url"] == "https://cards.scryfall.io/art_crop/front/1/2/bolt.jpg" and art["game"] == "mtg"
    assert art["credit"] == "Арт: Christopher Moeller · Lightning Bolt"
    assert (await c.post(f"{base}/card", json={"card_id": card_id}, headers=org)).status_code == 409
    other = (await c.post(base, files={"file": ("r.png", png(800, 600, "RGB"), "image/png")},
                          data={"purpose": "other", "game": "berserk"}, headers=org)).json()

    # анонсы MTG: две картинки по очереди (давно не использованная первой), картинка итогов - не для анонсов
    used = []
    for i in range(4):
        msg = (await announce(c, org, cid, f"Турнир {i}"))[0]
        used.append(msg.photo_url)
        if msg.photo_url == art["url"]:
            assert "🎨 Арт: Christopher Moeller" in msg.text
    assert set(used[:2]) == {up["url"], art["url"]} and set(used[2:]) == {up["url"], art["url"]}
    assert other["url"] not in used
    # анонс Берсерка: арт MTG не подходит, только «любая игра»
    assert [m.photo_url for m in await announce(c, org, cid, "Берсерк", game="berserk")] == [up["url"]]
    # выключенная картинка не используется
    await c.patch(f"{base}/{up['id']}", json={"enabled": False}, headers=org)
    assert [m.photo_url for m in await announce(c, org, cid, "Ещё", game="berserk")] == [None]
    items = (await c.get(base, headers=org)).json()["items"]
    assert {i["id"]: i["uses"] for i in items}[art["id"]] == 2

    # права: судья клуба - может, обычный игрок - нет
    jh, judge = await reg(2)
    ph, _ = await reg(3)
    await c.put(f"/clubs/{cid}/judges", json={"player_no": judge["player_no"], "games": ["mtg"]}, headers=org)
    assert (await c.get(base, headers=jh)).status_code == 200
    assert (await c.get(base, headers=ph)).status_code == 403
    assert (await c.post(base, files={"file": ("x.txt", b"hello", "text/plain")}, headers=jh)).status_code == 400
    assert (await c.delete(f"{base}/{other['id']}", headers=jh)).status_code == 204

    # Telegram: короткий текст - фото с подписью, длинный - крупное превью над текстом
    class Bot:
        def __init__(self):
            self.sent = []

        async def send_photo(self, chat, photo, **kw):
            self.sent.append(("photo", photo))

        async def send_message(self, chat, text, **kw):
            self.sent.append(("text", kw["link_preview_options"]))
    bot = Bot()
    m = OutboxMessage(chat_id="-100500", text="коротко", photo_url=art["url"], parse_mode="HTML")
    await deliver(bot, m)
    m.text = "x" * 1500
    await deliver(bot, m)
    assert bot.sent[0] == ("photo", art["url"])
    lp = bot.sent[1][1]
    assert (lp.url, lp.show_above_text, lp.prefer_large_media) == (art["url"], True, True)


@needs_db
async def test_vk_attachment_uploaded_once(ctx):
    c, fake, org, cid, card_id, reg = ctx
    async with SessionLocal() as s:
        s.add(ClubVk(club_id=cid, group_id=4242, group_name="Дракон", group_token=encrypt("vk1.group")))
        s.add(ClubVkChat(club_id=cid, game="mtg", peer_id=2000000001))
        await s.commit()
    await c.post(f"/clubs/{cid}/notice-images/card", json={"card_id": card_id}, headers=org)
    for name in ("А", "Б"):
        await announce(c, org, cid, name)
    await vk_bot.process_batch()
    sends = fake.of("messages.send")
    assert [x["attachment"] for x in sends] == ["photo-4242_55_kk", "photo-4242_55_kk"]
    assert len(fake.of("photos.saveMessagesPhoto")) == 1 and len(fake.of("scryfall")) == 1   # загрузили один раз
    async with SessionLocal() as s:
        img = (await s.execute(select(NoticeImage))).scalar_one()
    assert (img.vk_attachment, img.vk_group_id) == ("photo-4242_55_kk", 4242)
    assert "🎨 Арт:" in sends[0]["message"] and json.loads(sends[0]["keyboard"])["inline"] is True
