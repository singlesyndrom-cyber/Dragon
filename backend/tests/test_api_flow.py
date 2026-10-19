"""Интеграционные тесты API на настоящем PostgreSQL. Запуск: RUN_INTEGRATION=1 и DATABASE_URL."""
import json
import os

import pytest

pytestmark = pytest.mark.skipif(not os.getenv("RUN_INTEGRATION"), reason="нужен PostgreSQL (RUN_INTEGRATION=1)")

if os.getenv("RUN_INTEGRATION"):
    import httpx
    from sqlalchemy import select, update

    from app.db import Base, SessionLocal, engine
    from app.main import app
    from app.models import GlobalRole, OutboxMessage, User


@pytest.fixture
async def client():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await engine.dispose()


async def reg(c, n):
    r = await c.post("/auth/register", json={"email": f"u{n}@test.io", "password": "password1", "nickname": f"Игрок{n}"})
    assert r.status_code == 200, r.text
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    me = (await c.get("/auth/me", headers=h)).json()
    return h, me["id"]


async def make_admin(uid):
    async with SessionLocal() as s:
        await s.execute(update(User).where(User.id == uid).values(role=GlobalRole.admin))
        await s.commit()


async def outbox():
    async with SessionLocal() as s:
        return (await s.execute(select(OutboxMessage).order_by(OutboxMessage.id))).scalars().all()


