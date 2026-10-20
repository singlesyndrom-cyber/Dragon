"""Загрузка базы MTG: подменённый сервер Scryfall, настоящий PostgreSQL."""
import json
import os

import pytest

pytestmark = pytest.mark.skipif(not os.getenv("RUN_INTEGRATION"), reason="нужен PostgreSQL (RUN_INTEGRATION=1)")

if os.getenv("RUN_INTEGRATION"):
    import httpx
    from sqlalchemy import text, update

    from app import scryfall
    from app.db import Base, SessionLocal, engine
    from app.main import app
    from app.models import GlobalRole, User
    from app.schema import sync_schema
    from app.security import create_token

ORACLE = [
    {"oracle_id": "o-sol", "name": "Sol Ring", "layout": "normal", "set": "cmm", "set_name": "Commander Masters",
     "type_line": "Artifact", "mana_cost": "{1}", "oracle_text": "{T}: Add {C}{C}.", "rarity": "uncommon", "cmc": 1,
     "image_uris": {"normal": "https://cards.scryfall.io/normal/sol.jpg"}, "artist": "Mike Bierek",
     "legalities": {"commander": "legal", "vintage": "restricted", "modern": "not_legal"},
     "prices": {"usd": "1.20", "eur": "1.05"}, "scryfall_uri": "https://scryfall.com/card/cmm/sol"},
    {"oracle_id": "o-tok", "name": "Goblin", "layout": "token"},
    {"oracle_id": "o-del", "name": "Delver of Secrets // Insectile Aberration", "layout": "transform", "cmc": 1,
     "set": "mid", "rarity": "common", "legalities": {"commander": "legal"},
     "card_faces": [{"name": "Delver of Secrets", "mana_cost": "{U}", "type_line": "Creature — Human Wizard",
                     "oracle_text": "Upkeep", "image_uris": {"normal": "d1.jpg"}},
                    {"name": "Insectile Aberration", "type_line": "Creature — Insect", "oracle_text": "Flying"}]},
]
RU_PAGE1 = {"has_more": True, "next_page": "https://api.scryfall.com/cards/search?q=lang%3Aru&page=2",
            "data": [{"lang": "ru", "oracle_id": "o-sol", "printed_name": "Кольцо Сола",
                      "printed_type_line": "Артефакт", "printed_text": "{T}: добавьте {C}{C}."}]}
RU_PAGE2 = {"has_more": False, "data": [
    {"lang": "en", "oracle_id": "o-del", "name": "skip me"},
    {"lang": "ru", "oracle_id": "o-del", "card_faces": [
        {"printed_name": "Похититель Тайн", "printed_type_line": "Существо"},
        {"printed_name": "Насекомое-Аберрация", "printed_type_line": "Существо"}]},
    {"lang": "ru", "oracle_id": "o-unknown", "printed_name": "Нет в базе"}]}


def fake_scryfall(seen: list):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        url = str(request.url)
        if url == "https://api.scryfall.com/bulk-data":
            return httpx.Response(200, json={"data": [
                {"type": "default_cards", "download_uri": "https://data.test/default.json"},
                {"type": "oracle_cards", "download_uri": "https://data.test/oracle.json"}]})
        if url == "https://data.test/oracle.json":
            return httpx.Response(200, content=json.dumps(ORACLE).encode())
        if request.url.path == "/cards/search":
            return httpx.Response(200, json=RU_PAGE2 if request.url.params.get("page") == "2" else RU_PAGE1)
        return httpx.Response(404)
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), headers=scryfall.HEADERS)


@pytest.fixture
async def client():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await engine.dispose()


