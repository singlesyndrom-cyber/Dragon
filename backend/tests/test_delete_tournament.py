"""Удаление турнира: права (организатор, судья по направлению), откат очков лиги и банков EDH, уборка гостей.
Запуск: RUN_INTEGRATION=1 и DATABASE_URL."""
import os

import pytest

pytestmark = pytest.mark.skipif(not os.getenv("RUN_INTEGRATION"), reason="нужен PostgreSQL (RUN_INTEGRATION=1)")

if os.getenv("RUN_INTEGRATION"):
    import httpx
    from sqlalchemy import select

    from app.db import Base, SessionLocal, engine
    from app.main import app
    from app.models import ClubMember, ClubStats, Match, TournamentPlayer, User
    from tests.helpers import make_creator


@pytest.fixture
async def client():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await engine.dispose()


async def reg(c, n):
    r = await c.post("/auth/register", json={"email": f"d{n}@example.com", "password": "password1", "nickname": f"Игрок{n}"})
    assert r.status_code == 200, r.text
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    return h, (await c.get("/auth/me", headers=h)).json()


async def club_with_staff(c):
    org, _ = await reg(c, 0)
    mtg_h, mtg = await reg(c, 1)
    edh_h, edh = await reg(c, 2)
    pl_h, pl = await reg(c, 3)
    await make_creator(c, org)
    cid = (await c.post("/clubs", json={"name": "Клуб удаления"}, headers=org)).json()["id"]
    await c.put(f"/clubs/{cid}/judges", json={"player_no": mtg["player_no"], "games": ["mtg"]}, headers=org)
    await c.put(f"/clubs/{cid}/judges", json={"player_no": edh["player_no"], "games": ["edh"]}, headers=org)
    return cid, org, mtg_h, edh_h, (pl_h, pl)


async def play_swiss(c, cid, h, name, players):
    tid = (await c.post("/tournaments", json={"club_id": cid, "name": name, "format": "swiss", "rounds": 2},
                        headers=h)).json()["id"]
    for p in players:
        body = {"user_id": p} if isinstance(p, int) else {"nickname": p}
        assert (await c.post(f"/tournaments/{tid}/players", json=body, headers=h)).status_code == 201
    assert (await c.post(f"/tournaments/{tid}/start", headers=h)).status_code == 200
    for rnd in (1, 2):
        for m in (await c.get(f"/tournaments/{tid}/round/{rnd}")).json():
            if m.get("p2"):
                await c.post(f"/tournaments/matches/{m['match_id']}/result", json={"result": "p1"}, headers=h)
        if rnd == 1:
            assert (await c.post(f"/tournaments/{tid}/next-round", headers=h)).status_code == 200
    assert (await c.post(f"/tournaments/{tid}/finish", headers=h)).status_code == 200
    return tid


async def points(cid):
    async with SessionLocal() as s:
        rows = (await s.execute(select(User.nickname, ClubMember.league_points, ClubMember.events_played)
                                .join(User, User.id == ClubMember.user_id).where(ClubMember.club_id == cid))).all()
    return {n: (p, e) for n, p, e in rows}


