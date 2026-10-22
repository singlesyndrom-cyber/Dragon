"""Вступление и выход из клуба, «мои клубы», запись на турнир сразу с колодой, мета по пулу колод игроков.
Запуск: RUN_INTEGRATION=1 и DATABASE_URL."""
import os
from datetime import datetime, timedelta

import pytest

pytestmark = pytest.mark.skipif(not os.getenv("RUN_INTEGRATION"), reason="нужен PostgreSQL (RUN_INTEGRATION=1)")

if os.getenv("RUN_INTEGRATION"):
    from zoneinfo import ZoneInfo

    import httpx
    from sqlalchemy import select

    from app.config import settings
    from app.db import Base, SessionLocal, engine
    from app.main import app
    from app.models import TableBooking, TournamentPlayer
    from tests.helpers import make_creator


@pytest.fixture
async def client():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await engine.dispose()


async def reg(c, n):
    r = await c.post("/auth/register", json={"email": f"m{n}@example.com", "password": "password1", "nickname": f"Игрок{n}"})
    assert r.status_code == 200, r.text
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    return h, (await c.get("/auth/me", headers=h)).json()


ATRAXA, KRENKO = "Atraxa, Praetors' Voice", "Krenko, Mob Boss"
EDH = {"text": "1 Sol Ring\n1 Arcane Signet\n1 Counterspell\n30 Island\n", "commander": ATRAXA}
EDH2 = {"text": "1 Sol Ring\n1 Cultivate\n30 Forest\n", "commander": ATRAXA}
EDH3 = {"text": "1 Sol Ring\n1 Goblin Bombardment\n30 Mountain\n", "commander": KRENKO}


async def test_join_leave_and_my_clubs(client):
    org, _ = await reg(client, 0)
    await make_creator(client, org)
    cid = (await client.post("/clubs", json={"name": "Дракон"}, headers=org)).json()["id"]
    ph, _ = await reg(client, 1)
    assert (await client.get("/clubs/mine", headers=ph)).json() == []
    assert (await client.post(f"/clubs/{cid}/join", headers=ph)).status_code == 204
    assert (await client.post(f"/clubs/{cid}/join", headers=ph)).status_code == 409
    tid = (await client.post(f"/clubs/{cid}/tables", json={"name": "Стол 1"}, headers=org)).json()["id"]
    tour = (await client.post("/tournaments", json={"club_id": cid, "name": "Пятница", "format": "swiss"},
                              headers=org)).json()["id"]
    mine = (await client.get("/clubs/mine", headers=ph)).json()
    assert mine == [{"id": cid, "name": "Дракон", "slug": mine[0]["slug"], "city": "", "organizer": False,
                     "league_points": 0, "edh_bank": 1000.0, "events_played": 0, "upcoming": 1, "tables": 1}]

    # бронь и запись на турнир; выйти, пока записан, нельзя
    day = (datetime.now(ZoneInfo(settings.app_timezone)).date() + timedelta(days=2)).isoformat()
    assert (await client.post(f"/clubs/{cid}/bookings", json={"table_id": tid, "date": day, "start": "15:00",
                                                              "duration": 60}, headers=ph)).status_code == 201
    assert (await client.post(f"/tournaments/{tour}/register", headers=ph)).status_code == 204
    r = await client.post(f"/clubs/{cid}/leave", headers=ph)
    assert r.status_code == 400 and "«Пятница»" in r.json()["detail"]
    await client.delete(f"/tournaments/{tour}/register", headers=ph)
    assert (await client.post(f"/clubs/{cid}/leave", headers=ph)).status_code == 204
    assert (await client.get("/clubs/mine", headers=ph)).json() == []
    async with SessionLocal() as s:
        assert (await s.execute(select(TableBooking.status))).scalar_one() == "cancelled"   # бронь снята
    # организатор выйти не может; не участник - 404
    assert (await client.post(f"/clubs/{cid}/leave", headers=org)).status_code == 400
    assert (await client.post(f"/clubs/{cid}/leave", headers=ph)).status_code == 404


