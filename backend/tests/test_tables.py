"""Столы клуба и бронирование: права, часы работы, шаг 30 минут, пересечения, лимит, уведомления.
Запуск: RUN_INTEGRATION=1 и DATABASE_URL."""
import os
from datetime import date, datetime, timedelta

import pytest

pytestmark = pytest.mark.skipif(not os.getenv("RUN_INTEGRATION"), reason="нужен PostgreSQL (RUN_INTEGRATION=1)")

if os.getenv("RUN_INTEGRATION"):
    import asyncio
    from zoneinfo import ZoneInfo

    import httpx
    from sqlalchemy import select

    from app.config import settings
    from app.db import Base, SessionLocal, engine
    from app.main import app
    from app.models import AuthAccount, OutboxMessage, Provider, TableBooking
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
    r = await c.post("/auth/register", json={"email": f"t{n}@example.com", "password": "password1", "nickname": f"Игрок{n}"})
    assert r.status_code == 200, r.text
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    return h, (await c.get("/auth/me", headers=h)).json()


def next_weekday(wd: int) -> date:
    """Ближайший будущий день недели (не сегодня, чтобы время не успело пройти)."""
    today = datetime.now(ZoneInfo(settings.app_timezone)).date()
    d = today + timedelta(days=1)
    while d.weekday() != wd:
        d += timedelta(days=1)
    return d


async def setup_club(c):
    org, org_me = await reg(c, 0)
    await make_creator(c, org)
    cid = (await c.post("/clubs", json={"name": "Антикафе Грифон"}, headers=org)).json()["id"]
    async with SessionLocal() as s:                   # у организатора привязан Telegram - ему придут сообщения
        s.add(AuthAccount(user_id=org_me["id"], provider=Provider.telegram, external_id="5550001"))
        await s.commit()
    return cid, org


async def test_tables_and_hours_managed_by_organizer(client):
    cid, org = await setup_club(client)
    ph, _ = await reg(client, 1)
    await client.post(f"/clubs/{cid}/join", headers=ph)
    body = {"name": "Стол 1", "seats": 6, "games": "MTG, EDH", "description": "У окна"}
    assert (await client.post(f"/clubs/{cid}/tables", json=body, headers=ph)).status_code == 403
    r = await client.post(f"/clubs/{cid}/tables", json=body, headers=org)
    assert r.status_code == 201 and r.json()["seats"] == 6
    tid = r.json()["id"]
    r = await client.patch(f"/clubs/{cid}/tables/{tid}", json={"name": "Большой стол"}, headers=org)
    assert r.json()["name"] == "Большой стол" and r.json()["games"] == "MTG, EDH"
    assert [t["name"] for t in (await client.get(f"/clubs/{cid}/tables")).json()] == ["Большой стол"]

    # часы по умолчанию 10-23; организатор задаёт свои, с работой после полуночи и выходным
    assert (await client.get(f"/clubs/{cid}/hours")).json()["days"]["0"] == ["10:00", "23:00"]
    hours = {"days": {"0": None, "4": ["18:00", "02:00"], "5": ["12:00", "24:00"]}}
    assert (await client.put(f"/clubs/{cid}/hours", json=hours, headers=ph)).status_code == 403
    assert (await client.put(f"/clubs/{cid}/hours", json={"days": {"1": ["10:15", "20:00"]}},
                             headers=org)).status_code == 422
    r = await client.put(f"/clubs/{cid}/hours", json=hours, headers=org)
    assert r.status_code == 200 and r.json()["days"] == {"4": ["18:00", "02:00"], "5": ["12:00", "24:00"]}
    mon = await client.get(f"/clubs/{cid}/bookings", params={"date": next_weekday(0).isoformat()})
    assert mon.json()["open"] is None                                     # понедельник - выходной
    fri = (await client.get(f"/clubs/{cid}/bookings", params={"date": next_weekday(4).isoformat()})).json()
    assert (fri["open"]["from"], fri["open"]["to"]) == ("18:00", "02:00")