async def test_sync_search_and_decks(client):
    async with SessionLocal() as s:
        assert await scryfall.due(s)                       # пустая база - пора загружать
    seen: list = []
    async with fake_scryfall(seen) as http:
        run = await scryfall.sync(trigger="auto", client=http)
    assert run.error is None and run.cards == 2 and run.russian == 2
    assert seen[0].headers["user-agent"].startswith("DragonTCGPlatform")
    first_search = next(r for r in seen if r.url.path == "/cards/search")
    assert first_search.url.params["q"] == "lang:ru"

    async with SessionLocal() as s:
        assert not await scryfall.due(s)                   # только что загрузили

    # повторная загрузка не дублирует карты и не стирает русские названия
    async with fake_scryfall([]) as http:
        assert (await scryfall.sync(client=http, russian=False)).cards == 2
    stats = (await client.get("/cards/stats")).json()
    assert stats["games"]["mtg"] == {"cards": 2, "russian": 2} and stats["scryfall_updated"]

    # поиск по-русски и по-английски
    found = (await client.get("/cards?q=кольцо")).json()
    assert [c["name"] for c in found] == ["Sol Ring"] and found[0]["name_ru"] == "Кольцо Сола"
    assert [c["name"] for c in (await client.get("/cards?q=delver")).json()] == ["Delver of Secrets // Insectile Aberration"]
    card = (await client.get(f"/cards/{found[0]['id']}")).json()
    assert card["legalities"]["vintage"] == "restricted" and card["prices"] == {"usd": 1.2, "eur": 1.05}
    assert card["text_ru"] == "{T}: добавьте {C}{C}." and card["extra"]["artist"] == "Mike Bierek"
    dfc = (await client.get(f"/cards/{(await client.get('/cards?q=похититель')).json()[0]['id']}")).json()
    assert len(dfc["extra"]["faces"]) == 2 and dfc["name_ru"] == "Похититель Тайн // Насекомое-Аберрация"

    # деклист на русском распознаётся
    r = await client.post("/auth/register", json={"email": "p@t.io", "password": "password1", "nickname": "Игрок"})
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    deck = (await client.post("/decks", json={"name": "Ру", "text": "1 Кольцо Сола\n1 Похититель Тайн\n1 Непонятная"},
                              headers=h)).json()
    assert deck["unmatched"] == ["Непонятная"]
    names = [c["name"] for c in (await client.get(f"/decks/{deck['id']}", headers=h)).json()["cards"]]
    assert "Sol Ring" in names and "Delver of Secrets // Insectile Aberration" in names


async def test_admin_endpoints_and_lock(client):
    async with SessionLocal() as s:
        await s.execute(text("INSERT INTO users (nickname, role, is_banned) VALUES ('Админ', 'admin', false)"))
        await s.commit()
        uid = (await s.execute(text("SELECT id FROM users"))).scalar()
    h = {"Authorization": f"Bearer {create_token(uid)}"}
    st = (await client.get("/admin/cards/sync/status", headers=h)).json()
    assert st == {"running": False, "last": None}

    async with SessionLocal() as holder:                  # загрузка «идёт» в другом процессе
        assert (await holder.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": scryfall.LOCK_ID})).scalar()
        assert (await client.get("/admin/cards/sync/status", headers=h)).json()["running"] is True
        assert (await client.post("/admin/cards/sync/scryfall", headers=h)).status_code == 409
        with pytest.raises(scryfall.SyncBusy):
            await scryfall.sync()
        await holder.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": scryfall.LOCK_ID})

    async def broken(request):
        return httpx.Response(500)
    async with httpx.AsyncClient(transport=httpx.MockTransport(broken)) as http:
        run = await scryfall.sync(client=http)
    assert run.cards == 0 and "500" in run.error
    last = (await client.get("/admin/cards/sync/status", headers=h)).json()["last"]
    assert last["cards"] == 0 and last["error"] and last["trigger"] == "admin"


async def test_schema_catch_up(client):
    async with engine.begin() as conn:                     # база «старой версии»: колонок ещё нет
        await conn.exec_driver_sql("DROP INDEX IF EXISTS ix_cards_name_ru_lower")
        await conn.exec_driver_sql("DROP INDEX IF EXISTS ix_cards_name_ru_front")
        await conn.exec_driver_sql("ALTER TABLE cards DROP COLUMN name_ru_lower, DROP COLUMN text_ru, DROP COLUMN name_ru_front")
        await conn.exec_driver_sql("DROP TABLE sync_runs")
    async with engine.begin() as conn:
        changes = await conn.run_sync(sync_schema)
    assert len(changes) == 3 and any("text_ru" in c for c in changes)
    async with engine.begin() as conn:
        cols = {r[0] for r in (await conn.exec_driver_sql(
            "SELECT column_name FROM information_schema.columns WHERE table_name='cards'")).all()}
        idx = (await conn.exec_driver_sql("SELECT 1 FROM pg_indexes WHERE indexname='ix_cards_name_ru_lower'")).all()
        runs = (await conn.exec_driver_sql("SELECT count(*) FROM sync_runs")).scalar()
    assert {"name_ru_lower", "text_ru"} <= cols and idx and runs == 0
    async with engine.begin() as conn:
        assert await conn.run_sync(sync_schema) == []      # повторный запуск ничего не меняет
