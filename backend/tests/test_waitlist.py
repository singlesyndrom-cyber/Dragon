"""Лист ожидания: очередь при полном турнире, автозапись при освобождении места, сообщение бота. RUN_INTEGRATION=1."""
import os

import pytest

pytestmark = pytest.mark.skipif(not os.getenv("RUN_INTEGRATION"), reason="нужен PostgreSQL (RUN_INTEGRATION=1)")

if os.getenv("RUN_INTEGRATION"):
    import httpx
    from sqlalchemy import select

    from app.db import Base, SessionLocal, engine
    from app.main import app
    from app.models import AuthAccount, OutboxMessage, Provider
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
    r = await c.post("/auth/register", json={"email": f"w{n}@example.com", "password": "password1", "nickname": f"Игрок{n}"})
    assert r.status_code == 200, r.text
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    return h, (await c.get("/auth/me", headers=h)).json()


async def test_waitlist_promotes_in_order(client):
    org, _ = await reg(client, 0)
    await make_creator(client, org)
    cid = (await client.post("/clubs", json={"name": "Дракон"}, headers=org)).json()["id"]
    tid = (await client.post("/tournaments", json={"club_id": cid, "name": "Командир", "format": "edh", "max_players": 2},
                             headers=org)).json()["id"]
    a, b, c, d = [await reg(client, i) for i in (1, 2, 3, 4)]
    async with SessionLocal() as s:
        s.add(AuthAccount(user_id=c[1]["id"], provider=Provider.telegram, external_id="303"))
        await s.commit()

    assert (await client.post(f"/tournaments/{tid}/waitlist", headers=a[0])).status_code == 400   # места ещё есть
    for h, _ in (a, b):
        assert (await client.post(f"/tournaments/{tid}/register", headers=h)).status_code == 204
    r = await client.post(f"/tournaments/{tid}/register", headers=c[0])
    assert r.status_code == 400 and "лист ожидания" in r.json()["detail"]
    assert (await client.post(f"/tournaments/{tid}/waitlist?bracket=4", headers=c[0])).json() == {"position": 1}
    assert (await client.post(f"/tournaments/{tid}/waitlist", headers=d[0])).json() == {"position": 2}
    assert (await client.post(f"/tournaments/{tid}/waitlist", headers=c[0])).json() == {"position": 1}   # повтор - то же место
    assert (await client.post(f"/tournaments/{tid}/waitlist", headers=a[0])).status_code == 409
    card = (await client.get(f"/tournaments/{tid}")).json()
    assert [(w["nickname"], w["position"]) for w in card["waitlist"]] == [("Игрок3", 1), ("Игрок4", 2)]

    # Игрок1 отменил запись - Игрок3 записан автоматически, с брекетом из заявки, и получил сообщение
    assert (await client.delete(f"/tournaments/{tid}/register", headers=a[0])).status_code == 204
    card = (await client.get(f"/tournaments/{tid}")).json()
    assert {p["nickname"]: p["bracket"] for p in card["participants"]} == {"Игрок2": 2, "Игрок3": 4}
    assert [w["nickname"] for w in card["waitlist"]] == ["Игрок4"]
    async with SessionLocal() as s:
        msg = (await s.execute(select(OutboxMessage).where(OutboxMessage.kind == "waitlist_promoted"))).scalar_one()
    assert msg.chat_id == "303" and "Освободилось место" in msg.text and msg.buttons[0][0]["callback_data"] == f"unreg:{tid}"
    assert [c["id"] for c in (await client.get("/clubs/mine", headers=c[0])).json()] == [cid]   # вступил в клуб

    # организатор поднял лимит - записан следующий; игрок может выйти из очереди сам
    e = await reg(client, 5)
    await client.patch(f"/tournaments/{tid}", json={"max_players": 3}, headers=org)
    card = (await client.get(f"/tournaments/{tid}")).json()
    assert len(card["participants"]) == 3 and card["waitlist"] == []
    await client.post(f"/tournaments/{tid}/waitlist", headers=e[0])
    assert (await client.delete(f"/tournaments/{tid}/waitlist", headers=e[0])).status_code == 204
    assert (await client.get(f"/tournaments/{tid}")).json()["waitlist"] == []

    # организатор убрал игрока - очередь пуста, просто освободилось место
    await client.delete(f"/tournaments/{tid}/players/{b[1]['id']}", headers=org)
    assert len((await client.get(f"/tournaments/{tid}")).json()["participants"]) == 2
