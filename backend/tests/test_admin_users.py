"""Админка: карточка аккаунта, удаление без истории, объединение двух аккаунтов. RUN_INTEGRATION=1."""
import os

import pytest

pytestmark = pytest.mark.skipif(not os.getenv("RUN_INTEGRATION"), reason="нужен PostgreSQL (RUN_INTEGRATION=1)")

if os.getenv("RUN_INTEGRATION"):
    import httpx
    from sqlalchemy import select, update

    from app.db import Base, SessionLocal, engine
    from app.main import app
    from app.models import AuthAccount, ClubMember, Deck, GlobalRole, Provider, TournamentPlayer, User
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
    r = await c.post("/auth/register", json={"email": f"au{n}@example.com", "password": "password1", "nickname": f"Игрок{n}"})
    assert r.status_code == 200, r.text
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    return h, (await c.get("/auth/me", headers=h)).json()


async def make_admin(uid):
    async with SessionLocal() as s:
        await s.execute(update(User).where(User.id == uid).values(role=GlobalRole.admin))
        await s.commit()


async def test_lookup_and_delete(client):
    ah, a = await reg(client, 0)
    await make_admin(a["id"])
    ph, p = await reg(client, 1)
    assert (await client.get(f"/admin/users/lookup/{p['player_no']}", headers=ph)).status_code == 403
    card = (await client.get(f"/admin/users/lookup/{p['player_no']}", headers=ah)).json()
    assert card["nickname"] == "Игрок1" and card["emails"] == ["au1@example.com"] and card["tournaments"] == 0
    assert (await client.get("/admin/users/lookup/99999", headers=ah)).status_code == 404
    assert (await client.delete(f"/admin/users/{a['player_no']}", headers=ah)).status_code == 400   # себя нельзя

    # колода и вступление в клуб - не история: удаляется вместе с аккаунтом
    await client.post("/decks", json={"name": "К", "text": "1 Sol Ring"}, headers=ph)
    r = await client.delete(f"/admin/users/{p['player_no']}", headers=ah)
    assert r.status_code == 200 and r.json()["nickname"] == "Игрок1"
    async with SessionLocal() as s:
        assert (await s.execute(select(User).where(User.id == p["id"]))).first() is None
        assert (await s.execute(select(Deck))).first() is None
        assert (await s.execute(select(AuthAccount).where(AuthAccount.user_id == p["id"]))).first() is None
    # вход удалённым аккаунтом не работает
    assert (await client.post("/auth/login", json={"email": "au1@example.com", "password": "password1"})).status_code == 401

    # с историей турниров удалить нельзя
    oh, _ = await reg(client, 2)
    await make_creator(client, oh)
    cid = (await client.post("/clubs", json={"name": "Клуб"}, headers=oh)).json()["id"]
    tid = (await client.post("/tournaments", json={"club_id": cid, "name": "Турнир", "format": "swiss"}, headers=oh)).json()["id"]
    xh, x = await reg(client, 3)
    await client.post(f"/tournaments/{tid}/register", headers=xh)
    r = await client.delete(f"/admin/users/{x['player_no']}", headers=ah)
    assert r.status_code == 409 and "турниров: 1" in r.json()["detail"]


async def test_merge_moves_everything(client):
    ah, a = await reg(client, 0)
    await make_admin(a["id"])
    oh, _ = await reg(client, 1)
    await make_creator(client, oh)
    cid = (await client.post("/clubs", json={"name": "Дракон"}, headers=oh)).json()["id"]
    main_h, main = await reg(client, 2)
    dup_h, dup = await reg(client, 3)
    for h in (main_h, dup_h):
        await client.post(f"/clubs/{cid}/join", headers=h)
    async with SessionLocal() as s:   # у дубля - очки лиги и Telegram
        await s.execute(update(ClubMember).where(ClubMember.user_id == dup["id"]).values(league_points=9, events_played=3))
        await s.execute(update(ClubMember).where(ClubMember.user_id == main["id"]).values(league_points=4, events_played=1))
        s.add(AuthAccount(user_id=dup["id"], provider=Provider.telegram, external_id="4242"))
        await s.commit()
    t1 = (await client.post("/tournaments", json={"club_id": cid, "name": "Первый", "format": "swiss"}, headers=oh)).json()["id"]
    await client.post(f"/tournaments/{t1}/register", headers=dup_h)
    await client.post("/decks", json={"name": "Колода дубля", "text": "1 Sol Ring"}, headers=dup_h)

    body = {"from_no": dup["player_no"], "into_no": main["player_no"]}
    assert (await client.post("/admin/users/merge", json=body, headers=main_h)).status_code == 403
    assert (await client.post("/admin/users/merge", json={**body, "into_no": dup["player_no"]}, headers=ah)).status_code == 400
    r = await client.post("/admin/users/merge", json=body, headers=ah)
    assert r.status_code == 200, r.text
    assert r.json()["into"] == main["player_no"] and r.json()["nickname"] == "Игрок2"

    async with SessionLocal() as s:
        assert (await s.execute(select(User).where(User.id == dup["id"]))).first() is None
        m = (await s.execute(select(ClubMember).where(ClubMember.user_id == main["id"]))).scalar_one()
        assert (m.league_points, m.events_played) == (13, 4)
        assert (await s.execute(select(TournamentPlayer.user_id).where(TournamentPlayer.tournament_id == t1))).scalar_one() == main["id"]
        assert (await s.execute(select(Deck.user_id))).scalar_one() == main["id"]
        providers = sorted(p.value for p in (await s.execute(select(AuthAccount.provider).where(
            AuthAccount.user_id == main["id"]))).scalars())
    assert providers == ["email", "email", "telegram"]
    # теперь в основной аккаунт можно войти и почтой дубля
    r = await client.post("/auth/login", json={"email": "au3@example.com", "password": "password1"})
    assert r.status_code == 200
    me = (await client.get("/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"})).json()
    assert me["player_no"] == main["player_no"]

    # оба в одном турнире - отказ
    t2 = (await client.post("/tournaments", json={"club_id": cid, "name": "Второй", "format": "swiss"}, headers=oh)).json()["id"]
    zh, z = await reg(client, 4)
    for h in (main_h, zh):
        await client.post(f"/tournaments/{t2}/register", headers=h)
    r = await client.post("/admin/users/merge", json={"from_no": z["player_no"], "into_no": main["player_no"]}, headers=ah)
    assert r.status_code == 409 and "одном и том же турнире" in r.json()["detail"]
