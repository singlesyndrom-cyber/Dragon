"""Конструктор колод: правила форматов (без базы) и API - список карт, видимость, каталог, копия. RUN_INTEGRATION=1."""
import os
from types import SimpleNamespace as Card_

import pytest

from app.deckrules import Entry, check


def card(name, type_line, ci=(), text="", legal=None):
    return Card_(name=name, type_line=type_line, text=text, extra={"color_identity": list(ci)},
                 legalities=legal or {})


ATRAXA = card("Atraxa", "Legendary Creature — Angel", "WUBG", "Flying", {"commander": "legal"})
BOLT = card("Lightning Bolt", "Instant", "R", "", {"commander": "legal", "modern": "legal", "pauper": "legal"})
SOL = card("Sol Ring", "Artifact", "", "", {"commander": "legal", "modern": "not_legal", "vintage": "restricted"})
FOREST = card("Forest", "Basic Land — Forest", "G", "", {"commander": "legal", "modern": "legal"})
RATS = card("Relentless Rats", "Creature — Rat", "B", "A deck can have any number of cards named Relentless Rats.",
            {"commander": "legal"})
BEARS = card("Grizzly Bears", "Creature — Bear", "G", "", {"commander": "legal", "modern": "legal"})
TYMNA = card("Tymna", "Legendary Creature — Human", "WB", "Partner", {"commander": "legal"})
THRASIOS = card("Thrasios", "Legendary Creature — Merfolk", "GU", "Partner", {"commander": "legal"})


def texts(problems):
    return " | ".join(p["text"] for p in problems)


def test_commander_rules():
    deck = [Entry("Atraxa", 1, "commander", ATRAXA), Entry("Lightning Bolt", 1, "main", BOLT),
            Entry("Grizzly Bears", 2, "main", BEARS), Entry("Forest", 30, "main", FOREST),
            Entry("Relentless Rats", 20, "main", RATS), Entry("Sol Ring", 1, "main", SOL), Entry("Мистика", 1, "main", None)]
    t = texts(check(deck, "commander"))
    assert "В колоде 56 карт, нужно ровно 100" in t
    assert "Вне цветов командира (WUBG): Lightning Bolt" in t                # Rats чёрная - в цветах Атраксы
    assert "Singleton — одна копия каждой карты: Grizzly Bears ×2" in t      # базовые земли и Rats - без ограничения
    assert "Не найдены в базе карт: Мистика" in t
    assert "Не выбран командир" in texts(check([Entry("Sol Ring", 1, "main", SOL)], "commander"))
    assert "Не может быть командиром: Sol Ring" in texts(check([Entry("Sol Ring", 1, "commander", SOL)], "commander"))
    assert "Partner" in texts(check([Entry("Atraxa", 1, "commander", ATRAXA), Entry("Tymna", 1, "commander", TYMNA)], "commander"))
    ok = texts(check([Entry("Tymna", 1, "commander", TYMNA), Entry("Thrasios", 1, "commander", THRASIOS),
                      Entry("Forest", 98, "main", FOREST)], "commander"))
    assert ok == ""


def test_constructed_rules():
    deck = [Entry("Lightning Bolt", 5, "main", BOLT), Entry("Forest", 50, "main", FOREST), Entry("Sol Ring", 1, "main", SOL),
            Entry("Grizzly Bears", 16, "side", BEARS)]
    t = texts(check(deck, "modern"))
    assert "Больше четырёх копий: Grizzly Bears ×16, Lightning Bolt ×5" in t
    assert "В сайдборде 16 карт" in t and "Не легальны в Modern: Sol Ring" in t
    assert "В основной колоде 56 карт, нужно не меньше 60" in t
    assert "Ограничены (одна копия): Sol Ring" in texts(check([Entry("Sol Ring", 2, "main", SOL)], "vintage"))
    assert check([Entry("Lightning Bolt", 99, "main", BOLT)], "casual") == []


needs_db = pytest.mark.skipif(not os.getenv("RUN_INTEGRATION"), reason="нужен PostgreSQL (RUN_INTEGRATION=1)")
if os.getenv("RUN_INTEGRATION"):
    import httpx

    from app.db import Base, SessionLocal, engine
    from app.main import app
    from app.models import Card


@pytest.fixture
async def client():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    ids = {}
    async with SessionLocal() as s:
        for c in (ATRAXA, BOLT, SOL, FOREST, BEARS):
            row = Card(game="mtg", external_id=c.name, name=c.name, name_lower=c.name.lower(), name_front=c.name.lower(),
                       type_line=c.type_line, text=c.text, legalities=c.legalities, extra=c.extra, cmc=1,
                       prices={"usd": "2.50"}, image_url=f"https://img/{c.name}.jpg")
            s.add(row)
            await s.flush()
            ids[c.name] = row.id
        await s.commit()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        c.ids = ids
        yield c
    await engine.dispose()


