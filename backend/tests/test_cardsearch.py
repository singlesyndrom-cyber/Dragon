"""Картотека: язык запросов в духе Scryfall. Разбор - без базы; выдача - на PostgreSQL (RUN_INTEGRATION=1)."""
import os

import pytest

from app.cardsearch import parse, tokenize

needs_db = pytest.mark.skipif(not os.getenv("RUN_INTEGRATION"), reason="нужен PostgreSQL (RUN_INTEGRATION=1)")


def test_tokenize():
    toks = tokenize('t:"legendary creature" -c:r (mv<=2 or pow>=4) !"Sol Ring" сол или kw:flying')
    assert [(t.kind, t.neg, t.key, t.op, t.value) for t in toks] == [
        ("term", False, "t", ":", "legendary creature"), ("term", True, "c", ":", "r"), ("(", False, None, None, None),
        ("term", False, "mv", "<=", "2"), ("or", False, None, None, None), ("term", False, "pow", ">=", "4"),
        (")", False, None, None, None), ("exact", False, None, None, "Sol Ring"), ("word", False, None, None, "сол"),
        ("or", False, None, None, None), ("term", False, "kw", ":", "flying")]


def test_warnings_and_inline_options():
    p = parse("foo:bar mv>abc c:xyz r:superrare is:shiny f:twoheaded (t:elf order:mv dir:desc game:berserk")
    assert p.order == "mv" and p.direction == "desc" and p.game == "berserk"
    w = " | ".join(p.warnings)
    for part in ("«foo:»", "нужно число", "Не понял цвет", "Редкость", "is:shiny", "Формат «twoheaded»", "скобки"):
        assert part in w, part


if os.getenv("RUN_INTEGRATION"):
    import httpx

    from app.db import Base, SessionLocal, engine
    from app.main import app
    from app.models import Card

CARDS = [
    dict(external_id="sol", name="Sol Ring", name_ru="Солнечное Кольцо", set_code="cmm", set_name="Commander Masters",
         type_line="Artifact", type_ru="Артефакт", mana_cost="{1}", text="{T}: Add {C}{C}.", rarity="uncommon", cmc=1,
         is_game_changer=True, legalities={"commander": "legal", "vintage": "restricted", "modern": "not_legal"},
         prices={"usd": "1.20", "eur": "1.05"}, extra={"colors": [], "color_identity": [], "artist": "Mike Bierek"}),
    dict(external_id="bolt", name="Lightning Bolt", name_ru="Молния", set_code="clu", type_line="Instant",
         text="Lightning Bolt deals 3 damage to any target.", text_ru="Молния наносит 3 повреждения любой цели.",
         rarity="common", cmc=1, legalities={"commander": "legal", "modern": "legal"}, prices={"usd": "0.50"},
         extra={"colors": ["R"], "color_identity": ["R"], "artist": "Christopher Moeller"}),
    dict(external_id="atraxa", name="Atraxa, Praetors' Voice", set_code="c16", type_line="Legendary Creature — Phyrexian Angel Horror",
         text="Flying, vigilance, deathtouch, lifelink", rarity="mythic", cmc=4,
         legalities={"commander": "legal"}, prices={"usd": "15"},
         extra={"colors": ["W", "U", "B", "G"], "color_identity": ["W", "U", "B", "G"], "power": "4", "toughness": "4",
                "keywords": ["Flying", "Vigilance", "Deathtouch", "Lifelink"]}),
    dict(external_id="tarmo", name="Tarmogoyf", set_code="mm3", type_line="Creature — Lhurgoyf", rarity="mythic", cmc=2,
         text="Tarmogoyf's power is equal to...", legalities={"commander": "legal", "modern": "legal"},
         extra={"colors": ["G"], "color_identity": ["G"], "power": "*", "toughness": "1+*"}),
    dict(external_id="elves", name="Llanowar Elves", name_ru="Лановарские Эльфы", set_code="dom",
         type_line="Creature — Elf Druid", type_ru="Существо — Эльф Друид", text="{T}: Add {G}.", rarity="common", cmc=1,
         legalities={"commander": "legal", "pauper": "legal"},
         extra={"colors": ["G"], "color_identity": ["G"], "power": "1", "toughness": "1"}),
    dict(external_id="bear", name="Grizzly Bears", set_code="lea", type_line="Creature — Bear", text=None, rarity="common",
         cmc=2, legalities={"commander": "legal"}, extra={"colors": ["G"], "color_identity": ["G"], "power": "2",
                                                            "toughness": "2"}),
    dict(game="berserk", external_id="b1", name="Огненный дракон", set_code="s1", type_line="Существо", rarity="rare",
         cmc=6, extra={}),
]


