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


async def test_play_edh_flow(client):
    c = client
    org, _ = await auth(c, "o@t.io", "Орг")
    await make_creator(c, org)
    cid = (await c.post("/clubs", json={"name": "Дракон", "city": "Севастополь"}, headers=org)).json()["id"]
    ps = [await auth(c, f"e{i}@t.io", f"Командир {i}") for i in range(4)]
    tid = (await c.post("/tournaments", json={"club_id": cid, "name": "EDH", "format": "edh"}, headers=org)).json()["id"]
    for h, me in ps:
        assert (await c.post(f"/tournaments/{tid}/register?bracket=2", headers=h)).status_code == 204
        assert (await c.put(f"/edh/{tid}/players/{me['id']}", json={"checked_in": True}, headers=org)).status_code == 204
    assert (await c.post(f"/edh/{tid}/round", headers=org)).status_code == 200

    h0, me0 = ps[0]
    cur = (await c.get("/play/current", headers=h0)).json()
    assert len(cur) == 1 and cur[0]["kind"] == "edh" and len(cur[0]["seats"]) == 4
    assert cur[0]["seconds_left"] > 0 and sum(s["me"] for s in cur[0]["seats"]) == 1
    table_id = cur[0]["table_id"]
    winner = ps[2][1]["id"]

    # победитель должен сидеть за столом; чужой стол - нельзя
    assert (await c.post(f"/play/edh/{table_id}/report", json={"outcome": "win", "winner_id": 999999},
                         headers=h0)).status_code == 400
    _, stranger = await auth(c, "x@t.io", "Чужой")
    assert (await c.post(f"/play/edh/{table_id}/report", json={"outcome": "draw"},
                         headers=_)).status_code == 404

    # один отчёт - ещё не согласовано
    await c.post(f"/play/edh/{table_id}/report", json={"outcome": "win", "winner_id": winner, "source": "life"}, headers=h0)
    it = (await c.get(f"/play/tournaments/{tid}/edh-reports", headers=org)).json()["items"][0]
    assert not it["agreed"] and it["suggested"]["winner_id"] == winner and it["in_time"]
    assert (await c.post(f"/play/tournaments/{tid}/edh-reports/apply", json={}, headers=org)).json()["applied"] == 0
    # второй игрок сказал «ничья» - конфликт
    await c.post(f"/play/edh/{table_id}/report", json={"outcome": "draw"}, headers=ps[1][0])
    it = (await c.get(f"/play/tournaments/{tid}/edh-reports", headers=org)).json()["items"][0]
    assert it["conflict"] and it["suggested"] is None
    # исправился - согласовано; другие игроки видят отчёты
    await c.post(f"/play/edh/{table_id}/report", json={"outcome": "win", "winner_id": winner}, headers=ps[1][0])
    seen = (await c.get("/play/current", headers=ps[2][0])).json()[0]["reports"]
    assert len(seen) == 2 and all(r["winner"] == ps[2][1]["nickname"] for r in seen)
    it = (await c.get(f"/play/tournaments/{tid}/edh-reports", headers=org)).json()["items"][0]
    assert it["agreed"]
    assert (await c.get(f"/play/tournaments/{tid}/edh-reports", headers=h0)).status_code == 403
    assert (await c.post(f"/play/tournaments/{tid}/edh-reports/apply", json={}, headers=org)).json()["applied"] == 1
    t = next(x for x in (await c.get(f"/edh/{tid}/tables")).json() if x["table_id"] == table_id)
    assert t["status"] == "finished" and t["outcome"] == "win"
    cur = (await c.get("/play/current", headers=ps[2][0])).json()[0]
    assert cur["status"] == "finished" and cur["winner"] == ps[2][1]["nickname"]
    # стол закрыт - отчёты больше не принимаются
    assert (await c.post(f"/play/edh/{table_id}/report", json={"outcome": "draw"}, headers=h0)).status_code == 409
