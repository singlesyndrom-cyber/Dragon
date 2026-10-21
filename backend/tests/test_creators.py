"""Заявки на статус «Создатель Клуба»: подача, защита от спама, модерация, права. RUN_INTEGRATION=1."""
import os

import pytest

pytestmark = pytest.mark.skipif(not os.getenv("RUN_INTEGRATION"), reason="нужен PostgreSQL (RUN_INTEGRATION=1)")

if os.getenv("RUN_INTEGRATION"):
    import asyncio

    import httpx
    from sqlalchemy import select, text, update

    from app import mailer
    from app.db import Base, SessionLocal, engine
    from app.main import app
    from app.models import AuthAccount, ClubCreatorRequest, GlobalRole, OutboxMessage, Provider, User
    from app.schema import sync_schema


@pytest.fixture
async def client():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await engine.dispose()


@pytest.fixture
def mails(monkeypatch):
    sent = []

    async def fake(to, subject, body):
        sent.append({"to": to, "subject": subject, "body": body})
        return True
    monkeypatch.setattr(mailer, "send_mail", fake)
    return sent


async def reg(c, n):
    r = await c.post("/auth/register", json={"email": f"c{n}@example.com", "password": "password1", "nickname": f"Игрок{n}"})
    assert r.status_code == 200, r.text
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    return h, (await c.get("/auth/me", headers=h)).json()


async def make_admin(uid):
    async with SessionLocal() as s:
        await s.execute(update(User).where(User.id == uid).values(role=GlobalRole.admin))
        await s.commit()


REQ = {"club_name": "Драконье логово", "city": "Казань", "about": "Проводим пятничные турниры по Magic уже два года."}


async def test_request_and_approve(client, mails):
    ah, admin = await reg(client, 0)
    await make_admin(admin["id"])
    ph, player = await reg(client, 1)
    assert player["is_club_creator"] is False
    # без статуса клуб не создать
    r = await client.post("/clubs", json={"name": "Самовольный"}, headers=ph)
    assert r.status_code == 403 and "Создатель Клуба" in r.json()["detail"]
    assert (await client.get("/creator-requests/mine", headers=ph)).json() == {"is_club_creator": False, "request": None}

    assert (await client.post("/creator-requests", json={**REQ, "about": "мало"}, headers=ph)).status_code == 422
    r = await client.post("/creator-requests", json=REQ, headers=ph)
    assert r.status_code == 201 and r.json()["status"] == "pending", r.text
    # одна активная заявка
    r = await client.post("/creator-requests", json=REQ, headers=ph)
    assert r.status_code == 409 and "на рассмотрении" in r.json()["detail"]
    mine = (await client.get("/creator-requests/mine", headers=ph)).json()
    assert mine["request"]["status_text"] == "на рассмотрении"

    # список для админа: имя, номер, email, дата, статус
    rows = (await client.get("/admin/creator-requests?status=pending", headers=ah)).json()
    assert len(rows) == 1 and rows[0]["user"]["email"] == "c1@example.com" and rows[0]["user"]["nickname"] == "Игрок1"
    assert rows[0]["created_at"] and rows[0]["club_name"] == "Драконье логово"
    rid = rows[0]["id"]

    r = await client.post(f"/admin/creator-requests/{rid}/approve", headers=ah)
    assert r.status_code == 200 and r.json()["status"] == "approved"
    assert (await client.post(f"/admin/creator-requests/{rid}/reject", json={}, headers=ah)).status_code == 409
    assert (await client.get("/auth/me", headers=ph)).json()["is_club_creator"] is True
    assert mails[-1]["to"] == "c1@example.com" and "одобрена" in mails[-1]["subject"]
    r = await client.post("/clubs", json={"name": "Драконье логово"}, headers=ph)
    assert r.status_code == 201, r.text
    # со статусом новая заявка не нужна
    assert (await client.post("/creator-requests", json=REQ, headers=ph)).status_code == 409