async def test_booking_rules_and_notifications(client):
    cid, org = await setup_club(client)
    t1 = (await client.post(f"/clubs/{cid}/tables", json={"name": "Стол 1"}, headers=org)).json()["id"]
    t2 = (await client.post(f"/clubs/{cid}/tables", json={"name": "Стол 2"}, headers=org)).json()["id"]
    await client.put(f"/clubs/{cid}/hours", json={"days": {str(d): ["12:00", "02:00"] for d in range(7)}}, headers=org)
    ah, a = await reg(client, 1)
    bh, b = await reg(client, 2)
    day = next_weekday(5).isoformat()
    req = {"table_id": t1, "date": day, "start": "18:00", "duration": 180, "note": "Драфт на четверых"}

    # не участник клуба бронировать не может
    r = await client.post(f"/clubs/{cid}/bookings", json=req, headers=ah)
    assert r.status_code == 403 and "участники клуба" in r.json()["detail"]
    await client.post(f"/clubs/{cid}/join", headers=ah)
    await client.post(f"/clubs/{cid}/join", headers=bh)

    # шаг 30 минут и часы работы
    assert (await client.post(f"/clubs/{cid}/bookings", json={**req, "start": "18:10"}, headers=ah)).status_code == 422
    assert (await client.post(f"/clubs/{cid}/bookings", json={**req, "duration": 45}, headers=ah)).status_code == 422
    r = await client.post(f"/clubs/{cid}/bookings", json={**req, "start": "11:00"}, headers=ah)
    assert r.status_code == 400 and "12:00–02:00" in r.json()["detail"]
    far = (date.fromisoformat(day) + timedelta(days=70)).isoformat()
    assert (await client.post(f"/clubs/{cid}/bookings", json={**req, "date": far}, headers=ah)).status_code == 400

    r = await client.post(f"/clubs/{cid}/bookings", json=req, headers=ah)
    assert r.status_code == 201, r.text
    first = r.json()["id"]
    # пересечение на том же столе - нельзя; встык и на другом столе - можно
    r = await client.post(f"/clubs/{cid}/bookings", json={**req, "start": "20:30", "duration": 60}, headers=bh)
    assert r.status_code == 409 and "18:00–21:00" in r.json()["detail"]
    assert (await client.post(f"/clubs/{cid}/bookings", json={**req, "start": "21:00", "duration": 60},
                              headers=bh)).status_code == 201
    assert (await client.post(f"/clubs/{cid}/bookings", json={**req, "table_id": t2}, headers=bh)).status_code == 201
    # после полуночи - тот же рабочий день
    r = await client.post(f"/clubs/{cid}/bookings", json={**req, "start": "00:30", "duration": 90}, headers=ah)
    assert r.status_code == 201, r.text
    assert r.json()["when"].endswith("00:30–02:00")

    # расписание дня: участники видят ник, гость сайта - только занятость
    sched = (await client.get(f"/clubs/{cid}/bookings", params={"date": day}, headers=bh)).json()
    t1_slots = next(t for t in sched["tables"] if t["id"] == t1)["bookings"]
    assert [(s["from"], s["to"], s["nickname"], s["mine"]) for s in t1_slots] == [
        ("18:00", "21:00", "Игрок1", False), ("21:00", "22:00", "Игрок2", True), ("00:30", "02:00", "Игрок1", False)]
    anon = (await client.get(f"/clubs/{cid}/bookings", params={"date": day})).json()
    assert all(s["nickname"] is None for t in anon["tables"] for s in t["bookings"])

    # лимит будущих броней у игрока
    r = await client.post(f"/clubs/{cid}/bookings", json={**req, "table_id": t2, "start": "12:00", "duration": 60},
                          headers=bh)
    assert r.status_code == 201
    r = await client.post(f"/clubs/{cid}/bookings", json={**req, "table_id": t2, "start": "13:00", "duration": 60},
                          headers=bh)
    assert r.status_code == 400 and "максимум" in r.json()["detail"]

    # отменить чужую бронь нельзя, свою - можно, организатор - любую
    assert (await client.delete(f"/bookings/{first}", headers=bh)).status_code == 403
    assert (await client.delete(f"/bookings/{first}", headers=ah)).status_code == 204
    assert (await client.delete(f"/bookings/{first}", headers=ah)).status_code == 409
    mine_b = (await client.get("/bookings/mine", headers=bh)).json()
    assert len(mine_b) == 3 and mine_b[0]["club"] == "Антикафе Грифон"
    assert (await client.delete(f"/bookings/{mine_b[0]['id']}", headers=org)).status_code == 204

    # сообщения бота организатору в личку: новые брони и отмены
    async with SessionLocal() as s:
        msgs = (await s.execute(select(OutboxMessage).where(OutboxMessage.kind == "booking")
                                .order_by(OutboxMessage.id))).scalars().all()
    assert all(m.chat_id == "5550001" for m in msgs)
    texts = [m.text for m in msgs]
    # организатор сам себе не пишет: его отмена без сообщения
    assert sum("Новая бронь" in t for t in texts) == 5 and sum("Бронь отменена" in t for t in texts) == 1
    assert "Драфт на четверых" in texts[0] and "18:00–21:00" in texts[0] and "Игрок1" in texts[0]
    assert "Бронь отменена" in texts[-1] and "Игрок1" in texts[-1] and "Отменил" not in texts[-1]


async def test_no_double_booking_under_race(client):
    cid, org = await setup_club(client)
    t1 = (await client.post(f"/clubs/{cid}/tables", json={"name": "Стол 1"}, headers=org)).json()["id"]
    players = [await reg(client, i) for i in range(1, 5)]
    for h, _ in players:
        await client.post(f"/clubs/{cid}/join", headers=h)
    req = {"table_id": t1, "date": next_weekday(2).isoformat(), "start": "18:00", "duration": 120}
    codes = sorted(r.status_code for r in await asyncio.gather(
        *[client.post(f"/clubs/{cid}/bookings", json=req, headers=h) for h, _ in players]))
    assert codes == [201, 409, 409, 409]
    async with SessionLocal() as s:
        assert len((await s.execute(select(TableBooking))).scalars().all()) == 1


async def test_delete_table_with_future_bookings(client):
    cid, org = await setup_club(client)
    t1 = (await client.post(f"/clubs/{cid}/tables", json={"name": "Стол 1"}, headers=org)).json()["id"]
    ph, _ = await reg(client, 1)
    await client.post(f"/clubs/{cid}/join", headers=ph)
    bid = (await client.post(f"/clubs/{cid}/bookings", json={"table_id": t1, "date": next_weekday(3).isoformat(),
                                                             "start": "15:00", "duration": 60}, headers=ph)).json()["id"]
    r = await client.delete(f"/clubs/{cid}/tables/{t1}", headers=org)
    assert r.status_code == 409 and "будущие брони" in r.json()["detail"]
    await client.delete(f"/bookings/{bid}", headers=ph)
    assert (await client.delete(f"/clubs/{cid}/tables/{t1}", headers=org)).status_code == 204
    assert (await client.get(f"/clubs/{cid}/tables")).json() == []