@pytest.fixture
async def client():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with SessionLocal() as s:
        for c in CARDS:
            c = {"game": "mtg", **c}
            s.add(Card(**c, name_lower=c["name"].lower(), name_front=c["name"].lower(),
                       name_ru_lower=c.get("name_ru") and c["name_ru"].lower()))
        await s.commit()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await engine.dispose()


async def names(c, q, **params):
    r = await c.get("/cards/search", params={"q": q, "game": "mtg", **params})
    assert r.status_code == 200, r.text
    return [i["name"] for i in r.json()["items"]]


@needs_db
async def test_search_language(client):
    c = client
    assert await names(c, "") == ["Atraxa, Praetors' Voice", "Grizzly Bears", "Lightning Bolt", "Llanowar Elves",
                                  "Sol Ring", "Tarmogoyf"]
    assert len(await names(c, "*")) == 6
    assert await names(c, "кольцо") == ["Sol Ring"]
    assert (await names(c, "bolt"))[0] == "Lightning Bolt"                       # русское название
    assert await names(c, "ring sol") == ["Sol Ring"]                     # слова в любом порядке
    assert await names(c, '!"sol ring"') == ["Sol Ring"] and await names(c, '!"sol"') == []
    assert await names(c, "t:creature t:elf") == ["Llanowar Elves"]
    assert await names(c, "t:эльф") == ["Llanowar Elves"]
    assert await names(c, 'o:"3 damage"') == ["Lightning Bolt"] and await names(c, "o:повреждения") == ["Lightning Bolt"]
    assert await names(c, "c:r") == ["Lightning Bolt"]
    assert await names(c, "c:c") == ["Sol Ring"]
    assert await names(c, "c:m") == ["Atraxa, Praetors' Voice"]
    assert await names(c, "c=g") == ["Grizzly Bears", "Llanowar Elves", "Tarmogoyf"]
    assert await names(c, "c>=wu") == ["Atraxa, Praetors' Voice"]
    assert await names(c, "id<=g") == ["Grizzly Bears", "Llanowar Elves", "Sol Ring", "Tarmogoyf"]
    assert await names(c, "id:gr t:creature") == ["Grizzly Bears", "Llanowar Elves", "Tarmogoyf"]
    assert await names(c, "mv>=2 -t:legendary") == ["Grizzly Bears", "Tarmogoyf"]
    assert await names(c, "pow>=2") == ["Atraxa, Praetors' Voice", "Grizzly Bears"]   # «*» не число - не попадает
    assert await names(c, "r>=mythic") == ["Atraxa, Praetors' Voice", "Tarmogoyf"]
    assert await names(c, "r<uncommon") == ["Grizzly Bears", "Lightning Bolt", "Llanowar Elves"]
    assert await names(c, "s:CMM") == ["Sol Ring"]
    assert await names(c, "f:modern") == ["Lightning Bolt", "Tarmogoyf"]
    assert await names(c, "f:pauper") == ["Llanowar Elves"]
    assert await names(c, "restricted:vintage") == ["Sol Ring"]
    assert await names(c, "is:gc") == ["Sol Ring"]
    assert await names(c, "is:commander") == ["Atraxa, Praetors' Voice"]
    assert await names(c, "is:russian") == ["Lightning Bolt", "Llanowar Elves", "Sol Ring"]
    assert await names(c, "is:vanilla") == ["Grizzly Bears"]
    assert await names(c, "kw:deathtouch") == ["Atraxa, Praetors' Voice"]
    assert await names(c, 'a:"mike"') == ["Sol Ring"]
    assert await names(c, "usd<1") == ["Lightning Bolt"]
    assert await names(c, "(t:elf or t:bear) mv<=1") == ["Llanowar Elves"]
    assert await names(c, "t:elf or t:bear mv<=1") == ["Llanowar Elves"]          # «и» связывает сильнее «или»
    assert await names(c, "тип:существо цвет:g мв:1") == ["Llanowar Elves"]


