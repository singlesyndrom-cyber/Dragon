"""Симуляция сезона EDH «Зима 2026» в клубе «Дракон»: 1 декабря 2026 – 28 февраля 2027, ивент каждое воскресенье.

Часы платформы подменяются, поэтому три месяца проживаются за секунды. Параллельно тест сам ведёт банки
по правилам (старт 1000, +150 раз в неделю пришедшим, победитель забирает 7% банка каждого соперника,
ничья или таймер - все теряют 7%) и после каждого ивента сверяет с таблицей сезона на сайте.
Запуск: RUN_INTEGRATION=1 и DATABASE_URL.
"""
import os
import random
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

pytestmark = pytest.mark.skipif(not os.getenv("RUN_INTEGRATION"), reason="нужен PostgreSQL (RUN_INTEGRATION=1)")

if os.getenv("RUN_INTEGRATION"):
    import httpx
    from sqlalchemy import select

    from app import leagues as L
    from app.db import Base, SessionLocal, engine
    from app.main import app
    from app.models import ClubMember, OutboxMessage
    from tests.helpers import make_creator

MSK = ZoneInfo("Europe/Moscow")
NICKS = ["Ярослав", "Мирослава", "Тимур", "Алина", "Глеб", "Вероника", "Савва", "Ульяна", "Платон", "Злата"]


@pytest.fixture
async def client():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await engine.dispose()


@pytest.fixture
def clock(monkeypatch):
    """Часы платформы: clock.set(datetime) переводит время."""
    class Clock:
        now = datetime(2026, 11, 15, 12, 0, tzinfo=MSK)

        def set(self, dt):
            self.now = dt
    c = Clock()
    monkeypatch.setattr(L, "now", lambda: c.now)
    return c


def sundays(start: date, end: date) -> list[date]:
    d = start + timedelta(days=(6 - start.weekday()) % 7)
    out = []
    while d <= end:
        out.append(d)
        d += timedelta(days=7)
    return out


def r2(x: float) -> float:
    return round(x, 2)


