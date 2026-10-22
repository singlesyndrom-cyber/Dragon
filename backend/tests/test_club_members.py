"""Страница «Участники»: список для штаба клуба и запись нескольких участников в турнир.
Запуск: RUN_INTEGRATION=1 и DATABASE_URL."""
import os

import pytest

pytestmark = pytest.mark.skipif(not os.getenv("RUN_INTEGRATION"), reason="нужен PostgreSQL (RUN_INTEGRATION=1)")

if os.getenv("RUN_INTEGRATION"):
    import httpx

    from app.db import Base, SessionLocal, engine
    from app.main import app
    from app.models import AuthAccount, Provider
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
    r = await c.post("/auth/register", json={"email": f"cm{n}@example.com", "password": "password1", "nickname": f"Игрок{n}"})
    assert r.status_code == 200, r.text
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    return h, (await c.get("/auth/me", headers=h)).json()


async def test_members_list_and_bulk_add(client):
    org, _ = await reg(client, 0)
    await make_creator(client, org)
    cid = (await client.post("/clubs", json={"name": "Дракон"}, headers=org)).json()["id"]
    jh, judge = await reg(client, 1)
    players = [await reg(client, i) for i in (2, 3, 4)]
    outsider_h, outsider = await reg(client, 5)
    for h, _ in [(jh, judge), *players]:
        await client.post(f"/clubs/{cid}/join", headers=h)
    await client.put(f"/clubs/{cid}/judges", json={"player_no": judge["player_no"], "games": ["edh"]}, headers=org)
    async with SessionLocal() as s:
        s.add(AuthAccount(user_id=players[0][1]["id"], provider=Provider.telegram, external_id="777"))
        await s.commit()

    # видят организатор и судьи, обычный участник - нет
    assert (await client.get(f"/clubs/{cid}/members", headers=players[0][0])).status_code == 403
    assert (await client.get(f"/clubs/{cid}/members", headers=jh)).status_code == 200
    rows = (await client.get(f"/clubs/{cid}/members", headers=org)).json()
    assert [r["nickname"] for r in rows] == ["Игрок0", "Игрок1", "Игрок2", "Игрок3", "Игрок4"]   # штаб сверху
    assert rows[0]["organizer"] and rows[1]["judge_games"] == ["edh"]
    assert rows[2]["telegram"] is True and rows[3]["telegram"] is False
    assert rows[2]["edh_bank"] == 1000.0 and rows[2]["last_played"] is None

    edh = (await client.post("/tournaments", json={"club_id": cid, "name": "Командир", "format": "edh",
                                                   "max_players": 3}, headers=org)).json()["id"]
    swiss = (await client.post("/tournaments", json={"club_id": cid, "name": "Пятница", "format": "swiss"},
                               headers=org)).json()["id"]
    ids = [p["id"] for _, p in players]
    # судья EDH записывает в EDH, но не в швейцарку
    assert (await client.post(f"/tournaments/{swiss}/players/bulk", json={"user_ids": ids}, headers=jh)).status_code == 403
    await client.post(f"/tournaments/{edh}/players", json={"user_id": ids[0]}, headers=org)
    r = await client.post(f"/tournaments/{edh}/players/bulk",
                          json={"user_ids": [ids[0], ids[1], ids[2], judge["id"], outsider["id"]], "bracket": 3},
                          headers=jh)
    assert r.status_code == 200, r.text
    # лимит 3: один уже записан, двое добавлены, судье места не хватило, не участник пропущен
    assert r.json() == {"added": [ids[1], ids[2]], "skipped": [ids[0], outsider["id"]], "no_room": [judge["id"]]}
    card = (await client.get(f"/tournaments/{edh}")).json()
    assert {p["nickname"]: p["bracket"] for p in card["participants"]} == {"Игрок2": 2, "Игрок3": 3, "Игрок4": 3}
    marked = {r["nickname"]: r["registered"] for r in (await client.get(
        f"/clubs/{cid}/members", params={"tournament_id": edh}, headers=org)).json()}
    assert marked == {"Игрок0": False, "Игрок1": False, "Игрок2": True, "Игрок3": True, "Игрок4": True}

    # подсказки при добавлении игрока теперь доступны и судье
    assert (await client.get(f"/clubs/{cid}/players?q=Игрок", headers=jh)).status_code == 200
