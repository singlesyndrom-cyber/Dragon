"""«Берсерк» с ProBerserk.ru: разбор страницы выпуска (без БД) и загрузка в базу (PostgreSQL)."""
import os
from pathlib import Path

import pytest

PAGE = (Path(__file__).parent / "fixtures" / "proberserk_edition.html").read_text(encoding="utf-8")


def test_parse_edition_page():
    from app import berserk
    assert berserk.parse_editions(PAGE) == [("/edition/aa7e3", "Война стихий"), ("/edition/e2ba8", "Легенды Лаара"),
                                            ("/edition/ab007", "Гибель Богов")]
    cards = {c["name"]: c for c in berserk.parse_edition(PAGE, "Гибель Богов")}
    assert list(cards) == ["Изобретатель Братства", "Преторианец", "Бернхольм", "Бешеный карлик"]
    inv = cards["Изобретатель Братства"]
    assert inv["external_id"] == "7/1" and inv["extra"]["proberserk_id"] == "7cdf0cb7a77e4a459b7281e7d9560846"
    assert inv["set_code"] == "7" and inv["type_line"] == "Существо · Братство" and inv["cmc"] == 3
    assert inv["rarity"] == "uncommon" and inv["image_url"] == "https://proberserk.ru/images/cards/7/1.jpg"
    assert inv["extra"]["health"] == 7 and inv["extra"]["move"] == 1 and inv["extra"]["strike"] == "1-1-2"
    assert inv["extra"]["unique"] and not inv["extra"]["elite"] and inv["extra"]["elements"] == ["Степи"]
    assert inv["text"].startswith("{second}: Начинает бой с {counter}. Заряд. X {counter} {tap}: Воздействие \"магнум опус\"")
    pr = cards["Преторианец"]
    assert pr["extra"]["icons"] == {"armor": 1} and "Строй: {ova}1.\n{instant}: Если" in pr["text"]
    land = cards["Бернхольм"]
    assert land["extra"]["elite"] and land["extra"]["health"] is None and land["extra"]["move"] is None
    assert land["rarity"] == "rare"
    assert cards["Бешеный карлик"]["extra"]["proberserk_id"] == "1607e8a5-6983-45c4-8611-49eeaaacfaf6"   # id с дефисами
    assert cards["Бешеный карлик"]["extra"]["elements"] == ["Нейтральная"] and cards["Бешеный карлик"]["extra"]["class"] is None


def test_icons_in_text():
    from app import berserk
    assert berserk.mark_icons("Не более 4counter.\r\ncountertap: Воздействие. wolf: прыжок, ova1. Пиво lager") == \
        "Не более 4{counter}.\n{counter}{tap}: Воздействие. {wolf}: прыжок, {ova}1. Пиво lager"


pytestmark_db = pytest.mark.skipif(not os.getenv("RUN_INTEGRATION"), reason="нужен PostgreSQL (RUN_INTEGRATION=1)")

if os.getenv("RUN_INTEGRATION"):
    import httpx

    from app import berserk
    from app.db import Base, engine
    from app.main import app


@pytest.fixture
async def client():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await engine.dispose()


@pytestmark_db
async def test_sync_search_deck_and_images(client, tmp_path, monkeypatch):
    from sqlalchemy import text as sql
    from app.db import SessionLocal
    async with SessionLocal() as s:          # карта со старым ключом - после загрузки должна исчезнуть
        await s.execute(sql("INSERT INTO cards (game, external_id, name, name_lower, name_front, is_game_changer, extra) "
                            "VALUES ('berserk', 'dc921', 'Старая', 'старая', 'старая', false, '{}')"))
        await s.commit()
    seen: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.startswith("/edition/"):
            return httpx.Response(200, text=PAGE if request.url.path == "/edition/ab007" or request.url.path == berserk.START
                                  else "<html>нет таблицы</html>")
        return httpx.Response(404)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), headers=berserk.HEADERS) as http:
        run = await berserk.sync(client=http, pause=0)
    assert run.error is None and run.cards == 4
    assert all(r.headers["user-agent"].startswith("DragonClub") for r in seen)
    assert [r.url.path for r in seen] == ["/edition/aa7e3", "/edition/aa7e3", "/edition/e2ba8", "/edition/ab007"]

    assert not (await client.get("/cards/search", params={"q": "старая", "game": "berserk"})).json()["items"]
    stats = (await client.get("/cards/stats")).json()
    assert stats["games"]["berserk"]["cards"] == 4 and stats["berserk_updated"]

    def names(q):
        return [c["name"] for c in client_results[q]]
    client_results = {}
    for q in ("el:нейтральная", "класс:братство", "hp>=9", "s:7 mv<=2", "r:редкая", "карлик"):
        r = (await client.get("/cards/search", params={"q": q, "game": "berserk"})).json()
        client_results[q] = r["items"]
    assert names("el:нейтральная") == ["Бешеный карлик"]
    assert names("класс:братство") == ["Изобретатель Братства"]
    assert names("hp>=9") == ["Преторианец"]
    assert names("s:7 mv<=2") == ["Бернхольм"]
    assert names("r:редкая") == ["Бернхольм"]
    assert client_results["карлик"][0]["bk"]["strike"] == "1-2-2"

    # колода «Берсерка»: формат по умолчанию, проверка размера и копий
    r = await client.post("/auth/register", json={"email": "b@t.io", "password": "password1", "nickname": "Берсеркер"})
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    deck = (await client.post("/decks", json={"name": "Степи", "game": "berserk",
                                              "text": "4 Преторианец\n3 Изобретатель Братства"}, headers=h)).json()
    assert deck["unmatched"] == []
    d = (await client.get(f"/decks/{deck['id']}", headers=h)).json()
    assert d["format"] == "berserk"
    texts = " ".join(p["text"] for p in d["problems"])
    assert "нужно не меньше 30" in texts and "Больше трёх копий: Преторианец ×4" in texts
    card = next(c for c in d["cards"] if c["name"] == "Преторианец")["card"]
    assert card["bk"]["icons"] == {"armor": 1} and card["text"].startswith("Рывок")
    assert (await client.patch(f"/decks/{deck['id']}", json={"format": "commander"}, headers=h)).status_code == 400
    # лимитед: копий сколько угодно; констрактед: не больше 50 карт
    r = (await client.patch(f"/decks/{deck['id']}", json={"format": "berserk_limited"}, headers=h)).json()
    assert not any("копий" in p["text"] for p in r["problems"])
    await client.put(f"/decks/{deck['id']}", headers=h, json={"name": "Степи", "game": "berserk", "format": "berserk",
                                                               "text": "\n".join(["3 Преторианец"] * 17) + "\n2 Бернхольм"})
    texts = " ".join(p["text"] for p in (await client.get(f"/decks/{deck['id']}", headers=h)).json()["problems"])
    assert "В колоде 53 карт, можно не больше 50" in texts

    # картинки - через наш сервер, с кэшем
    from app.config import settings
    from app.routers import images
    calls: list = []

    def img(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, content=b"JPEG")
    monkeypatch.setattr(settings, "image_cache_dir", str(tmp_path))
    monkeypatch.setattr(images, "transport", httpx.MockTransport(img))
    for _ in range(2):
        r = await client.get("/img/bk/cards/7/1.jpg")
        assert r.status_code == 200 and r.content == b"JPEG"
    assert calls == ["https://proberserk.ru/images/cards/7/1.jpg"]
    assert (await client.get("/img/bk/icons/icon-tap.png")).status_code == 200
    assert (await client.get("/img/bk/other/1.jpg")).status_code == 404 and (await client.get("/img/bk/cards/7/1.exe")).status_code == 404