async def test_reject_then_reapply(client, mails):
    ah, admin = await reg(client, 0)
    await make_admin(admin["id"])
    ph, player = await reg(client, 1)
    async with SessionLocal() as s:
        s.add(AuthAccount(user_id=player["id"], provider=Provider.telegram, external_id="424242"))
        await s.commit()
    rid = (await client.post("/creator-requests", json=REQ, headers=ph)).json()["id"]
    r = await client.post(f"/admin/creator-requests/{rid}/reject", json={"reason": "Укажите, где будете играть"},
                          headers=ah)
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    mine = (await client.get("/creator-requests/mine", headers=ph)).json()
    assert mine["request"]["status"] == "rejected" and mine["request"]["reject_reason"] == "Укажите, где будете играть"
    assert "Причина: Укажите" in mails[-1]["body"]
    async with SessionLocal() as s:
        msg = (await s.execute(select(OutboxMessage).where(OutboxMessage.kind == "creator_request"))).scalar_one()
    assert msg.chat_id == "424242" and "отклонена" in msg.text
    # после отказа - повторная заявка
    r = await client.post("/creator-requests", json={**REQ, "about": "Играем в антикафе «Грифон», по пятницам."},
                          headers=ph)
    assert r.status_code == 201
    statuses = [x["status"] for x in (await client.get("/admin/creator-requests", headers=ah)).json()]
    assert statuses == ["pending", "rejected"]          # активные сверху
    assert (await client.get("/auth/me", headers=ph)).json()["is_club_creator"] is False


async def test_permissions(client):
    ah, admin = await reg(client, 0)
    await make_admin(admin["id"])
    ph, player = await reg(client, 1)
    mh, moder = await reg(client, 2)
    rid = (await client.post("/creator-requests", json=REQ, headers=ph)).json()["id"]
    # обычный игрок не видит заявки и не может их решать или выдать себе статус
    assert (await client.get("/admin/creator-requests", headers=ph)).status_code == 403
    assert (await client.post(f"/admin/creator-requests/{rid}/approve", headers=ph)).status_code == 403
    assert (await client.put(f"/admin/users/{player['player_no']}/roles", json={"is_club_creator": True},
                             headers=ph)).status_code == 403
    assert (await client.get("/admin/creator-requests")).status_code == 401
    # модератора назначает только администратор; модератор решает заявки, но роли не раздаёт
    assert (await client.put(f"/admin/users/{moder['player_no']}/roles", json={"is_moderator": True},
                             headers=mh)).status_code == 403
    r = await client.put(f"/admin/users/{moder['player_no']}/roles", json={"is_moderator": True}, headers=ah)
    assert r.status_code == 200 and r.json()["is_moderator"] is True
    assert (await client.get("/auth/me", headers=mh)).json()["is_moderator"] is True
    assert (await client.put(f"/admin/users/{player['player_no']}/roles", json={"is_club_creator": True},
                             headers=mh)).status_code == 403
    assert (await client.post(f"/admin/creator-requests/{rid}/approve", headers=mh)).status_code == 200
    staff = (await client.get("/admin/staff", headers=mh)).json()
    assert {(s["nickname"], s["admin"], s["moderator"]) for s in staff} == {("Игрок0", True, False), ("Игрок2", False, True)}
    # администратор может снять статус
    r = await client.put(f"/admin/users/{player['player_no']}/roles", json={"is_club_creator": False}, headers=ah)
    assert r.json()["is_club_creator"] is False
    assert (await client.post("/clubs", json={"name": "После снятия"}, headers=ph)).status_code == 403


async def test_one_pending_enforced_by_database(client):
    """Даже при одновременной отправке в базе остаётся одна заявка на рассмотрении."""
    ph, _ = await reg(client, 1)
    codes = sorted(r.status_code for r in await asyncio.gather(
        *[client.post("/creator-requests", json=REQ, headers=ph) for _ in range(3)]))
    assert codes[0] == 201 and all(c == 409 for c in codes[1:])
    async with SessionLocal() as s:
        assert len((await s.execute(select(ClubCreatorRequest))).scalars().all()) == 1


async def test_existing_organizers_get_status_on_upgrade(client):
    """База до появления статуса: организаторы клубов получают его автоматически, остальные - нет."""
    oh, org = await reg(client, 1)
    _, other = await reg(client, 2)
    async with SessionLocal() as s:
        await s.execute(update(User).where(User.id == org["id"]).values(is_club_creator=True))
        await s.commit()
    await client.post("/clubs", json={"name": "Старый клуб"}, headers=oh)
    async with engine.begin() as conn:
        await conn.execute(text("ALTER TABLE users DROP COLUMN is_club_creator"))
        changes = await conn.run_sync(sync_schema)
        assert any("выдано организаторам 1" in c for c in changes)
    async with SessionLocal() as s:
        flags = dict((await s.execute(select(User.id, User.is_club_creator))).all())
    assert flags[org["id"]] is True and flags[other["id"]] is False
