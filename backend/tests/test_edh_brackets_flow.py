"""EDH: судья видит брекет по карточкам рядом с заявленным. RUN_INTEGRATION=1."""
import os

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


async def test_declared_vs_cards(client):
    c = client
    org = await auth(c, "o@t.io", "Орг")
    pl = await auth(c, "p@t.io", "Игрок")
    stranger = await auth(c, "s@t.io", "Чужой")
    await make_creator(c, org)
    cid = (await c.post("/clubs", json={"name": "Дракон"}, headers=org)).json()["id"]
    tid = (await c.post("/tournaments", json={"club_id": cid, "name": "EDH", "format": "edh"}, headers=org)).json()["id"]
    text = "Commander\n1 Atraxa, Praetors' Voice\n\nDeck\n1 Armageddon\n1 Thassa's Oracle\n1 Demonic Consultation\n30 Forest"
    deck = (await c.post("/decks", json={"name": "Атракса", "text": text}, headers=pl)).json()["id"]
    d = (await c.get(f"/decks/{deck}", headers=pl)).json()
    assert d["bracket"]["min_bracket"] == 4 and d["bracket"]["mld"] == ["Armageddon"]
    assert (await c.post(f"/tournaments/{tid}/register?bracket=2&deck_id={deck}", headers=pl)).status_code == 204
    rows = (await c.get(f"/decks/tournament/{tid}", headers=org)).json()
    r = rows[0]
    assert r["bracket"] == 2 and r["assessment"]["label"] == "4+"
    assert "Заявлен брекет 2" in r["bracket_hint"] and "Armageddon" in r["bracket_hint"]
    assert r["assessment"]["combos"] == [["Demonic Consultation", "Thassa's Oracle"]]
    assert (await c.get(f"/decks/tournament/{tid}", headers=stranger)).status_code == 403