async def user(c, n):
    r = await c.post("/auth/register", json={"email": f"d{n}@example.com", "password": "password1", "nickname": f"Деккер{n}"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@needs_db
async def test_builder_api(client):
    c, ids = client, client.ids
    a, b = await user(c, 1), await user(c, 2)
    did = (await c.post("/decks", json={"name": "Атракса"}, headers=a)).json()["id"]          # пустая колода
    d = (await c.get(f"/decks/{did}", headers=a)).json()
    assert d["format"] == "commander" and d["visibility"] == "private" and d["cards"] == [] and d["editable"]
    assert "Не выбран командир" in texts(d["problems"])

    body = {"cards": [{"card_id": ids["Atraxa"], "qty": 1, "section": "commander"},
                      {"card_id": ids["Sol Ring"], "qty": 1, "section": "main"},
                      {"card_id": ids["Lightning Bolt"], "qty": 1, "section": "main"},
                      {"card_id": ids["Forest"], "qty": 96, "section": "main"},
                      {"card_id": ids["Forest"], "qty": 1, "section": "main"},              # повтор - сложится
                      {"name": "Самодельная карта", "qty": 1, "section": "side"}]}
    r = await c.put(f"/decks/{did}/cards", json=body, headers=a)
    assert r.status_code == 200, r.text
    assert texts(r.json()["problems"]) == "Вне цветов командира (WUBG): Lightning Bolt | Не найдены в базе карт: Самодельная карта"
    d = (await c.get(f"/decks/{did}", headers=a)).json()
    forest = [x for x in d["cards"] if x["name"] == "Forest"]
    assert forest[0]["qty"] == 97 and forest[0]["card"]["prices"]["usd"] == "2.50"
    assert [x["is_commander"] for x in d["cards"] if x["section"] == "commander"] == [True]
    assert (await c.put(f"/decks/{did}/cards", json={"cards": [{"card_id": 999999, "qty": 1}]}, headers=a)).status_code == 400
    assert (await c.put(f"/decks/{did}/cards", json=body, headers=b)).status_code == 404     # чужая

    # формат и видимость
    r = (await c.patch(f"/decks/{did}", json={"format": "modern"}, headers=a)).json()
    assert "Не легальны в Modern" in texts(r["problems"])
    assert (await c.patch(f"/decks/{did}", json={"format": "nope"}, headers=a)).status_code == 400
    assert (await c.get(f"/decks/{did}")).status_code == 404 and (await c.get(f"/decks/{did}", headers=b)).status_code == 404
    key = (await c.patch(f"/decks/{did}", json={"visibility": "link"}, headers=a)).json()["share_key"]
    assert key and (await c.get(f"/decks/{did}")).status_code == 404
    seen = (await c.get(f"/decks/{did}", params={"key": key})).json()
    assert seen["editable"] is False and seen["share_key"] is None and seen["owner"]["nickname"] == "Деккер1"
    assert (await c.get("/decks/public")).json()["total"] == 0
    await c.patch(f"/decks/{did}", json={"visibility": "public", "format": "commander"}, headers=a)
    assert (await c.get(f"/decks/{did}")).status_code == 200
    pub = (await c.get("/decks/public", params={"format": "commander", "q": "atraxa"})).json()
    assert pub["total"] == 1 and pub["items"][0]["author"] == "Деккер1" and pub["items"][0]["commanders"][0]["name"] == "Atraxa"
    assert pub["items"][0]["cards"] == 100 and pub["items"][0]["usd"] == 250.0
    assert (await c.get("/decks/public", params={"format": "modern"})).json()["total"] == 0

    # копия себе и импорт текстом поверх
    cid = (await c.post(f"/decks/{did}/copy", headers=b)).json()["id"]
    mine = (await c.get("/decks/mine", headers=b)).json()
    assert mine[0]["id"] == cid and mine[0]["name"] == "Атракса (копия)" and mine[0]["cards"] == 100
    r = await c.put(f"/decks/{cid}", json={"name": "Болты", "text": "4 Lightning Bolt\n56 Forest\nSideboard\n2 Grizzly Bears",
                                         "format": "modern"}, headers=b)
    assert r.status_code == 200 and r.json()["unmatched"] == []
    d = (await c.get(f"/decks/{cid}", headers=b)).json()
    assert d["format"] == "modern" and d["problems"] == [] and {x["section"] for x in d["cards"]} == {"main", "side"}


@needs_db
async def test_import_moxfield_export_without_headers(client):
    """Экспорт Moxfield: 99 строк, пустая строка, командир. В Modern тот же хвост - сайдборд."""
    c = client
    a = await user(c, 3)
    text = "1 Sol Ring\n97 Forest\n1 Lightning Bolt\n\n1 Atraxa\n"
    r = (await c.post("/decks", json={"name": "Мокс", "text": text}, headers=a)).json()
    d = (await c.get(f"/decks/{r['id']}", headers=a)).json()
    assert [x["name"] for x in d["cards"] if x["section"] == "commander"] == ["Atraxa"]
    assert sum(x["qty"] for x in d["cards"] if x["section"] != "side") == 100
    # хвост из не-легендарной карты командиром не становится
    r = (await c.post("/decks", json={"name": "Без командира", "text": "97 Forest\n\n1 Sol Ring\n"}, headers=a)).json()
    d = (await c.get(f"/decks/{r['id']}", headers=a)).json()
    assert {x["section"] for x in d["cards"]} == {"main"} and "Не выбран командир" in texts(d["problems"])
    # конструктед: блок после пустой строки - сайдборд
    r = (await c.post("/decks", json={"name": "Модерн", "format": "modern", "text": "4 Lightning Bolt\n56 Forest\n\n2 Grizzly Bears"},
                      headers=a)).json()
    d = (await c.get(f"/decks/{r['id']}", headers=a)).json()
    assert [(x["name"], x["section"]) for x in d["cards"] if x["section"] == "side"] == [("Grizzly Bears", "side")]