async def new_club(c, h, name="Дракон", chat="-100123"):
    r = await c.post("/clubs", json={"name": name, "telegram_chat_id": chat}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------------- авторизация
async def test_auth(client):
    h, uid = await reg(client, 1)
    r = await client.post("/auth/register", json={"email": "U1@test.io", "password": "password1", "nickname": "xx"})
    assert r.status_code == 409
    assert (await client.post("/auth/login", json={"email": "u1@test.io", "password": "bad-pass"})).status_code == 401
    r = await client.post("/auth/login", json={"email": "u1@test.io", "password": "password1"})
    assert r.status_code == 200
    assert (await client.get("/auth/me")).status_code == 401
    assert (await client.get("/auth/me", headers=h)).json()["providers"] == ["email"]


# ---------------------------------------------------------------- швейцарка
async def test_swiss_flow(client):
    users = [await reg(client, i) for i in range(5)]
    org = users[0][0]
    club = await new_club(client, org)
    r = await client.post("/tournaments", json={"club_id": club["id"], "name": "Пятница", "format": "swiss", "rounds": 2},
                          headers=org)
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    assert (await client.post("/tournaments", json={"club_id": club["id"], "name": "Чужой"}, headers=users[1][0])).status_code == 403

    for h, _ in users:
        assert (await client.post(f"/tournaments/{tid}/register", headers=h)).status_code == 204
    assert (await client.post(f"/tournaments/{tid}/register", headers=users[1][0])).status_code == 409
    assert (await client.post(f"/tournaments/{tid}/start", headers=users[1][0])).status_code == 403

    r = await client.post(f"/tournaments/{tid}/start", headers=org)
    assert r.status_code == 200, r.text
    assert r.json() == {"round": 1, "rounds_total": 2}

    for rnd in (1, 2):
        ms = (await client.get(f"/tournaments/{tid}/round/{rnd}")).json()
        assert len(ms) == 3 and sum(1 for m in ms if m["p2"] is None) == 1
        played = [m for m in ms if m["p2"]]
        early = await client.post(f"/tournaments/{tid}/next-round", headers=org)
        assert early.status_code == 400  # не все результаты
        for i, m in enumerate(played):
            res = "draw" if (rnd == 1 and i == 0) else "p1"
            r = await client.post(f"/tournaments/matches/{m['match_id']}/result", json={"result": res}, headers=org)
            assert r.status_code == 204, r.text
        if rnd == 1:
            r = await client.post(f"/tournaments/{tid}/next-round", headers=org)
            assert r.status_code == 200, r.text

    assert (await client.post(f"/tournaments/{tid}/next-round", headers=org)).status_code == 400  # туры кончились
    standings = (await client.get(f"/tournaments/{tid}/standings")).json()
    # 2 тура: 4 сыгранных матча (1 ничья = 2 очка, 3 победы = 9 очков) + 2 bye по 3 = 17
    assert sum(r["points"] for r in standings) == 17
    assert [r["rank"] for r in standings] == [1, 2, 3, 4, 5]

    r = await client.post(f"/tournaments/{tid}/finish", headers=org)
    assert r.status_code == 200, r.text
    assert r.json()["winner_id"] == standings[0]["user_id"]

    board = (await client.get(f"/clubs/{club['id']}/leaderboard")).json()
    assert sum(m["league_points"] for m in board) == 17 and all(m["events_played"] == 1 for m in board)
    page = (await client.get(f"/clubs/{club['slug']}")).json()
    assert page["tournaments_total"] == 1 and page["avg_participants"] == 5 and page["rating"] > 0

    kinds = [m.kind for m in await outbox()]
    assert kinds == ["tournament_announce", "tournament_report"]
    report = (await outbox())[1]
    assert "Итоги турнира" in report.text and report.chat_id == "-100123"


# ---------------------------------------------------------------- EDH
async def test_edh_flow(client):
    users = [await reg(client, i) for i in range(6)]
    org = users[0][0]
    club = await new_club(client, org)
    tid = (await client.post("/tournaments", json={"club_id": club["id"], "name": "EDH-вечер", "format": "edh"},
                             headers=org)).json()["id"]
    for i, (h, _) in enumerate(users):
        r = await client.post(f"/tournaments/{tid}/register?bracket={2 if i < 4 else 4}", headers=h)
        assert r.status_code == 204, r.text
    # до отметки прихода стола не будет
    assert (await client.post(f"/edh/{tid}/round", headers=org)).status_code == 400
    for _, uid in users:
        r = await client.put(f"/edh/{tid}/players/{uid}", json={"checked_in": True}, headers=org)
        assert r.status_code == 204, r.text

    r = await client.post(f"/edh/{tid}/round", headers=org)
    assert r.status_code == 200, r.text
    assert r.json()["tables"] == 2   # брекет 4 (2 игрока) влит в брекет 2 -> 6 игроков -> столы 3+3

    tables = (await client.get(f"/edh/{tid}/tables")).json()
    assert sorted(len(t["seats"]) for t in tables) == [3, 3]
    assert all(s["bank_before"] == 1150 for t in tables for s in t["seats"])  # 1000 + 150 недельная надбавка
    assert all(t["seconds_left"] > 69 * 60 for t in tables)

    t1, t2 = tables
    winner = t1["seats"][0]["user_id"]
    other = t2["seats"][0]["user_id"]
    assert (await client.post(f"/edh/tables/{t1['table_id']}/win", json={"winner_id": other},
                              headers=org)).status_code == 400  # победитель не за этим столом
    assert (await client.post(f"/edh/tables/{t1['table_id']}/win", json={"winner_id": winner},
                              headers=org)).status_code == 204
    assert (await client.post(f"/edh/tables/{t1['table_id']}/draw", headers=org)).status_code == 409  # уже закрыт
    assert (await client.post(f"/edh/tables/{t2['table_id']}/timeout", headers=org)).status_code == 400  # таймер не истёк
    assert (await client.post(f"/edh/tables/{t2['table_id']}/draw", headers=org)).status_code == 204

    tables = {t["table_id"]: t for t in (await client.get(f"/edh/{tid}/tables?round_no=1")).json()}
    s1 = {s["user_id"]: s for s in tables[t1["table_id"]]["seats"]}
    assert s1[winner]["delta"] == 161.0 and s1[winner]["bank_after"] == 1311.0
    assert all(s["delta"] == -80.5 for u, s in s1.items() if u != winner)
    assert sum(s["delta"] for s in s1.values()) == 0
    assert all(s["delta"] == -80.5 for s in tables[t2["table_id"]]["seats"])  # ничья: очки сгорают

    # второй тур в ту же неделю: надбавка повторно не начисляется
    assert (await client.post(f"/edh/{tid}/round", headers=org)).status_code == 200
    r2 = (await client.get(f"/edh/{tid}/tables")).json()
    banks = {s["user_id"]: s["bank_before"] for t in r2 for s in t["seats"]}
    assert banks[winner] == 1311.0 and banks[other] == 1069.5
    assert (await client.post(f"/edh/{tid}/finish", headers=org)).status_code == 400  # столы открыты
    for t in r2:
        assert (await client.post(f"/edh/tables/{t['table_id']}/draw", headers=org)).status_code == 204

    res = (await client.get(f"/edh/{tid}/results")).json()
    assert res[0]["user_id"] == winner and all(r["games"] == 2 for r in res)
    assert (await client.post(f"/edh/{tid}/finish", headers=org)).status_code == 200
    board = {m["user_id"]: m for m in (await client.get(f"/clubs/{club['id']}/leaderboard")).json()}
    assert all(m["events_played"] == 1 for m in board.values())
    assert [m.kind for m in await outbox()] == ["tournament_announce", "tournament_report"]
    assert "Банк клуба" in (await outbox())[1].text


# ---------------------------------------------------------------- карты, деклисты, мета
CARDS = [{"id": "c1", "name": "Atraxa, Praetors' Voice", "type": "Legendary Creature"},
         {"id": "c2", "name": "Sol Ring", "type": "Artifact"},
         {"id": "c3", "name": "Krenko, Mob Boss", "type": "Legendary Creature"},
         {"id": "c4", "name": "Arcane Signet", "type": "Artifact"}]


async def test_cards_decks_meta(client):
    (ah, aid), (h1, u1), (h2, u2) = [await reg(client, i) for i in range(3)]
    await make_admin(aid)
    files = {"file": ("cards.json", json.dumps(CARDS).encode(), "application/json")}
    assert (await client.post("/admin/cards/import/mtg", files=files, headers=h1)).status_code == 403
    r = await client.post("/admin/cards/import/mtg", files=files, data={"dry_run": "true"}, headers=ah)
    assert r.status_code == 200 and r.json()["would_import"] == 4, r.text
    r = await client.post("/admin/cards/import/mtg", files=files, headers=ah)
    assert r.json()["imported"] == 4
    assert (await client.post("/admin/cards/import/mtg", files=files, headers=ah)).json()["imported"] == 4  # upsert
    found = (await client.get("/cards?q=sol")).json()
    assert [c["name"] for c in found] == ["Sol Ring"]

    club = await new_club(client, ah)
    tid = (await client.post("/tournaments", json={"club_id": club["id"], "name": "Мета", "rounds": 1},
                             headers=ah)).json()["id"]
    decks = {}
    for h, uid, text in ((h1, u1, "Commander\n1 Atraxa, Praetors' Voice\n\nDeck\n1 Sol Ring (CMM) 400\n1x Arcane Signet\n10 Forest"),
                         (h2, u2, "1 Sol Ring\n1 Unknown Card")):
        extra = {} if h is h1 else {"commander": "Krenko, Mob Boss"}
        r = await client.post("/decks", json={"name": "Колода", "text": text, **extra}, headers=h)
        assert r.status_code == 201, r.text
        decks[uid] = r.json()
        assert (await client.put(f"/decks/{r.json()['id']}/attach/{tid}", headers=h)).status_code == 400  # не зарегистрирован
        assert (await client.post(f"/tournaments/{tid}/register", headers=h)).status_code == 204
        assert (await client.put(f"/decks/{r.json()['id']}/attach/{tid}", headers=h)).status_code == 204
    assert decks[u2]["unmatched"] == ["Unknown Card"]
    assert (await client.get(f"/decks/{decks[u1]['id']}", headers=h2)).status_code == 404  # чужая колода скрыта

    view = {p["user_id"]: p for p in (await client.get(f"/decks/tournament/{tid}", headers=ah)).json()}
    assert view[u1]["commanders"] == ["Atraxa, Praetors' Voice"] and view[u2]["unmatched"] == 1

    assert (await client.post(f"/tournaments/{tid}/start", headers=ah)).status_code == 200
    r = await client.put(f"/decks/{decks[u1]['id']}", json={"name": "x", "text": "1 Sol Ring"}, headers=h1)
    assert r.status_code == 409  # деклист заблокирован после старта
    m = (await client.get(f"/tournaments/{tid}/round/1")).json()[0]
    await client.post(f"/tournaments/matches/{m['match_id']}/result", json={"result": "p1"}, headers=ah)
    assert (await client.get("/meta/commanders")).json()["entries"] == 0  # турнир ещё не завершён
    fin = (await client.post(f"/tournaments/{tid}/finish", headers=ah)).json()

    meta = (await client.get("/meta/commanders?min_games=1")).json()
    assert meta["entries"] == 2
    rows = {c["commander"]: c for c in meta["commanders"]}
    win_cmd = "Atraxa, Praetors' Voice" if fin["winner_id"] == u1 else "Krenko, Mob Boss"
    assert rows[win_cmd]["win_rate"] == 1.0 and rows[win_cmd]["pick_rate"] == 0.5 and rows[win_cmd]["reliable"]
    staples = (await client.get("/meta/cards?min_decks=1")).json()
    usage = {c["card"]: c["usage_pct"] for c in staples["cards"]}
    assert usage["Sol Ring"] == 100.0 and usage["Arcane Signet"] == 50.0 and "Forest" not in usage


# ---------------------------------------------------------------- новости
async def test_news(client):
    (ah, aid), (oh, _), (ph, _) = [await reg(client, i) for i in range(3)]
    await make_admin(aid)
    club = await new_club(client, oh, chat="@dragon_club")
    assert (await client.post("/news/categories", json={"name": "Турниры"}, headers=oh)).status_code == 403
    assert (await client.post("/news/categories", json={"name": "Турниры"}, headers=ah)).json()["slug"] == "turniry"

    r = await client.post("/news", json={"title": "Старт платформы", "body_md": "**Привет**", "category": "turniry",
                                         "tags": ["#EDH", "edh", "Берсерк"], "publish": True}, headers=ah)
    assert r.status_code == 201, r.text
    g = r.json()
    assert g["slug"] == "start-platformy"
    assert (await client.post("/news", json={"title": "Старт платформы", "body_md": "x", "publish": True},
                              headers=ah)).json()["slug"] == "start-platformy-2"
    assert (await client.post("/news", json={"title": "Глобальная", "body_md": "x"}, headers=oh)).status_code == 403

    r = await client.post("/news", json={"title": "Новость клуба", "body_md": "x", "club_id": club["id"]}, headers=oh)
    local = r.json()
    assert local["status"] == "draft"
    assert (await client.get(f"/news/{local['slug']}")).status_code == 404       # черновик скрыт от гостей
    assert (await client.get(f"/news/{local['slug']}", headers=oh)).status_code == 200
    assert (await client.post(f"/news/{local['id']}/publish", headers=ph)).status_code == 403
    assert (await client.post(f"/news/{local['id']}/publish", headers=oh)).status_code == 204

    feed = (await client.get("/news")).json()
    assert len(feed) == 3
    assert [a["slug"] for a in (await client.get("/news?tag=edh")).json()] == ["start-platformy"]
    assert len((await client.get(f"/news?club_id={club['id']}")).json()) == 1
    art = (await client.get("/news/start-platformy")).json()
    assert {t["slug"] for t in art["tags"]} == {"edh", "berserk"} and art["category"]["slug"] == "turniry"

    cid = (await client.post("/news/start-platformy/comments", json={"body": "Круто!"}, headers=ph)).json()["id"]
    assert (await client.post(f"/news/comments/{cid}/hide", headers=ph)).status_code == 403
    assert (await client.post(f"/news/comments/{cid}/hide", headers=ah)).status_code == 204
    assert (await client.get("/news/start-platformy/comments")).json() == []
    mod_view = (await client.get("/news/start-platformy/comments", headers=ah)).json()
    assert mod_view[0]["is_hidden"] is True

    msgs = await outbox()   # глобальный канал не задан, клубная новость ушла в чат клуба
    assert [(m.kind, m.chat_id) for m in msgs] == [("article", "@dragon_club")]
    assert "Новость клуба" in msgs[0].text
