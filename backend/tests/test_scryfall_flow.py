"""Загрузка базы MTG: подменённый сервер Scryfall, настоящий PostgreSQL."""
import gzip
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


def test_default_sql_forms():
    from sqlalchemy import Boolean, Column, DateTime, String, func, text
    from sqlalchemy.dialects import postgresql
    from app.schema import _default_sql
    d = postgresql.dialect()
    assert _default_sql(Column("a", DateTime, server_default=func.now()), d) == "now()"
    assert _default_sql(Column("b", Boolean, server_default=text("false")), d) == "false"
    assert _default_sql(Column("c", String, server_default="it's"), d) == "'it''s'"


def fake_scryfall(seen: list):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        url = str(request.url)
        if url == "https://api.scryfall.com/bulk-data":   # формат Scryfall с октября 2026: JSON Lines в gzip
            return httpx.Response(200, json={"data": [
                {"type": "default_cards", "jsonl_download_uri": "https://data.test/default.jsonl.gz"},
                {"type": "oracle_cards", "jsonl_download_uri": "https://data.test/oracle.jsonl.gz",
                 "compressed_size": 123}]})
        if url == "https://data.test/oracle.jsonl.gz":
            body = "\n".join(json.dumps(c, ensure_ascii=False) for c in ORACLE).encode()
            return httpx.Response(200, content=gzip.compress(body), headers={"content-type": "application/gzip"})
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


async def test_legacy_json_array_format(client):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/bulk-data"):
            return httpx.Response(200, json={"data": [{"type": "oracle_cards", "download_uri": "https://data.test/o.json"}]})
        if url == "https://data.test/o.json":
            return httpx.Response(200, content=json.dumps(ORACLE).encode())
        return httpx.Response(404)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        run = await scryfall.sync(client=http, russian=False)
    assert run.error is None and run.cards == 2


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
    assert run.cards == 0 and "500" in run.error and "попробуйте позже" in run.error

    async def no_dns(request):
        raise httpx.ConnectError("[Errno -5] No address associated with hostname")
    async with httpx.AsyncClient(transport=httpx.MockTransport(no_dns)) as http:
        run = await scryfall.sync(client=http)
    assert "DNS" in run.error and "Errno -5" in run.error
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

    # колонки со значением по умолчанию: у старых строк появляется значение, а не NULL
    async with engine.begin() as conn:
        await conn.exec_driver_sql("INSERT INTO users (nickname, role, is_banned) VALUES ('Старый', 'player', false)")
        await conn.exec_driver_sql("ALTER TABLE users DROP COLUMN is_guest")
        await conn.exec_driver_sql("INSERT INTO clubs (name, slug, description, city) VALUES ('Старый клуб', 'old', '', '')")
        cid = (await conn.exec_driver_sql("SELECT id FROM clubs WHERE slug='old'")).scalar()
        uid = (await conn.exec_driver_sql("SELECT id FROM users WHERE nickname='Старый'")).scalar()
        await conn.exec_driver_sql(
            f"INSERT INTO tournaments (club_id, name, game, format, status, current_round, created_by) "
            f"VALUES ({cid}, 'Старый', 'mtg', 'swiss', 'registration', 0, {uid})")
        await conn.exec_driver_sql("ALTER TABLE tournaments DROP COLUMN self_registration, DROP COLUMN deck_policy, "
                                   "DROP COLUMN description")
    async with engine.begin() as conn:
        changes = await conn.run_sync(sync_schema)
    assert any("self_registration" in c and "DEFAULT true NOT NULL" in c for c in changes), changes
    async with engine.begin() as conn:
        row = (await conn.exec_driver_sql(
            "SELECT self_registration, deck_policy, description FROM tournaments WHERE name='Старый'")).one()
        guest = (await conn.exec_driver_sql("SELECT is_guest FROM users WHERE nickname='Старый'")).scalar()
    assert tuple(row) == (True, "optional", "") and guest is False

    # ремонт базы, где колонки уже добавлены старой версией без значений по умолчанию (NULL в старых строках)
    async with engine.begin() as conn:
        await conn.exec_driver_sql("ALTER TABLE tournaments ALTER COLUMN self_registration DROP DEFAULT, "
                                   "ALTER COLUMN self_registration DROP NOT NULL, "
                                   "ALTER COLUMN deck_policy DROP DEFAULT, ALTER COLUMN deck_policy DROP NOT NULL")
        await conn.exec_driver_sql("UPDATE tournaments SET self_registration = NULL, deck_policy = NULL")
    async with engine.begin() as conn:
        fixes = await conn.run_sync(sync_schema)
    assert any("self_registration: заполнено 1" in c for c in fixes), fixes
    async with engine.begin() as conn:
        row = (await conn.exec_driver_sql("SELECT self_registration, deck_policy FROM tournaments WHERE name='Старый'")).one()
        nullable = (await conn.exec_driver_sql(
            "SELECT is_nullable FROM information_schema.columns WHERE table_name='tournaments' "
            "AND column_name='self_registration'")).scalar()
    assert tuple(row) == (True, "optional") and nullable == "NO"
    async with engine.begin() as conn:
        assert await conn.run_sync(sync_schema) == []      # после ремонта снова ничего не меняет


async def test_russian_names_survive_rate_limit(client, monkeypatch):
    """Scryfall ограничивает частоту поиска (429): ждём и повторяем; если так и не ответил - берём уже полученное."""
    async def no_wait(_):
        return None
    monkeypatch.setattr(scryfall.asyncio, "sleep", no_wait)
    calls = {"page2": 0}

    def make(limit_forever: bool):
        base = fake_scryfall([])._transport.handler

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/cards/search" and request.url.params.get("page") == "2":
                calls["page2"] += 1
                if limit_forever or calls["page2"] < 3:
                    return httpx.Response(429, headers={"Retry-After": "1"})
            return base(request)
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), headers=scryfall.HEADERS)

    async with make(limit_forever=False) as http:       # два отказа, потом ответ - загружено всё
        run = await scryfall.sync(client=http)
    assert run.error is None and run.russian == 2 and calls["page2"] == 3

    calls["page2"] = 0
    async with make(limit_forever=True) as http:        # всё время 429 - первая страница всё равно применена
        run = await scryfall.sync(client=http)
    assert run.russian == 1 and "частично" in run.error and calls["page2"] == scryfall.RETRIES
