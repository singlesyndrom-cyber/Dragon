"""Рейтинг силы через API: турнир, уровни, игроки из других городов, исключение, город. RUN_INTEGRATION=1."""
import os

import pytest

pytestmark = pytest.mark.skipif(not os.getenv("RUN_INTEGRATION"), reason="нужен PostgreSQL (RUN_INTEGRATION=1)")

if os.getenv("RUN_INTEGRATION"):
    import httpx
    from sqlalchemy import update

    from app.db import Base, SessionLocal, engine
    from app.main import app
    from app.models import GlobalRole, User
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
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    return h, (await c.get("/auth/me", headers=h)).json()


async def play(c, org, tid):
    """Старт, один тур: побеждает первый в паре, завершение."""
    assert (await c.post(f"/tournaments/{tid}/start", headers=org)).status_code == 200
    for m in (await c.get(f"/tournaments/{tid}/round/1")).json():
        if m.get("p2_id"):
            await c.post(f"/tournaments/matches/{m['match_id']}/result", json={"result": "p1"}, headers=org)
    assert (await c.post(f"/tournaments/{tid}/finish", headers=org)).status_code == 200


async def test_rating_flow(client):
    c = client
    org, org_me = await auth(c, "o@t.io", "Орг")
    await make_creator(c, org)
    async with SessionLocal() as s:
        await s.execute(update(User).where(User.id == org_me["id"]).values(role=GlobalRole.admin))
        await s.commit()
    cid = (await c.post("/clubs", json={"name": "Дракон", "city": "Севастополь"}, headers=org)).json()["id"]
    players = [await auth(c, f"p{i}@t.io", f"Игрок {i}") for i in range(4)]

    # клубный турнир с 4 игроками: рейтинг считается
    t1 = (await c.post("/tournaments", json={"club_id": cid, "name": "Пятница", "game": "berserk", "format": "swiss",
                                             "rounds": 1}, headers=org)).json()["id"]
    for h, _ in players:
        assert (await c.post(f"/tournaments/{t1}/register", headers=h)).status_code == 204
    await play(c, org, t1)
    tr = (await c.get(f"/ratings/tournaments/{t1}")).json()
    assert tr["discipline"] == "berserk_constructed" and tr["reason"] is None
    assert len(tr["changes"]) == 4 and sum(1 for x in tr["changes"] if x["delta"] > 0) == 2

    board = (await c.get("/ratings?discipline=berserk_constructed")).json()
    assert board["rows"] == []                                       # все ещё предварительные (меньше 10 партий)
    board = (await c.get("/ratings?discipline=berserk_constructed&include_provisional=true")).json()
    assert len(board["rows"]) == 4 and board["rows"][0]["city"] == "Севастополь"
    assert board["rows"][0]["provisional"] is True

    # уровень «Региональный чемпионат» назначает только администратор
    h0, me0 = players[0]
    await make_creator(c, h0)
    other = (await c.post("/clubs", json={"name": "Вавилон", "city": "Омск"}, headers=h0)).json()["id"]
    assert (await c.post("/tournaments", json={"club_id": other, "name": "Чемпионат", "game": "berserk",
                                               "tier": "regional"}, headers=h0)).status_code == 403
    t2 = (await c.post("/tournaments", json={"club_id": other, "name": "Открытый", "game": "berserk", "tier": "open",
                                             "rounds": 1}, headers=h0)).json()["id"]
    assert (await c.get(f"/tournaments/{t2}")).json()["tier"] == "open"
    # игрок из Севастополя записывается по своему аккаунту и не вступает в клуб Омска
    h1, me1 = players[1]
    assert (await c.post(f"/tournaments/{t2}/register", headers=h1)).status_code == 204
    mine = [x["name"] for x in (await c.get("/clubs/mine", headers=h1)).json()]
    assert mine == ["Дракон"]
    # организатор добавляет гостя другого города по номеру игрока - тоже без вступления
    h2, me2 = players[2]
    assert (await c.post(f"/tournaments/{t2}/players", json={"player_no": me2["player_no"]}, headers=h0)).status_code == 201
    assert [x["name"] for x in (await c.get("/clubs/mine", headers=h2)).json()] == ["Дракон"]

    # исключение администратором с причиной и возврат
    assert (await c.put(f"/ratings/tournaments/{t1}", json={"rated": False}, headers=org)).status_code == 422
    assert (await c.put(f"/ratings/tournaments/{t1}", json={"rated": False, "note": "проверка"}, headers=h0)).status_code == 403
    r = (await c.put(f"/ratings/tournaments/{t1}", json={"rated": False, "note": "договорные матчи"}, headers=org)).json()
    assert r["rated"] is False
    tr = (await c.get(f"/ratings/tournaments/{t1}")).json()
    assert tr["changes"] == [] and "договорные" in tr["reason"]
    await c.put(f"/ratings/tournaments/{t1}", json={"rated": True, "tier": "city"}, headers=org)
    assert len((await c.get(f"/ratings/tournaments/{t1}")).json()["changes"]) == 4

    # карточка игрока и свой город
    card = (await c.get(f"/ratings/player/{me1['player_no']}")).json()
    assert card["city"] == "Севастополь" and card["city_own"] is False
    assert card["ratings"][0]["discipline"] == "berserk_constructed" and len(card["ratings"][0]["history"]) == 1
    assert (await c.put("/ratings/me/city", json={"city": "  Симферополь "}, headers=h1)).json()["city"] == "Симферополь"
    board = (await c.get("/ratings?discipline=berserk_constructed&include_provisional=true&city=симферополь")).json()
    assert [x["user_id"] for x in board["rows"]] == [me1["id"]]
    assert (await c.get("/ratings/cities?discipline=berserk_constructed")).status_code == 200
    assert (await c.get("/ratings?discipline=chess")).status_code == 422

    # блокировка: партии игрока выпадают из рейтинга, турнир с 3 оставшимися не учитывается
    assert (await c.post(f"/admin/users/{me1['id']}/ban", json={"banned": True}, headers=org)).status_code == 204
    tr = (await c.get(f"/ratings/tournaments/{t1}")).json()
    assert tr["changes"] == [] and tr["reason"]
