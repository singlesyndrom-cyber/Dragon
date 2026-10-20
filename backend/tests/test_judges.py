"""Судьи клуба: назначение по номеру, права по направлениям, главный судья, журнал правок, отчёт.
Запуск: RUN_INTEGRATION=1 и DATABASE_URL."""
import os

import pytest

pytestmark = pytest.mark.skipif(not os.getenv("RUN_INTEGRATION"), reason="нужен PostgreSQL (RUN_INTEGRATION=1)")

if os.getenv("RUN_INTEGRATION"):
    import httpx
    from sqlalchemy import select

    from app.db import Base, SessionLocal, engine
    from app.main import app
    from app.models import OutboxMessage


@pytest.fixture
async def client():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await engine.dispose()


async def reg(c, n):
    r = await c.post("/auth/register", json={"email": f"j{n}@example.com", "password": "password1", "nickname": f"Игрок{n}"})
    assert r.status_code == 200, r.text
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    return h, (await c.get("/auth/me", headers=h)).json()


async def test_judge_role_flow(client):
    org, _ = await reg(client, 0)
    jh, judge = await reg(client, 1)
    players = [await reg(client, i) for i in (2, 3)]
    club = (await client.post("/clubs", json={"name": "Судейский клуб", "telegram_chat_id": "-100777"}, headers=org)).json()
    cid = club["id"]

    # назначение: только организатор, по номеру, направления из списка
    body = {"player_no": judge["player_no"], "games": ["mtg"]}
    assert (await client.put(f"/clubs/{cid}/judges", json=body, headers=jh)).status_code == 403
    assert (await client.put(f"/clubs/{cid}/judges", json={**body, "games": ["chess"]}, headers=org)).status_code == 422
    r = await client.put(f"/clubs/{cid}/judges", json=body, headers=org)
    assert r.status_code == 200 and r.json()["games"] == ["mtg"], r.text
    org_no = (await client.get("/auth/me", headers=org)).json()["player_no"]
    assert (await client.put(f"/clubs/{cid}/judges", json={"player_no": org_no, "games": ["edh"]},
                             headers=org)).status_code == 400            # организатор и так судит всё
    staff = (await client.get(f"/clubs/{cid}/judges")).json()
    assert [(s["nickname"], s["organizer"], s["games"]) for s in staff] == [
        ("Игрок0", True, ["mtg", "edh", "berserk"]), ("Игрок1", False, ["mtg"])]
    assert (await client.get("/clubs/judging", headers=jh)).json() == [
        {"id": cid, "name": "Судейский клуб", "slug": club["slug"], "games": ["mtg"]}]
    assert (await client.get("/clubs/judging", headers=org)).json() == []
    mem = (await client.get(f"/clubs/{cid}/membership", headers=jh)).json()
    assert mem["judge_games"] == ["mtg"] and not mem["can_manage"]

    swiss = (await client.post("/tournaments", json={"club_id": cid, "name": "Пятница", "format": "swiss", "rounds": 1},
                               headers=org)).json()["id"]
    edh = (await client.post("/tournaments", json={"club_id": cid, "name": "Командир", "format": "edh"},
                             headers=org)).json()["id"]
    # судья не создаёт турниры и не меняет настройки
    assert (await client.post("/tournaments", json={"club_id": cid, "name": "Свой", "format": "swiss"},
                              headers=jh)).status_code == 403
    assert (await client.patch(f"/tournaments/{swiss}", json={"name": "Другое"}, headers=jh)).status_code == 403
    # ведёт турнир своего направления, а EDH - нет
    for _, p in players:
        r = await client.post(f"/tournaments/{swiss}/players", json={"player_no": p["player_no"]}, headers=jh)
        assert r.status_code == 201, r.text
    assert (await client.post(f"/tournaments/{edh}/players", json={"nickname": "Гость"}, headers=jh)).status_code == 403

    # главного судью назначает организатор; обычного игрока назначить нельзя
    assert (await client.put(f"/tournaments/{swiss}/judge", json={"user_id": judge["id"]}, headers=jh)).status_code == 403
    assert (await client.put(f"/tournaments/{swiss}/judge", json={"user_id": players[0][1]["id"]},
                             headers=org)).status_code == 400
    assert (await client.put(f"/tournaments/{edh}/judge", json={"user_id": judge["id"]}, headers=org)).status_code == 400
    assert (await client.put(f"/tournaments/{swiss}/judge", json={"user_id": judge["id"]}, headers=org)).status_code == 204
    card = (await client.get(f"/tournaments/{swiss}")).json()
    assert card["judge"] == {"user_id": judge["id"], "nickname": "Игрок1", "player_no": judge["player_no"]}

    assert (await client.post(f"/tournaments/{swiss}/start", headers=jh)).status_code == 200
    m = (await client.get(f"/tournaments/{swiss}/round/1")).json()[0]
    url = f"/tournaments/matches/{m['match_id']}/result"
    assert (await client.post(url, json={"result": "p1"}, headers=jh)).status_code == 204
    assert (await client.post(url, json={"result": "p1"}, headers=jh)).status_code == 204   # то же - не правка
    assert (await client.post(url, json={"result": "p2"}, headers=jh)).status_code == 204
    edits = (await client.get(f"/tournaments/{swiss}/edits")).json()
    assert len(edits) == 1 and edits[0]["by"] == "Игрок1" and (edits[0]["before"], edits[0]["after"]) == ("p1", "p2")
    assert {edits[0]["p1"], edits[0]["p2"]} == {"Игрок2", "Игрок3"}

    assert (await client.post(f"/tournaments/{swiss}/finish", headers=jh)).status_code == 200
    async with SessionLocal() as s:
        report = (await s.execute(select(OutboxMessage).where(OutboxMessage.kind == "tournament_report"))).scalar_one()
    assert f"Судья: Игрок1 (№{judge['player_no']})" in report.text

    pc = (await client.get(f"/players/{judge['player_no']}")).json()
    assert pc["judging"] == {"total": 1, "by_game": {"Magic": 1}}
    assert pc["clubs"][0]["judge"] == ["Magic"]

    # снятие судейства: права пропадают
    r = await client.put(f"/clubs/{cid}/judges", json={"player_no": judge["player_no"], "games": []}, headers=org)
    assert r.status_code == 200 and r.json()["games"] == []
    t2 = (await client.post("/tournaments", json={"club_id": cid, "name": "Суббота", "format": "swiss"},
                            headers=org)).json()["id"]
    assert (await client.post(f"/tournaments/{t2}/players", json={"nickname": "Гость"}, headers=jh)).status_code == 403
    assert [s["nickname"] for s in (await client.get(f"/clubs/{cid}/judges")).json()] == ["Игрок0"]


async def test_edh_judge_closes_tables(client):
    org, _ = await reg(client, 0)
    jh, judge = await reg(client, 1)
    club = (await client.post("/clubs", json={"name": "EDH клуб"}, headers=org)).json()
    await client.put(f"/clubs/{club['id']}/judges", json={"player_no": judge["player_no"], "games": ["edh"]}, headers=org)
    tid = (await client.post("/tournaments", json={"club_id": club["id"], "name": "Командир", "format": "edh"},
                             headers=org)).json()["id"]
    for name in ("Аня", "Борис", "Вера"):
        r = await client.post(f"/tournaments/{tid}/players", json={"nickname": name}, headers=jh)
        assert r.status_code == 201, r.text
    for p in (await client.get(f"/tournaments/{tid}")).json()["participants"]:
        assert (await client.put(f"/edh/{tid}/players/{p['user_id']}", json={"checked_in": True},
                                 headers=jh)).status_code == 204
    r = await client.post(f"/edh/{tid}/round", headers=jh)
    assert r.status_code == 200, r.text
    table = (await client.get(f"/edh/{tid}/tables")).json()[0]
    assert (await client.post(f"/edh/tables/{table['table_id']}/draw", headers=jh)).status_code == 204