async def test_winter_2026_season(client, clock, capsys):
    rng = random.Random(2026)
    org = {"Authorization": f"Bearer {(await client.post('/auth/register', json={'email': 'drakon@example.com', 'password': 'password1', 'nickname': 'Организатор'})).json()['access_token']}"}
    await make_creator(client, org)
    club = (await client.post("/clubs", json={"name": "Дракон", "telegram_chat_id": "-100500"}, headers=org)).json()

    players = []
    for i, nick in enumerate(NICKS):
        r = await client.post("/auth/register", json={"email": f"w{i}@example.com", "password": "password1", "nickname": nick})
        me = (await client.get("/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"})).json()
        players.append({"id": me["id"], "no": me["player_no"], "nick": nick, "bracket": 2 if i < 6 else 3})
    by_id = {p["id"]: p for p in players}

    # --- сезон ---
    r = await client.post("/leagues", json={"club_id": club["id"], "name": "Зима 2026", "kind": "edh", "months": 3,
                                             "starts_on": "2026-12-01"}, headers=org)
    assert r.status_code == 201, r.text
    season = r.json()
    assert (season["starts_on"], season["ends_on"], season["status"]) == ("2026-12-01", "2027-02-28", "upcoming")
    days = sundays(date(2026, 12, 1), date(2027, 2, 28))
    assert len(days) == 13 and days[0] == date(2026, 12, 6) and days[-1] == date(2027, 2, 28)

    # ивент вне сезона не привязать
    for bad in ("2026-11-29T18:00:00", "2027-03-07T18:00:00"):
        r = await client.post("/tournaments", json={"club_id": club["id"], "name": "Вне сезона", "format": "edh",
                                                    "league_id": season["id"], "starts_at": bad}, headers=org)
        assert r.status_code == 400 and "вне сезона" in r.json()["detail"], r.text

    bank = {p["id"]: 1000.0 for p in players}   # модель: банк сезона
    events = {p["id"]: 0 for p in players}
    seen = set()
    stats = {"tables": 0, "win": 0, "draw": 0, "timeout": 0}

    for week, day in enumerate(days, 1):
        start = datetime(day.year, day.month, day.day, 18, 0, tzinfo=MSK)
        clock.set(start - timedelta(days=3))            # анонс и запись - в четверг
        r = await client.post("/tournaments", json={
            "club_id": club["id"], "name": f"Зима 2026 · неделя {week}", "format": "edh", "league_id": season["id"],
            "starts_at": start.replace(tzinfo=None).isoformat(), "description": "Воскресный EDH, банк сезона"}, headers=org)
        assert r.status_code == 201, r.text
        tid = r.json()["id"]
        came = rng.sample(players, rng.randint(6, 10))
        for p in came:
            r = await client.post(f"/tournaments/{tid}/players", json={"player_no": p["no"], "bracket": p["bracket"]},
                                  headers=org)
            assert r.status_code == 201, r.text
        clock.set(start)
        if week == 1:
            assert (await client.get(f"/leagues/{season['id']}")).json()["status"] == "active"
        for p in came:
            assert (await client.put(f"/edh/{tid}/players/{p['id']}", json={"checked_in": True},
                                     headers=org)).status_code == 204
            events[p["id"]] += 1
            bank[p["id"]] = r2(bank[p["id"]] + 150)       # надбавка недели - один раз, сколько бы ни было туров
            seen.add(p["id"])

        for rnd in (1, 2):
            if rnd == 2:
                # неделя 5: второй тур запущен после полуночи - надбавка не должна начислиться второй раз
                clock.set(start + (timedelta(hours=6, minutes=30) if week == 5 else timedelta(minutes=80)))
            r = await client.post(f"/edh/{tid}/round", headers=org)
            assert r.status_code == 200, r.text
            round_start = clock.now
            plan = []
            for tbl in (await client.get(f"/edh/{tid}/tables")).json():
                ids = [s["user_id"] for s in tbl["seats"]]
                assert 3 <= len(ids) <= 5
                roll = rng.random()
                plan.append((tbl, ids, "win" if roll < 0.7 else "draw" if roll < 0.9 else "timeout"))
            # победы и ничьи вносятся вовремя, столы по таймеру - после 70 минут
            for tbl, ids, outcome in sorted(plan, key=lambda x: x[2] == "timeout"):
                stats["tables"] += 1
                stats[outcome] += 1
                if outcome == "win":
                    winner = rng.choice(ids)
                    r = await client.post(f"/edh/tables/{tbl['table_id']}/win", json={"winner_id": winner}, headers=org)
                    losses = {u: r2(bank[u] * 0.07) for u in ids if u != winner}
                    for u, loss in losses.items():
                        bank[u] = r2(bank[u] - loss)
                    bank[winner] = r2(bank[winner] + r2(sum(losses.values())))
                else:
                    if outcome == "timeout":
                        clock.set(round_start + timedelta(minutes=71))
                        r = await client.post(f"/edh/tables/{tbl['table_id']}/timeout", headers=org)
                    else:
                        r = await client.post(f"/edh/tables/{tbl['table_id']}/draw", headers=org)
                    for u in ids:
                        bank[u] = r2(bank[u] - r2(bank[u] * 0.07))
                assert r.status_code == 204, r.text
            # победа у стола - игра с нулевой суммой
            for tbl in (await client.get(f"/edh/{tid}/tables?round_no={rnd}")).json():
                if tbl["outcome"] == "win":
                    assert abs(sum(s["delta"] for s in tbl["seats"])) < 0.02
        r = await client.post(f"/edh/{tid}/finish", headers=org)
        assert r.status_code == 200, r.text

        # таблица сезона на сайте = модель
        table = (await client.get(f"/leagues/{season['id']}")).json()["standings"]
        site = {row["user_id"]: row for row in table}
        assert set(site) == seen
        for uid in seen:
            assert abs(site[uid]["bank"] - bank[uid]) < 0.11, (week, by_id[uid]["nick"], site[uid]["bank"], bank[uid])
            assert site[uid]["events"] == events[uid]
        assert [row["bank"] for row in table] == sorted((row["bank"] for row in table), reverse=True)

    # --- после сезона ---
    clock.set(datetime(2027, 3, 1, 12, 0, tzinfo=MSK))
    final = (await client.get(f"/leagues/{season['id']}")).json()
    assert final["status"] == "finished" and final["events"] == 13 and len(final["tournaments"]) == 13
    r = await client.post("/tournaments", json={"club_id": club["id"], "name": "Опоздавший", "format": "edh",
                                                "league_id": season["id"]}, headers=org)
    assert r.status_code == 400 and "завершён" in r.json()["detail"]

    # клубный банк не тронут: сезон считает свой
    async with SessionLocal() as s:
        club_banks = (await s.execute(select(ClubMember.edh_bank).where(
            ClubMember.club_id == club["id"], ClubMember.user_id.in_(list(seen))))).scalars().all()
        reports = (await s.execute(select(OutboxMessage).where(OutboxMessage.kind == "tournament_report")
                                   .order_by(OutboxMessage.id))).scalars().all()
        announces = (await s.execute(select(OutboxMessage).where(OutboxMessage.kind == "tournament_announce"))).scalars().all()
    assert all(b == 1000 for b in club_banks)
    assert len(reports) == 13 and all("Сезон «Зима 2026»" in m.text for m in reports)
    assert len(announces) == 13

    # итог - в лог CI (аннотация), чтобы посмотреть сезон глазами
    rows = final["standings"]
    lines = [f"{i}. {r['nickname']} — банк {r['bank']:.1f} ({r['delta']:+.1f}), ивентов {r['events']}"
             for i, r in enumerate(rows, 1)]
    lines.append(f"Ивентов 13, столов {stats['tables']}: побед {stats['win']}, ничьих {stats['draw']}, "
                 f"по таймеру {stats['timeout']}. Сверка банков с моделью: сходится после каждого из 13 ивентов.")
    with capsys.disabled():   # мимо перехвата pytest: строка ::notice становится аннотацией в GitHub Actions
        print("::notice title=Сезон Зима 2026 (симуляция)::" + "%0A".join(lines), flush=True)
