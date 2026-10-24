"""Приложение за столом: текущий матч, отчёт игрока, согласование и внесение судьёй. RUN_INTEGRATION=1."""
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
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    return h, (await c.get("/auth/me", headers=h)).json()


async def test_play_report_flow(client):
    c = client
    org, _ = await auth(c, "o@t.io", "Орг")
    await make_creator(c, org)
    cid = (await c.post("/clubs", json={"name": "Дракон", "city": "Севастополь"}, headers=org)).json()["id"]
    ps = [await auth(c, f"p{i}@t.io", f"Игрок {i}") for i in range(4)]
    tid = (await c.post("/tournaments", json={"club_id": cid, "name": "Пятница", "game": "mtg", "format": "swiss",
                                              "rounds": 2}, headers=org)).json()["id"]
    for h, _ in ps:
        assert (await c.post(f"/tournaments/{tid}/register", headers=h)).status_code == 204
    assert (await c.get("/play/current", headers=ps[0][0])).json() == []      # турнир ещё не начался
    assert (await c.post(f"/tournaments/{tid}/start", headers=org)).status_code == 200

    by_nick = {me["nickname"]: h for h, me in ps}
    pairs = (await c.get(f"/tournaments/{tid}/round/1")).json()
    m1, m2 = pairs
    h1, h2 = by_nick[m1["p1"]], by_nick[m1["p2"]]

    cur = (await c.get("/play/current", headers=h2)).json()
    assert len(cur) == 1 and cur[0]["opponent"]["nickname"] == m1["p1"] and cur[0]["side"] == "p2"
    assert cur[0]["table"] == m1["table"] and cur[0]["tournament"]["round"] == 1 and cur[0]["result"] is None

    # чужой матч - нельзя; неверный счёт - нельзя
    assert (await c.post(f"/play/matches/{m2['match_id']}/report", json={"outcome": "win"}, headers=h1)).status_code == 404
    assert (await c.post(f"/play/matches/{m1['match_id']}/report", json={"outcome": "win", "score": "две"},
                         headers=h1)).status_code == 400
    # игроки - не судьи
    assert (await c.get(f"/play/tournaments/{tid}/reports", headers=h1)).status_code == 403

    # p2 сообщает о победе 2-1 по счётчику жизней; p1 пока молчит
    r = await c.post(f"/play/matches/{m1['match_id']}/report", json={"outcome": "win", "score": "2-1", "source": "life"},
                     headers=h2)
    assert r.status_code == 200
    rep = (await c.get(f"/play/tournaments/{tid}/reports", headers=org)).json()
    it = rep["items"][0]
    assert it["p2_report"]["result"] == "p2" and it["p2_report"]["score"] == "1-2" and it["agreed"] is None
    assert it["suggested"] == "p2" and not it["conflict"]
    # соперник видит отчёт со своей стороны
    cur1 = (await c.get("/play/current", headers=h1)).json()[0]
    assert cur1["opp_report"] == {**cur1["opp_report"], "outcome": "loss", "score": "1-2"}

    # p1 не согласен - конфликт; «внести все согласованные» его не трогает
    await c.post(f"/play/matches/{m1['match_id']}/report", json={"outcome": "win", "score": "2-0"}, headers=h1)
    it = (await c.get(f"/play/tournaments/{tid}/reports", headers=org)).json()["items"][0]
    assert it["conflict"] and it["agreed"] is None
    assert (await c.post(f"/play/tournaments/{tid}/reports/apply", json={}, headers=org)).json()["applied"] == 0

    # p1 исправился - согласовано, судья вносит
    await c.post(f"/play/matches/{m1['match_id']}/report", json={"outcome": "loss", "score": "1-2"}, headers=h1)
    it = (await c.get(f"/play/tournaments/{tid}/reports", headers=org)).json()["items"][0]
    assert it["agreed"] == "p2" and it["score"] == "1-2"
    assert (await c.post(f"/play/tournaments/{tid}/reports/apply", json={}, headers=org)).json()["applied"] == 1
    assert next(p for p in (await c.get(f"/tournaments/{tid}/round/1")).json()
                if p["match_id"] == m1["match_id"])["result"] == "p2"
    assert (await c.get("/play/current", headers=h2)).json()[0]["result"] == "win"
    # после внесения отправлять поздно
    assert (await c.post(f"/play/matches/{m1['match_id']}/report", json={"outcome": "draw"},
                         headers=h1)).status_code == 409

    # второй стол: прислал один игрок - судья вносит выборочно
    g1 = by_nick[m2["p1"]]
    await c.post(f"/play/matches/{m2['match_id']}/report", json={"outcome": "draw"}, headers=g1)
    assert (await c.post(f"/play/tournaments/{tid}/reports/apply", json={"match_ids": [m2["match_id"]]},
                         headers=org)).json()["applied"] == 1
    assert (await c.post(f"/tournaments/{tid}/next-round", headers=org)).status_code == 200
    # новый тур: в приложении новый соперник, старый отчёт не мешает
    cur = (await c.get("/play/current", headers=h2)).json()[0]
    assert cur["tournament"]["round"] == 2 and cur["my_report"] is None
    # прошлый тур закрыт
    assert (await c.post(f"/play/matches/{m1['match_id']}/report", json={"outcome": "win"},
                         headers=h2)).status_code == 400
