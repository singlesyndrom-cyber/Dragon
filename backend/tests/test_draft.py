"""Драфт: расписание пиков по MTR, рассадка по столам, первый тур по рассадке; API экрана судьи."""
import os
import random
from datetime import datetime, timedelta, timezone

import pytest

from app import draft as dl


def test_timeline_mtg_play_booster():
    cfg = dl.clean_config({}, "mtg")
    steps = dl.timeline(cfg)
    picks = [s for s in steps if s["kind"] == "pick"]
    assert len(picks) == 3 * 13                                  # 14 карт: 13 пиков по таймеру, последняя - без
    assert [s["seconds"] for s in picks[:13]] == [40, 35, 30, 25, 25, 20, 20, 15, 10, 10, 5, 5, 5]
    assert [s["direction"] for s in (picks[0], picks[13], picks[26])] == ["left", "right", "left"]
    assert [s["seconds"] for s in steps if s["kind"] == "review"] == [60, 90, 120]
    assert steps[-1] == {"kind": "build", "seconds": 25 * 60} and cfg["round_minutes"] == 50
    cfg15 = dl.clean_config({"cards": 15}, "mtg")
    assert [s["seconds"] for s in dl.timeline(cfg15)[:2]] == [40, 40]


def test_current_pause_skip_add():
    cfg = dl.clean_config({}, "mtg")
    t0 = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)
    st = {"started_at": t0.isoformat(), "offset": 0}
    cur = dl.current(cfg, st, t0 + timedelta(seconds=45))       # первый пик 40 с, идёт второй (35 с)
    assert cur["stage"] == "pick" and cur["step"]["pick"] == 2 and cur["left"] == 30
    st = dl.skip(cfg, st, t0 + timedelta(seconds=45))
    assert dl.current(cfg, st, t0 + timedelta(seconds=45))["step"]["pick"] == 3
    st = dl.add_time(cfg, st, t0 + timedelta(seconds=45), 10)
    assert dl.current(cfg, st, t0 + timedelta(seconds=45))["left"] == 40       # 30 с третьего пика + 10
    paused = {**st, "paused_at": (t0 + timedelta(seconds=45)).isoformat()}
    assert dl.current(cfg, paused, t0 + timedelta(hours=1))["left"] == 40     # на паузе время стоит
    total = sum(s["seconds"] for s in dl.timeline(cfg))
    assert dl.current(cfg, {"started_at": t0.isoformat()}, t0 + timedelta(seconds=total + 1))["stage"] == "done"


def test_pods_and_first_round():
    assert dl.pods(8) == [8] and dl.pods(10) == [5, 5] and dl.pods(17) == [6, 6, 5] and dl.pods(3) == [3]
    seating = dl.seat(list(range(1, 9)), random.Random(1))
    seat_of = {u: s for u, _, s in seating}
    pairs = dl.first_round_pairs(seating)
    assert len(pairs) == 4 and all(abs(seat_of[a] - seat_of[b]) == 4 for a, b in pairs)   # напротив, 1-5, 2-6…
    odd = dl.first_round_pairs([(u, 1 if u <= 5 else 2, u if u <= 5 else u - 5) for u in range(1, 11)])
    assert sorted(len([x for x in p if x]) for p in odd) == [2] * 5          # 5+5: по 2 пары и лишние играют между собой
    lone = dl.first_round_pairs([(1, 1, 1), (2, 1, 2), (3, 1, 3)])
    assert lone == [(1, 2), (3, None)]


pytestmark_db = pytest.mark.skipif(not os.getenv("RUN_INTEGRATION"), reason="нужен PostgreSQL (RUN_INTEGRATION=1)")

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


@pytestmark_db
async def test_draft_tournament_flow(client):
    c = client
    r = await c.post("/auth/register", json={"email": "j@t.io", "password": "password1", "nickname": "Судья"})
    org = {"Authorization": f"Bearer {r.json()['access_token']}"}
    await make_creator(c, org)
    cid = (await c.post("/clubs", json={"name": "Дракон"}, headers=org)).json()["id"]
    tid = (await c.post("/tournaments", json={"club_id": cid, "name": "Драфт 7-8-8", "game": "berserk", "format": "swiss",
                                              "rounds": 3, "silent": True, "draft": True,
                                              "draft_config": {"sets": "7-8-8", "cards": 11}}, headers=org)).json()["id"]
    t = (await c.get(f"/tournaments/{tid}")).json()
    assert t["draft"] is True and t["round_minutes"] == 50 and t["draft_sets"] == "7-8-8"
    for i in range(10):
        await c.post(f"/tournaments/{tid}/players", json={"nickname": f"Игрок {i}"}, headers=org)
    assert (await c.post(f"/tournaments/{tid}/draft/control", json={"action": "start"}, headers=org)).status_code == 400
    seat = (await c.post(f"/tournaments/{tid}/draft/seat", headers=org)).json()
    assert seat["pods"] == [5, 5] and all(s["seat"] for s in seat["seating"])
    cfg = (await c.put(f"/tournaments/{tid}/draft/config", json={"pick_seconds": {"11": 60}}, headers=org)).json()
    assert cfg["cards"] == 11 and cfg["pick_seconds"]["11"] == 60
    d = (await c.get(f"/tournaments/{tid}/draft")).json()
    assert d["state"]["stage"] == "seating" and d["timeline"][0]["seconds"] == 60
    cur = (await c.post(f"/tournaments/{tid}/draft/control", json={"action": "start"}, headers=org)).json()
    assert cur["stage"] == "pick" and cur["step"]["pack"] == 1 and cur["step"]["direction"] == "left"
    assert (await c.put(f"/tournaments/{tid}/draft/config", json={"cards": 12}, headers=org)).status_code == 400
    cur = (await c.post(f"/tournaments/{tid}/draft/control", json={"action": "skip"}, headers=org)).json()
    assert cur["step"]["pick"] == 2
    paused = (await c.post(f"/tournaments/{tid}/draft/control", json={"action": "pause"}, headers=org)).json()
    assert paused["paused"] is True
    # туры: первый - по рассадке (за каждым столом из 5: места 1-3, 2-4; пятые места играют между собой)
    assert (await c.post(f"/tournaments/{tid}/start", headers=org)).status_code == 200
    seats = {s["user_id"]: (s["pod"], s["seat"]) for s in (await c.get(f"/tournaments/{tid}/draft")).json()["seating"]}
    for m in (await c.get(f"/tournaments/{tid}/round/1")).json():
        (pa, sa), (pb, sb) = seats[m["p1_id"]], seats[m["p2_id"]]
        assert (pa == pb and abs(sa - sb) == 2) or (sa == sb == 5)
    t = (await c.get(f"/tournaments/{tid}")).json()
    assert t["round_started_at"] and t["round"] == 1
