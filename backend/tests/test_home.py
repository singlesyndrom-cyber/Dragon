"""Главная: неделя, мета месяца, сезон, клубы и личный блок. RUN_INTEGRATION=1."""
import os
from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.skipif(not os.getenv("RUN_INTEGRATION"), reason="нужен PostgreSQL (RUN_INTEGRATION=1)")

if os.getenv("RUN_INTEGRATION"):
    import httpx

    from app.db import Base, engine
    from app.main import app
    from tests.helpers import make_creator


@pytest.fixture
async def client():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await engine.dispose()


async def auth(c, email, nick):
    r = await c.post("/auth/register", json={"email": email, "password": "password1", "nickname": nick})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def test_home_blocks(client):
    c = client
    org = await auth(c, "o@t.io", "Орг")
    pl = await auth(c, "p@t.io", "Игрок")
    await make_creator(c, org)
    cid = (await c.post("/clubs", json={"name": "Дракон"}, headers=org)).json()["id"]
    lid = (await c.post("/leagues", json={"club_id": cid, "name": "Осень", "kind": "berserk", "months": 1},
                        headers=org)).json()["id"]
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()

    # завершённый турнир сезона: игрок со своей колодой и два гостя с колодами организатора
    t1 = (await c.post("/tournaments", json={"club_id": cid, "name": "Пятница", "game": "berserk", "format": "swiss",
                                             "rounds": 1, "league_id": lid}, headers=org)).json()["id"]
    my = (await c.post("/decks", json={"name": "Слуа", "game": "berserk", "text": "3 Карта"}, headers=pl)).json()["id"]
    assert (await c.post(f"/tournaments/{t1}/register?deck_id={my}", headers=pl)).status_code == 204
    for nick, name in (("Гость А", "слуа"), ("Гость Б", "Гномы Гор")):
        d = (await c.post("/decks", json={"name": name, "game": "berserk", "text": "3 Карта"}, headers=org)).json()["id"]
        assert (await c.post(f"/tournaments/{t1}/players", json={"nickname": nick, "deck_id": d},
                             headers=org)).status_code == 201
    assert (await c.post(f"/tournaments/{t1}/start", headers=org)).status_code == 200
    for m in (await c.get(f"/tournaments/{t1}/round/1")).json():
        if m.get("p2_id"):
            await c.post(f"/tournaments/matches/{m['match_id']}/result", json={"result": "p1"}, headers=org)
    assert (await c.post(f"/tournaments/{t1}/finish", headers=org)).status_code == 200

    t2 = (await c.post("/tournaments", json={"club_id": cid, "name": "Суббота", "game": "berserk", "format": "swiss",
                                             "starts_at": tomorrow, "deck_policy": "required"}, headers=org)).json()["id"]
    assert (await c.post(f"/tournaments/{t2}/register", headers=pl)).status_code == 204
    await c.post("/tournaments", json={"club_id": cid, "name": "Модерн", "game": "mtg", "starts_at": tomorrow}, headers=org)
    await c.post("/tournaments", json={"club_id": cid, "name": "Тест", "game": "berserk", "starts_at": tomorrow,
                                       "silent": True}, headers=org)

    h = (await c.get("/home?game=berserk")).json()
    assert [e["id"] for e in h["events"]] == [t2]                  # ни завершённого, ни MTG, ни тестового
    assert h["meta"]["decks"] == 3 and h["meta"]["since_days"] == 30
    top = h["meta"]["rows"][0]
    assert top["name"] in ("Слуа", "слуа") and top["decks"] == 2   # регистр названия не делит архетип
    assert h["season"]["name"] == "Осень" and h["season"]["rows"][0]["place"] == 1
    assert h["clubs"][0]["next"]["id"] == t2 and h["clubs"][0]["games"] == ["berserk", "mtg"]
    assert [e["name"] for e in (await c.get("/home?game=mtg")).json()["events"]] == ["Модерн"]
    assert (await c.get("/home?game=chess")).status_code == 422

    me = (await c.get("/home/me?game=berserk", headers=pl)).json()
    assert [t["id"] for t in me["tournaments"]] == [t2] and me["tournaments"][0]["deck_id"] is None
    assert me["decks_total"] == 1 and me["decks"][0]["cards"] == 3
    assert me["season"]["place"] >= 1 and me["season"]["name"] == "Осень"
    assert me["organizer"] == []

    om = (await c.get("/home/me?game=berserk", headers=org)).json()
    club = om["organizer"][0]
    assert club["name"] == "Дракон" and club["missing_decks"] == 1 and club["week"] == 3
    assert (await c.get("/home/me")).status_code == 401