async def test_swiss_delete_reverts_and_cleans_guests(client):
    cid, org, mtg_h, edh_h, (pl_h, pl) = await club_with_staff(client)
    keep = await play_swiss(client, cid, org, "Настоящий", [pl["id"], "Гость Постоянный", "Гость А", "Гость Б"])
    before = await points(cid)
    test = await play_swiss(client, cid, org, "Тестовый", [pl["id"], "Гость Постоянный", "Гость Тест1", "Гость Тест2"])
    assert (await points(cid))["Игрок3"] != before["Игрок3"]

    # обычный игрок и судья другого направления удалить не могут
    assert (await client.delete(f"/tournaments/{test}", headers=pl_h)).status_code == 403
    assert (await client.delete(f"/tournaments/{test}", headers=edh_h)).status_code == 403
    assert (await client.delete(f"/tournaments/{test}")).status_code == 401
    # судья MTG - может
    r = await client.delete(f"/tournaments/{test}", headers=mtg_h)
    assert r.status_code == 200, r.text
    assert r.json() == {"deleted": test, "guests_removed": 2}
    assert (await client.get(f"/tournaments/{test}")).status_code == 404

    after = await points(cid)
    assert after == before                       # очки лиги и счётчики вернулись как до тестового турнира
    async with SessionLocal() as s:
        names = set((await s.execute(select(User.nickname).where(User.is_guest.is_(True)))).scalars())
        assert names == {"Гость Постоянный", "Гость А", "Гость Б"}       # гость из другого турнира остался
        assert not (await s.execute(select(Match).where(Match.tournament_id == test))).first()
        assert not (await s.execute(select(TournamentPlayer).where(TournamentPlayer.tournament_id == test))).first()
        stats = await s.get(ClubStats, cid)
        assert stats.tournaments_total == 1 and stats.participants_total == 4
    assert (await client.get(f"/tournaments/{keep}")).status_code == 200


async def test_registration_delete_by_organizer(client):
    cid, org, mtg_h, edh_h, _ = await club_with_staff(client)
    tid = (await client.post("/tournaments", json={"club_id": cid, "name": "Черновик", "format": "edh"},
                             headers=org)).json()["id"]
    await client.post(f"/tournaments/{tid}/players", json={"nickname": "Гость Черновика"}, headers=org)
    assert (await client.delete(f"/tournaments/{tid}", headers=mtg_h)).status_code == 403   # EDH - не его направление
    r = await client.delete(f"/tournaments/{tid}", headers=org)
    assert r.status_code == 200 and r.json()["guests_removed"] == 1


async def test_edh_delete_reverts_banks(client):
    cid, org, mtg_h, edh_h, _ = await club_with_staff(client)
    tid = (await client.post("/tournaments", json={"club_id": cid, "name": "Командир", "format": "edh"},
                             headers=org)).json()["id"]
    for n in ("Аня", "Борис", "Вера"):
        await client.post(f"/tournaments/{tid}/players", json={"nickname": n}, headers=org)
    card = (await client.get(f"/tournaments/{tid}")).json()
    for p in card["participants"]:
        await client.put(f"/edh/{tid}/players/{p['user_id']}", json={"checked_in": True}, headers=org)
    assert (await client.post(f"/edh/{tid}/round", headers=org)).status_code == 200
    banks0 = {}
    async with SessionLocal() as s:
        for m in (await s.execute(select(ClubMember).where(ClubMember.club_id == cid))).scalars():
            banks0[m.user_id] = m.edh_bank       # после надбавки недели, до игры
    table = (await client.get(f"/edh/{tid}/tables")).json()[0]
    winner = table["seats"][0]["user_id"]
    assert (await client.post(f"/edh/tables/{table['table_id']}/win", json={"winner_id": winner},
                              headers=org)).status_code == 204
    assert (await client.post(f"/edh/{tid}/finish", headers=org)).status_code == 200
    async with SessionLocal() as s:
        moved = {m.user_id: m.edh_bank for m in (await s.execute(select(ClubMember).where(ClubMember.club_id == cid))).scalars()}
    assert moved[winner] > banks0[winner]
    # судья EDH удаляет; банки откатываются, гости без других турниров удаляются вместе с записями клуба
    keep_guest = (await client.post("/tournaments", json={"club_id": cid, "name": "Ещё", "format": "edh"},
                                    headers=org)).json()["id"]
    await client.post(f"/tournaments/{keep_guest}/players", json={"user_id": winner}, headers=org)
    r = await client.delete(f"/tournaments/{tid}", headers=edh_h)
    assert r.status_code == 200 and r.json()["guests_removed"] == 2, r.text
    async with SessionLocal() as s:
        m = (await s.execute(select(ClubMember).where(ClubMember.club_id == cid, ClubMember.user_id == winner))).scalar_one()
    assert m.edh_bank == pytest.approx(banks0[winner]) and m.events_played == 0
