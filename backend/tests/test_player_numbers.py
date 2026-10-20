"""Номер игрока: выдача, поиск, запись на турнир, гости, аукцион. Запуск: RUN_INTEGRATION=1 и DATABASE_URL."""
import os

import pytest

pytestmark = pytest.mark.skipif(not os.getenv("RUN_INTEGRATION"), reason="нужен PostgreSQL (RUN_INTEGRATION=1)")

if os.getenv("RUN_INTEGRATION"):
    import httpx
    from sqlalchemy import select, text

    from app import auction_service as svc
    from app.auction_texts import lot_caption, rating_card
    from app.db import Base, SessionLocal, engine
    from app.main import app
    from app.models import User
    from app.schema import sync_schema


@pytest.fixture
async def client():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await engine.dispose()


async def reg(c, n):
    r = await c.post("/auth/register", json={"email": f"p{n}@example.com", "password": "password1", "nickname": f"Игрок{n}"})
    assert r.status_code == 200, r.text
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    return h, (await c.get("/auth/me", headers=h)).json()


async def test_numbers_are_sequential_from_1001(client):
    _, a = await reg(client, 1)
    _, b = await reg(client, 2)
    assert a["player_no"] == 1001 and b["player_no"] == 1002
    # аккаунт из Telegram-бота тоже получает номер
    async with SessionLocal() as s:
        tg = await svc.get_or_create_tg_user(s, 777, "tg_user", "TG")
        assert tg.player_no == 1003


async def test_add_by_number_and_guests_have_none(client):
    org, _ = await reg(client, 1)
    _, other = await reg(client, 2)
    club = (await client.post("/clubs", json={"name": "Номерной клуб"}, headers=org)).json()
    tid = (await client.post("/tournaments", json={"club_id": club["id"], "name": "Пятница", "format": "swiss",
                                                   "rounds": 2}, headers=org)).json()["id"]
    # игрок другого клуба находится по точному номеру, хотя в этом клубе ещё не играл
    hints = (await client.get(f"/clubs/{club['id']}/players?q=№{other['player_no']}", headers=org)).json()
    assert hints[0]["user_id"] == other["id"] and hints[0]["member"] is False and hints[0]["player_no"] == 1002
    r = await client.post(f"/tournaments/{tid}/players", json={"player_no": other["player_no"]}, headers=org)
    assert r.status_code == 201 and r.json()["nickname"] == "Игрок2" and r.json()["player_no"] == 1002
    assert (await client.post(f"/tournaments/{tid}/players", json={"player_no": 999999}, headers=org)).status_code == 404
    # гость номера не получает и не сдвигает нумерацию
    r = await client.post(f"/tournaments/{tid}/players", json={"nickname": "Гость Вася"}, headers=org)
    assert r.status_code == 201 and r.json()["player_no"] is None
    _, third = await reg(client, 3)
    assert third["player_no"] == 1003
    card = (await client.get(f"/tournaments/{tid}")).json()
    by_nick = {p["nickname"]: p["player_no"] for p in card["participants"]}
    assert by_nick == {"Игрок2": 1002, "Гость Вася": None}
    # гостя привязываем к аккаунту по номеру игрока
    guest = next(p for p in card["participants"] if p["guest"])
    r = await client.post(f"/clubs/{club['id']}/guests/{guest['user_id']}/merge", json={"player_no": 1003}, headers=org)
    assert r.status_code == 200, r.text
    names = {p["nickname"] for p in (await client.get(f"/tournaments/{tid}")).json()["participants"]}
    assert names == {"Игрок2", "Игрок3"}


async def test_public_card_and_auction(client):
    _, a = await reg(client, 1)
    card = (await client.get(f"/players/{a['player_no']}")).json()
    assert card["nickname"] == "Игрок1" and card["auction"]["deals_completed"] == 0 and card["tournaments"] == 0
    assert (await client.get("/players/5")).status_code == 404
    async with SessionLocal() as s:
        seller = await s.get(User, a["id"])
        lot = await svc.create_lot(s, seller, "Sol Ring", "NM", 100, 24, None)
        view = await svc.lot_view(s, lot.id)
    assert view["seller_no"] == 1001
    cap = lot_caption(lot_id=1, title="Sol Ring", condition="NM", seller="Игрок1", seller_avg=None, seller_count=0,
                      start_price=100, current_price=None, leader=None, bids=0, ends_at=view["ends_at"],
                      status="active", next_bid=100, tz="Europe/Moscow", seller_no=1001)
    assert "Игрок1 (№1001)" in cap
    txt = rating_card("Игрок1", 1001, {"seller_avg": 4.5, "seller_count": 2, "buyer_avg": None, "buyer_count": 0,
                                       "deals_completed": 2})
    assert "1001" in txt and "4.5" in txt and "оценок пока нет" in txt


async def test_old_accounts_get_numbers_on_schema_sync(client):
    """База до появления номеров: колонка добавляется, аккаунтам выдаются номера по порядку, гостям - нет."""
    await reg(client, 1)
    await reg(client, 2)
    org, _ = await reg(client, 3)
    r = await client.post("/clubs", json={"name": "Старый клуб"}, headers=org)
    assert r.status_code == 201, r.text
    r = await client.post("/tournaments", json={"club_id": r.json()["id"], "name": "Турнир", "format": "swiss",
                                                "rounds": 1}, headers=org)
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    await client.post(f"/tournaments/{tid}/players", json={"nickname": "Гость"}, headers=org)
    async with engine.begin() as conn:
        # как в базе, созданной до появления номеров: нет ни колонки, ни последовательности
        await conn.execute(text("ALTER TABLE users DROP COLUMN player_no"))
        await conn.execute(text("DROP SEQUENCE player_no_seq"))
        changes = await conn.run_sync(sync_schema)
        assert any("выдано номеров 3" in c for c in changes)
        assert await conn.run_sync(sync_schema) == []
    async with SessionLocal() as s:
        rows = (await s.execute(select(User.nickname, User.player_no).order_by(User.id))).all()
    assert rows == [("Игрок1", 1001), ("Игрок2", 1002), ("Игрок3", 1003), ("Гость", None)]
    _, d = await reg(client, 4)
    assert d["player_no"] == 1004
