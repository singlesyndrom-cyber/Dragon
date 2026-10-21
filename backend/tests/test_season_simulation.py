"""Симуляция сезона EDH «Зима 2026»: 20 игроков, ивент каждое воскресенье с 6 декабря 2026 по 28 февраля 2027.

Часы платформы подменяются, поэтому сезон проходит «по календарю»: создаётся в ноябре, играется
13 воскресений, после 28 февраля закрывается. Каждый стол проверяется по правилам банка (7%, нулевая сумма
при победе, сгорание при ничьей и таймере), надбавка +150 - раз в неделю только пришедшим.
Итоговый отчёт пишется в season-report.md (CI сохраняет его как артефакт).
RUN_INTEGRATION=1.
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
CLOCK = {"now": datetime(2026, 11, 1, 12, 0, tzinfo=MSK)}
NAMES = ["Аня", "Борис", "Вера", "Глеб", "Даша", "Егор", "Жанна", "Захар", "Ира", "Кирилл",
         "Лена", "Миша", "Нина", "Олег", "Полина", "Роман", "Света", "Тимур", "Ульяна", "Фёдор"]
SUNDAYS = [date(2026, 12, 6) + timedelta(weeks=k) for k in range(13)]
RATE = 0.07


@pytest.fixture
async def client(monkeypatch):
    monkeypatch.setattr(L, "now", lambda: CLOCK["now"])
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await engine.dispose()


async def reg(c, email, nick):
    r = await c.post("/auth/register", json={"email": email, "password": "password1", "nickname": nick})
    assert r.status_code == 200, r.text
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    return h, (await c.get("/auth/me", headers=h)).json()


def ok(r, code=200):
    assert r.status_code == code, f"{r.request.method} {r.request.url.path} -> {r.status_code}: {r.text}"
    return r.json() if r.content else None


async def test_winter_2026_edh_season(client):
    rng = random.Random(2026)
    c = client
    org, _ = await reg(c, "owner@example.com", "Владелец")
    await make_creator(c, org)
    club = ok(await c.post("/clubs", json={"name": "Дракон", "telegram_chat_id": "-100500"}, headers=org), 201)

    # ---------- сезон и расписание (ноябрь) ----------
    season = ok(await c.post("/leagues", json={"club_id": club["id"], "name": "Зима 2026", "kind": "edh", "months": 3,
                                               "starts_on": "2026-12-01"}, headers=org), 201)
    assert (season["starts_on"], season["ends_on"], season["status"]) == ("2026-12-01", "2027-02-28", "upcoming")
    lid = season["id"]
    events = []
    for d in SUNDAYS:
        assert d.weekday() == 6
        t = ok(await c.post("/tournaments", json={
            "club_id": club["id"], "name": f"Воскресный EDH {d:%d.%m}", "format": "edh", "league_id": lid,
            "max_players": 20, "starts_at": f"{d.isoformat()}T18:00:00+03:00",
            "description": "Банк сезона, столы по 3–5, 70 минут"}, headers=org), 201)
        events.append((d, t["id"]))
    # ивент за пределами сезона не привязать
    r = await c.post("/tournaments", json={"club_id": club["id"], "name": "Март", "format": "edh", "league_id": lid,
                                           "starts_at": "2027-03-07T18:00:00+03:00"}, headers=org)
    assert r.status_code == 400 and "вне сезона" in r.json()["detail"]
    sched = ok(await c.get(f"/leagues/{lid}"))
    assert len(sched["tournaments"]) == 13

    players = []
    for i, nick in enumerate(NAMES):
        h, me = await reg(c, f"p{i}@example.com", nick)
        players.append({"h": h, "id": me["id"], "nick": nick, "bracket": rng.choice([2, 2, 3, 3, 3, 4])})
    by_id = {p["id"]: p for p in players}
    extra, _ = await reg(c, "late@example.com", "Опоздавший")

    # ---------- модель банка, которую сверяем с платформой ----------
    bank: dict[int, float] = {}            # банк сезона по нашим расчётам
    attended: dict[int, int] = {}
    burned = 0.0
    weeks = []
    stats = {"tables": 0, "win": 0, "draw": 0, "timeout": 0, "sizes": {}}

    for week_no, (d, tid) in enumerate(events, 1):
        CLOCK["now"] = datetime(d.year, d.month, d.day, 17, 0, tzinfo=MSK)
        come = rng.sample(players, rng.randint(12, 20))
        no_show = rng.sample([p for p in players if p not in come], min(2, 20 - len(come)))
        for p in come + no_show:          # записались; часть не пришла
            ok(await c.post(f"/tournaments/{tid}/register?bracket={p['bracket']}", headers=p["h"]), 204)
        if len(come) + len(no_show) == 20:  # лимит 20 мест
            r = await c.post(f"/tournaments/{tid}/register", headers=extra)
            assert r.status_code == 400, r.text
        for p in come:
            ok(await c.put(f"/edh/{tid}/players/{p['id']}", json={"checked_in": True}, headers=org), 204)

        week = {"date": d, "came": len(come), "tables": 0, "win": 0, "draw": 0, "timeout": 0}
        rounds = 2 if rng.random() < 0.6 else 1
        for rnd in range(1, rounds + 1):
            CLOCK["now"] = datetime(d.year, d.month, d.day, 18, 0, tzinfo=MSK) + timedelta(minutes=80 * (rnd - 1))
            ok(await c.post(f"/edh/{tid}/round", headers=org))
            tables = ok(await c.get(f"/edh/{tid}/tables"))
            seated = [s["user_id"] for tb in tables for s in tb["seats"]]
            assert sorted(seated) == sorted(p["id"] for p in come), "за столы садятся ровно пришедшие"
            for tb in tables:
                assert 3 <= len(tb["seats"]) <= 5, f"стол на {len(tb['seats'])}"
                stats["sizes"][len(tb["seats"])] = stats["sizes"].get(len(tb["seats"]), 0) + 1
                if rnd == 1:  # надбавка +150 один раз за неделю, до первого стола
                    for s in tb["seats"]:
                        expected = bank.get(s["user_id"], 1000.0) + 150
                        assert abs(s["bank_before"] - expected) < 0.01, (by_id[s["user_id"]]["nick"], s["bank_before"], expected)
                        bank[s["user_id"]] = expected
                else:
                    for s in tb["seats"]:
                        assert abs(s["bank_before"] - bank[s["user_id"]]) < 0.01, "во втором туре надбавки нет"
            # исходы столов
            pending_timeouts = []
            for tb in tables:
                roll = rng.random()
                ids = [s["user_id"] for s in tb["seats"]]
                if roll < 0.7:
                    winner = rng.choice(ids)
                    ok(await c.post(f"/edh/tables/{tb['table_id']}/win", json={"winner_id": winner}, headers=org), 204)
                    outcome = "win"
                elif roll < 0.85:
                    ok(await c.post(f"/edh/tables/{tb['table_id']}/draw", headers=org), 204)
                    outcome, winner = "draw", None
                else:
                    pending_timeouts.append(tb)
                    continue
                _apply(bank, ids, winner)
                if outcome == "draw":
                    burned += sum(round(RATE * bank_before, 2) for bank_before in _before)
                week[outcome] += 1
            if pending_timeouts:
                r = await c.post(f"/edh/tables/{pending_timeouts[0]['table_id']}/timeout", headers=org)
                assert r.status_code == 400 and "не истёк" in r.json()["detail"]
                CLOCK["now"] += timedelta(minutes=71)
                for tb in pending_timeouts:
                    ok(await c.post(f"/edh/tables/{tb['table_id']}/timeout", headers=org), 204)
                    ids = [s["user_id"] for s in tb["seats"]]
                    _apply(bank, ids, None)
                    burned += sum(round(RATE * b, 2) for b in _before)
                    week["timeout"] += 1
            # платформа посчитала так же, как правила
            after = ok(await c.get(f"/edh/{tid}/tables?round_no={rnd}"))
            for tb in after:
                deltas = [s["delta"] for s in tb["seats"]]
                if tb["outcome"] == "win":
                    assert abs(sum(deltas)) < 0.05, f"победа - нулевая сумма, а вышло {sum(deltas)}"
                else:
                    for s in tb["seats"]:
                        assert abs(s["delta"] + round(RATE * s["bank_before"], 2)) < 0.02
                for s in tb["seats"]:
                    assert abs(s["bank_after"] - bank[s["user_id"]]) < 0.05, (by_id[s["user_id"]]["nick"], s["bank_after"], bank[s["user_id"]])
            week["tables"] += len(tables)
        # повторное открытие тура после завершения - нельзя
        ok(await c.post(f"/edh/{tid}/finish", headers=org))
        assert (await c.post(f"/edh/{tid}/round", headers=org)).status_code == 400
        for p in come:
            attended[p["id"]] = attended.get(p["id"], 0) + 1
        res = ok(await c.get(f"/edh/{tid}/results"))
        week["best"] = f"{res[0]['nickname']} {res[0]['net']:+.1f}"
        async with SessionLocal() as sess:
            report = (await sess.execute(select(OutboxMessage.text).where(OutboxMessage.kind == "tournament_report")
                                         .order_by(OutboxMessage.id.desc()).limit(1))).scalar_one()
        congrats = report.split("📊")[0]
        for r in res:   # поздравляют только тех, кто вечер закончил в плюсе
            if r["net"] <= 0:
                assert f"<b>{r['nickname']}</b>" not in congrats.split("\n", 1)[1], (r, congrats)
        for k in ("win", "draw", "timeout"):
            stats[k] += week[k]
        stats["tables"] += week["tables"]
        weeks.append(week)

    # ---------- итоги сезона ----------
    CLOCK["now"] = datetime(2027, 3, 1, 12, 0, tzinfo=MSK)
    final = ok(await c.get(f"/leagues/{lid}"))
    assert final["status"] == "finished"
    table = final["standings"]
    assert len(table) == len(attended)
    for row in table:
        assert abs(row["bank"] - round(bank[row["user_id"]], 1)) < 0.1, row
        assert row["events"] == attended[row["user_id"]], row
    assert [r["bank"] for r in table] == sorted((r["bank"] for r in table), reverse=True)
    total = sum(bank.values())
    expected_total = 1000 * len(attended) + 150 * sum(attended.values()) - burned
    assert abs(total - expected_total) < 1.0, (total, expected_total)

    # после сезона: новый ивент к нему не привязать
    r = await c.post("/tournaments", json={"club_id": club["id"], "name": "Поздний", "format": "edh", "league_id": lid},
                     headers=org)
    assert r.status_code == 400 and "завершён" in r.json()["detail"]
    # клубный банк сезон не трогает
    async with SessionLocal() as s:
        club_banks = (await s.execute(select(ClubMember.edh_bank).where(ClubMember.club_id == club["id"]))).scalars().all()
        reports = (await s.execute(select(OutboxMessage.text).where(OutboxMessage.kind == "tournament_report")
                                   .order_by(OutboxMessage.id))).scalars().all()
    assert set(club_banks) == {1000.0}
    assert len(reports) == 13 and all("Сезон «Зима 2026»" in t for t in reports)

    _write_report(weeks, table, attended, stats, total, burned, reports[-1])


_before: list[float] = []


def _apply(bank: dict, ids: list[int], winner: int | None) -> None:
    """Правила банка: каждый проигравший теряет 7% своего банка; при победе всё уходит победителю."""
    _before.clear()
    _before.extend(bank[i] for i in ids)
    losses = {i: round(RATE * bank[i], 2) for i in ids if i != winner}
    for i, loss in losses.items():
        bank[i] = round(bank[i] - loss, 2)
    if winner is not None:
        bank[winner] = round(bank[winner] + sum(losses.values()), 2)


def _write_report(weeks, table, attended, stats, total, burned, last_report):
    lines = ["# Сезон EDH «Зима 2026» — прогон симуляции", "",
             f"Игроков: 20 · ивентов: {len(weeks)} · столов: {stats['tables']} "
             f"(победа {stats['win']}, ничья {stats['draw']}, таймер {stats['timeout']}) · "
             f"столы по размеру: {', '.join(f'{k} игр. — {v}' for k, v in sorted(stats['sizes'].items()))}",
             f"Банк всех игроков в конце: {total:,.1f}; сгорело на ничьих и таймерах: {burned:,.1f}".replace(",", " "),
             "", "## По неделям", "", "| Дата | Пришли | Столов | Победы | Ничьи | Таймер | Лучший вечер |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    lines += [f"| {w['date']:%d.%m.%Y} | {w['came']} | {w['tables']} | {w['win']} | {w['draw']} | {w['timeout']} | {w['best']} |"
              for w in weeks]
    lines += ["", "## Итоговая таблица сезона", "", "| Место | Игрок | Банк | Ивентов |", "| --- | --- | --- | --- |"]
    lines += [f"| {i} | {r['nickname']} | {r['bank']:.1f} | {r['events']} |" for i, r in enumerate(table, 1)]
    lines += ["", "## Последний автоотчёт в Telegram", "", "```", last_report, "```"]
    path = os.getenv("SEASON_REPORT", "season-report.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
