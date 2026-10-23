"""Тестовый турнир без оповещений и гости с колодой организатора. RUN_INTEGRATION=1."""
import os

import pytest

pytestmark = pytest.mark.skipif(not os.getenv("RUN_INTEGRATION"), reason="нужен PostgreSQL (RUN_INTEGRATION=1)")

if os.getenv("RUN_INTEGRATION"):
    import httpx
    from sqlalchemy import func, select

    from app.db import Base, SessionLocal, engine
    from app.main import app
    from app.models import OutboxMessage
    from tests.helpers import make_creator


@pytest.fixture
async def client():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await engine.dispose()


async def outbox() -> int:
    async with SessionLocal() as s:
        return (await s.execute(select(func.count()).select_from(OutboxMessage))).scalar_one()


async def test_silent_tournament_with_guest_decks(client):
    c = client
    r = await c.post("/auth/register", json={"email": "o@t.io", "password": "password1", "nickname": "Орг"})
    org = {"Authorization": f"Bearer {r.json()['access_token']}"}
    await make_creator(c, org)
    cid = (await c.post("/clubs", json={"name": "Дракон", "telegram_chat_id": "-100123"}, headers=org)).json()["id"]
    before = await outbox()
    tid = (await c.post("/tournaments", json={"club_id": cid, "name": "Тест", "game": "berserk", "format": "swiss",
                                              "rounds": 1, "silent": True}, headers=org)).json()["id"]
    assert (await c.get(f"/tournaments/{tid}")).json()["silent"] is True
    d1 = (await c.post("/decks", json={"name": "Слуа", "game": "berserk", "text": "3 Карта"}, headers=org)).json()["id"]
    mtg = (await c.post("/decks", json={"name": "EDH", "game": "mtg", "text": "1 Sol Ring"}, headers=org)).json()["id"]
    assert (await c.post(f"/tournaments/{tid}/players", json={"nickname": "Гость А", "deck_id": mtg},
                         headers=org)).status_code == 400                  # колода другой игры
    for nick in ("Гость А", "Гость Б"):
        assert (await c.post(f"/tournaments/{tid}/players", json={"nickname": nick, "deck_id": d1},
                             headers=org)).status_code == 201
    parts = (await c.get(f"/tournaments/{tid}")).json()["participants"]
    assert all(p["has_deck"] for p in parts) and len(parts) == 2
    assert (await c.post(f"/tournaments/{tid}/start", headers=org)).status_code == 200
    for m in (await c.get(f"/tournaments/{tid}/round/1")).json():
        if m.get("p2_id"):
            await c.post(f"/tournaments/matches/{m['match_id']}/result", json={"result": "p1"}, headers=org)
    assert (await c.post(f"/tournaments/{tid}/finish", headers=org)).status_code == 200
    assert await outbox() == before                                    # ни анонса, ни итогов в чат
    # обычный турнир того же клуба оповещение отправляет
    await c.post("/tournaments", json={"club_id": cid, "name": "Обычный", "game": "berserk", "format": "swiss"}, headers=org)
    assert await outbox() > before