@needs_db
async def test_exact_name_first(client):
    c = client
    async with SessionLocal() as s:     # алфавит поставил бы её первой: «A…» раньше «L…»
        s.add(Card(game="mtg", external_id="emer", name="Aemeritus of Conflict // Lightning Bolt",
                   name_lower="aemeritus of conflict // lightning bolt", name_front="aemeritus of conflict", extra={}))
        await s.commit()
    assert await names(c, "lightning bolt") == ["Lightning Bolt", "Aemeritus of Conflict // Lightning Bolt"]
    assert await names(c, '!"aemeritus of conflict"') == ["Aemeritus of Conflict // Lightning Bolt"]
    assert await names(c, "light") == ["Lightning Bolt", "Aemeritus of Conflict // Lightning Bolt"]   # «начинается с»
    assert (await names(c, "lightning bolt", order="name"))[0] == "Aemeritus of Conflict // Lightning Bolt"


@needs_db
async def test_sort_paging_and_games(client):
    c = client
    assert await names(c, "", order="usd", dir="desc") == ["Atraxa, Praetors' Voice", "Sol Ring", "Lightning Bolt",
                                                           "Grizzly Bears", "Llanowar Elves", "Tarmogoyf"]
    assert (await names(c, "order:mv dir:desc"))[:2] == ["Atraxa, Praetors' Voice", "Grizzly Bears"]
    assert await names(c, "order:rarity t:creature") == ["Grizzly Bears", "Llanowar Elves", "Atraxa, Praetors' Voice",
                                                        "Tarmogoyf"]
    r = (await c.get("/cards/search", params={"q": "", "game": "mtg", "per_page": 4, "page": 2})).json()
    assert r["total"] == 6 and [i["name"] for i in r["items"]] == ["Sol Ring", "Tarmogoyf"]
    r = (await c.get("/cards/search", params={"q": "дракон", "game": "berserk"})).json()
    assert r["total"] == 1 and r["items"][0]["game"] == "berserk"
    r = (await c.get("/cards/search", params={"q": "foo:bar sol"})).json()   # без игры - все игры; неизвестное - предупреждение
    assert [i["name"] for i in r["items"]] == ["Sol Ring"] and "foo" in r["warnings"][0]
    item = (await c.get("/cards/search", params={"q": "atraxa"})).json()["items"][0]
    assert item["power"] == "4" and item["colors"] == ["W", "U", "B", "G"] and item["prices"]["usd"] == "15"
    sets = {s["code"]: s for s in (await c.get("/cards/sets")).json()}
    assert set(sets) == {"c16", "clu", "cmm", "dom", "lea", "mm3"} and sets["cmm"]["name"] == "Commander Masters"


@needs_db
async def test_fake_russian_names_cleared(client):
    from app.scryfall import clear_fake_russian
    async with SessionLocal() as s:
        s.add(Card(game="mtg", external_id="boom", name="Boom // Bust", name_lower="boom // bust", name_front="boom",
                   name_ru="Boom // Bust", name_ru_lower="boom", name_ru_front="boom", extra={}))   # служебные поля могут не совпасть
        await s.commit()
        assert await clear_fake_russian(await s.connection()) == 1
        await s.commit()
    assert "Boom // Bust" not in await names(client, "is:russian")
    assert await names(client, "кольцо") == ["Sol Ring"]           # настоящие переводы на месте
