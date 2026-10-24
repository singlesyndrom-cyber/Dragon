"""«Респонс» через API: загрузка выгрузки в админке, карточка, колода с автораскладкой. RUN_INTEGRATION=1."""
import json
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(not os.getenv("RUN_INTEGRATION"), reason="нужен PostgreSQL (RUN_INTEGRATION=1)")

if os.getenv("RUN_INTEGRATION"):
    import httpx
    from sqlalchemy import update

    from app.db import Base, SessionLocal, engine
    from app.main import app
    from app.models import GlobalRole, User

FIXTURE = Path(__file__).parent / "fixtures" / "response_page1.json"


@pytest.fixture
async def client():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await engine.dispose()


async def test_import_and_deck(client):
    c = client
    r = await c.post("/auth/register", json={"email": "a@t.io", "password": "password1", "nickname": "Админ"})
    adm = {"Authorization": f"Bearer {r.json()['access_token']}"}
    me = (await c.get("/auth/me", headers=adm)).json()
    async with SessionLocal() as s:
        await s.execute(update(User).where(User.id == me["id"]).values(role=GlobalRole.admin))
        await s.commit()
    raw = FIXTURE.read_bytes()
    r = await c.post("/admin/cards/response/import", files={"file": ("cards.json", raw, "application/json")}, headers=adm)
    assert r.status_code == 200, r.text
    assert r.json()["cards"] == 50 and r.json()["in_base"] == 50 and r.json()["total_in_api"] == 427
    st = (await c.get("/admin/cards/sync/response", headers=adm)).json()
    assert st["cards"] == 50 and st["auth"] == "none" and st["key_configured"] is False

    found = (await c.get("/cards/search?q=Адепт&game=response")).json()
    card = next(x for x in found["items"] if x["name"] == "Адепт раздора")
    assert card and card["rs"]["factions"] == ["Хаос"]

    data = json.loads(raw)["data"]
    hero = "Азарион, Пересмешник"
    orders = ["Благословление войны", "Большой пожар", "Бурлящая кровь", "Демонический наставник", "Аннигиляция"]
    fits = [x["name"] for x in data if not x["is_hero"] and "Приказ" not in x["supertypes"]
            and set(x["factions"]) <= {"Хаос", "Технологии"} and "Легендарный" not in x["supertypes"]]
    main = [f"2 {n}" for n in fits[:15]]
    text = "\n".join([f"1 {hero}"] + [f"1 {o}" for o in orders] + main)          # без заголовков
    d = (await c.post("/decks", json={"name": "Азарион", "game": "response", "text": text}, headers=adm)).json()
    deck = (await c.get(f"/decks/{d['id']}", headers=adm)).json()
    assert deck["format"] == "response"
    sections = {x["name"]: x["section"] for x in deck["cards"]}
    assert sections[hero] == "commander" and all(sections[o] == "orders" for o in orders)
    assert sum(x["qty"] for x in deck["cards"] if x["section"] == "main") == 2 * len(fits[:15])
    probs = [p["text"] for p in deck["problems"]]
    assert (len(fits) >= 15) == (not probs), probs