async def test_register_with_deck_from_pool(client):
    org, _ = await reg(client, 0)
    await make_creator(client, org)
    cid = (await client.post("/clubs", json={"name": "Дракон"}, headers=org)).json()["id"]
    ph, p = await reg(client, 1)
    oh, _ = await reg(client, 2)
    edh = (await client.post("/tournaments", json={"club_id": cid, "name": "Командир", "format": "edh"},
                             headers=org)).json()["id"]
    deck = (await client.post("/decks", json={"name": "Атракса", **EDH}, headers=ph)).json()["id"]
    berserk = (await client.post("/decks", json={"name": "Берс", "game": "berserk", "text": "3 Карта"},
                                 headers=ph)).json()["id"]
    alien = (await client.post("/decks", json={"name": "Чужая", **EDH3}, headers=oh)).json()["id"]

    assert (await client.post(f"/tournaments/{edh}/register?deck_id={alien}", headers=ph)).status_code == 404
    r = await client.post(f"/tournaments/{edh}/register?deck_id={berserk}", headers=ph)
    assert r.status_code == 400 and "не совпадает" in r.json()["detail"]
    # ошибочная колода не записала игрока и не добавила в клуб
    assert (await client.get("/clubs/mine", headers=ph)).json() == []
    assert (await client.post(f"/tournaments/{edh}/register?bracket=3&deck_id={deck}", headers=ph)).status_code == 204
    async with SessionLocal() as s:
        tp = (await s.execute(select(TournamentPlayer).where(TournamentPlayer.user_id == p["id"]))).scalar_one()
    assert tp.deck_id == deck and tp.bracket == 3
    assert [c["id"] for c in (await client.get("/clubs/mine", headers=ph)).json()] == [cid]   # вступил автоматически


async def test_pool_meta_counts_only_opted_in_decks(client):
    org, _ = await reg(client, 0)
    await make_creator(client, org)
    cid = (await client.post("/clubs", json={"name": "Дракон"}, headers=org)).json()["id"]
    a, _ = await reg(client, 1)
    b, _ = await reg(client, 2)
    c, _ = await reg(client, 3)
    await client.post(f"/clubs/{cid}/join", headers=a)
    await client.post(f"/clubs/{cid}/join", headers=b)
    d1 = (await client.post("/decks", json={"name": "A1", **EDH, "in_meta": True}, headers=a)).json()["id"]
    d2 = (await client.post("/decks", json={"name": "B1", **EDH2}, headers=b)).json()["id"]
    await client.post("/decks", json={"name": "C1", **EDH3, "in_meta": True}, headers=c)   # не в клубе
    await client.post("/decks", json={"name": "B-private", **EDH3}, headers=b)              # без галочки

    assert (await client.get("/decks/mine", headers=a)).json()[0]["in_meta"] is True
    # галочка ставится и снимается без перезаливки деклиста; чужую колоду менять нельзя
    assert (await client.patch(f"/decks/{d2}", json={"in_meta": True}, headers=a)).status_code == 404
    r = await client.patch(f"/decks/{d2}", json={"in_meta": True}, headers=b)
    assert r.status_code == 200 and r.json()["in_meta"] is True

    everyone = (await client.get("/meta/pool")).json()
    assert everyone["decks"] == 3
    assert {x["commander"]: x["decks"] for x in everyone["commanders"]} == {
        "Atraxa, Praetors' Voice": 2, "Krenko, Mob Boss": 1}
    sol = next(x for x in everyone["cards"] if x["card"] == "Sol Ring")
    assert sol["decks"] == 3 and sol["usage_pct"] == 100.0
    assert not any(x["card"] in ("Island", "Forest", "Mountain") for x in everyone["cards"])   # базовые земли не считаем

    club = (await client.get("/meta/pool", params={"club_id": cid})).json()
    assert club["decks"] == 2 and [x["commander"] for x in club["commanders"]] == [ATRAXA]
    atraxa = (await client.get("/meta/pool", params={"commander": ATRAXA})).json()
    assert atraxa["decks_in_scope"] == 2

    await client.patch(f"/decks/{d1}", json={"in_meta": False}, headers=a)
    assert (await client.get("/meta/pool", params={"club_id": cid})).json()["decks"] == 1
