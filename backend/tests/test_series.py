"""Еженедельная серия турниров и отложенные анонсы в чат клуба. RUN_INTEGRATION=1."""
import os
from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.skipif(not os.getenv("RUN_INTEGRATION"), reason="нужен PostgreSQL (RUN_INTEGRATION=1)")

if os.getenv("RUN_INTEGRATION"):
    from zoneinfo import ZoneInfo

    import httpx
    from sqlalchemy import select, update

    from app import notify
    from app.config import settings
    from app.db import Base, SessionLocal, engine
    from app.main import app
    from app.models import OutboxMessage, Tournament
    from tests.helpers import make_creator


@pytest.fixture
async def client():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await engine.dispose()


async def announces():
    async with SessionLocal() as s:
        return (await s.execute(select(OutboxMessage).where(OutboxMessage.kind == "tournament_announce")
                                .order_by(OutboxMessage.id))).scalars().all()


async def test_weekly_series_announced_a_week_ahead(client):
    r = await client.post("/auth/register", json={"email": "s@example.com", "password": "password1", "nickname": "Орг"})
    org = {"Authorization": f"Bearer {r.json()['access_token']}"}
    await make_creator(client, org)
    cid = (await client.post("/clubs", json={"name": "Дракон", "telegram_chat_id": "-100555"}, headers=org)).json()["id"]
    tz = ZoneInfo(settings.app_timezone)
    first = (datetime.now(tz) + timedelta(days=3)).replace(hour=18, minute=0, second=0, microsecond=0)
    base = {"club_id": cid, "name": "Воскресный EDH", "format": "edh", "max_players": 20,
            "starts_at": first.replace(tzinfo=None).isoformat()}
    until = (first + timedelta(weeks=12)).date().isoformat()

    r = await client.post("/tournaments/series", json={"tournament": base, "until": until}, headers=org)
    assert r.status_code == 201, r.text
    ids = r.json()["ids"]
    assert r.json()["count"] == 13
    rows = (await client.get(f"/tournaments?club_id={cid}&status=registration")).json()
    assert len(rows) == 13 and all(t["max_players"] == 20 for t in rows)
    starts = sorted(datetime.fromisoformat(t["starts_at"]).astimezone(tz) for t in rows)
    assert {d.weekday() for d in starts} == {first.weekday()} and {d.hour for d in starts} == {18}
    assert all((b - a) == timedelta(days=7) for a, b in zip(starts, starts[1:]))
    assert rows[0]["name"] == f"Воскресный EDH {first:%d.%m}"
    async with SessionLocal() as s:
        series = set((await s.execute(select(Tournament.series_id))).scalars())
    assert series == {ids[0]}

    # в чат ушёл только ближайший; остальные - за неделю до своей даты
    msgs = await announces()
    assert len(msgs) == 1 and f"{first:%d.%m}" in msgs[0].text
    assert msgs[0].buttons[0][0] == {"text": "✅ Записаться", "callback_data": f"reg:{ids[0]}"}
    async with SessionLocal() as s:
        assert await notify.announce_due(s) == 0
        # прошла неделя: второй турнир теперь ближе 7 дней
        await s.execute(update(Tournament).where(Tournament.id == ids[1])
                        .values(starts_at=datetime.now(timezone.utc) + timedelta(days=6)))
        await s.commit()
        assert await notify.announce_due(s) == 1
        assert await notify.announce_due(s) == 0
    assert len(await announces()) == 2

    # серия не длиннее 26 и только для организатора
    r = await client.post("/tournaments/series", json={"tournament": base, "until": (first + timedelta(weeks=40)).date().isoformat()},
                          headers=org)
    assert r.status_code == 400 and "максимум 26" in r.json()["detail"]
    r = await client.post("/tournaments/series", json={"tournament": {**base, "starts_at": None}, "until": until}, headers=org)
    assert r.status_code == 422


async def test_far_single_tournament_waits_for_its_week(client):
    r = await client.post("/auth/register", json={"email": "f@example.com", "password": "password1", "nickname": "Орг"})
    org = {"Authorization": f"Bearer {r.json()['access_token']}"}
    await make_creator(client, org)
    cid = (await client.post("/clubs", json={"name": "Клуб", "telegram_chat_id": "-100777"}, headers=org)).json()["id"]
    far = (datetime.now(timezone.utc) + timedelta(days=20)).replace(tzinfo=None).isoformat()
    await client.post("/tournaments", json={"club_id": cid, "name": "Через три недели", "format": "swiss", "starts_at": far},
                      headers=org)
    await client.post("/tournaments", json={"club_id": cid, "name": "Сегодня", "format": "swiss"}, headers=org)
    assert [m.text.count("Сегодня") for m in await announces()] == [1]
