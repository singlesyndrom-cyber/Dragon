"""Сезоны лиг, гости, выбывание, исправление прошлых туров, настройки турнира. Настоящий PostgreSQL."""
import os
from datetime import date

import pytest

from app.leagues import season_end

pytestmark_int = pytest.mark.skipif(not os.getenv("RUN_INTEGRATION"), reason="нужен PostgreSQL (RUN_INTEGRATION=1)")

if os.getenv("RUN_INTEGRATION"):
    import httpx

    from app.db import Base, engine
    from app.main import app
    from tests.helpers import make_creator


def test_season_end_dates():
    assert season_end(date(2026, 10, 1), 1) == date(2026, 10, 31)
    assert season_end(date(2026, 10, 20), 2) == date(2026, 12, 19)
    assert season_end(date(2026, 11, 30), 3) == date(2027, 2, 27)
    assert season_end(date(2027, 1, 31), 1) == date(2027, 2, 27)


@pytest.fixture
async def client():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await engine.dispose()


async def reg(c, n):
    r = await c.post("/auth/register", json={"email": f"l{n}@test.io", "password": "password1", "nickname": f"Игрок{n}"})
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    return h, (await c.get("/auth/me", headers=h)).json()["id"]


async def setup(c):
    org, org_id = await reg(c, 0)
    await make_creator(c, org)
    club = (await c.post("/clubs", json={"name": "Сезонный клуб"}, headers=org)).json()
    return org, org_id, club


@pytestmark_int
async def test_edh_season_bank_resets_and_tracks(client):
    org, org_id, club = await setup(client)
    # сезон EDH на 2 месяца
    r = await client.post("/leagues", json={"club_id": club["id"], "name": "Осень", "kind": "edh", "months": 2}, headers=org)
    assert r.status_code == 201, r.text
    season = r.json()
    assert season["status"] == "active" and season["months"] == 2
    # пересекающийся сезон того же вида запрещён, другого вида - можно
    assert (await client.post("/leagues", json={"club_id": club["id"], "name": "Дубль", "kind": "edh", "months": 1},
                              headers=org)).status_code == 409
    assert (await client.post("/leagues", json={"club_id": club["id"], "name": "Берсерк", "kind": "berserk", "months": 3},
                              headers=org)).status_code == 201
    other, _ = await reg(client, 99)
    assert (await client.post("/leagues", json={"club_id": club["id"], "name": "Чужой", "kind": "edh", "months": 1},
                              headers=other)).status_code == 403

    # швейцарка к EDH-сезону не привязывается
    bad = await client.post("/tournaments", json={"club_id": club["id"], "name": "Не та", "format": "swiss",
                                                   "league_id": season["id"]}, headers=org)
    assert bad.status_code == 400

    # без сезона клубный банк игрока уйдёт выше 1000; в сезоне он стартует с 1000 заново
    players = [await reg(client, i) for i in range(1, 4)]
    async def edh_event(name, league_id=None):
        body = {"club_id": club["id"], "name": name, "format": "edh"}
        if league_id:
            body["league_id"] = league_id
        tid = (await client.post("/tournaments", json=body, headers=org)).json()["id"]
        for h, uid in players:
            assert (await client.post(f"/tournaments/{tid}/register", headers=h)).status_code == 204
            await client.put(f"/edh/{tid}/players/{uid}", json={"checked_in": True}, headers=org)
        assert (await client.post(f"/edh/{tid}/round", headers=org)).status_code == 200
        table = (await client.get(f"/edh/{tid}/tables")).json()[0]
        await client.post(f"/edh/tables/{table['table_id']}/win", json={"winner_id": players[0][1]}, headers=org)
        assert (await client.post(f"/edh/{tid}/finish", headers=org)).status_code == 200
        return tid

    await edh_event("Без сезона")
    board = {m["user_id"]: m for m in (await client.get(f"/clubs/{club['id']}/leaderboard")).json()}
    assert board[players[0][1]]["edh_bank"] == 1311.0          # 1150 + 7% от двух соперников
    tid = await edh_event("Сезонный вечер", season["id"])
    lg = (await client.get(f"/leagues/{season['id']}")).json()
    st = {r["user_id"]: r for r in lg["standings"]}
    assert st[players[0][1]]["bank"] == 1311.0 and st[players[0][1]]["events"] == 1   # сезон: снова от 1000
    assert st[players[1][1]]["bank"] == 1069.5 and lg["standings"][0]["user_id"] == players[0][1]
    assert [t["id"] for t in lg["tournaments"]] == [tid]
    # клубный банк сезоном не тронут
    board = {m["user_id"]: m for m in (await client.get(f"/clubs/{club['id']}/leaderboard")).json()}
    assert board[players[0][1]]["edh_bank"] == 1311.0
    # результаты ивента берут банк сезона
    res = {r["user_id"]: r for r in (await client.get(f"/edh/{tid}/results")).json()}
    assert res[players[0][1]]["bank"] == 1311.0

    # закрытый сезон: новые ивенты не привязать и туры не начать
    t2 = (await client.post("/tournaments", json={"club_id": club["id"], "name": "Поздно", "format": "edh",
                                                   "league_id": season["id"]}, headers=org)).json()["id"]
    assert (await client.post(f"/leagues/{season['id']}/close", headers=org)).status_code == 204
    assert (await client.get(f"/leagues/{season['id']}")).json()["status"] == "finished"
    for h, uid in players:
        await client.post(f"/tournaments/{t2}/register", headers=h)
        await client.put(f"/edh/{t2}/players/{uid}", json={"checked_in": True}, headers=org)
    assert (await client.post(f"/edh/{t2}/round", headers=org)).status_code == 400
    assert (await client.post("/tournaments", json={"club_id": club["id"], "name": "Ещё", "format": "edh",
                                                     "league_id": season["id"]}, headers=org)).status_code == 400
    listed = (await client.get(f"/leagues?club_id={club['id']}&status=active")).json()
    assert [x["name"] for x in listed] == ["Берсерк"]


@pytestmark_int
async def test_berserk_season_guests_drop_and_corrections(client):
    org, org_id, club = await setup(client)
    season = (await client.post("/leagues", json={"club_id": club["id"], "name": "Зима", "kind": "berserk", "months": 1},
                                headers=org)).json()
    assert (await client.post("/tournaments", json={"club_id": club["id"], "name": "MTG", "game": "mtg", "format": "swiss",
                                                     "league_id": season["id"]}, headers=org)).status_code == 400
    r = await client.post("/tournaments", json={
        "club_id": club["id"], "name": "Берсерк #1", "game": "berserk", "format": "swiss", "rounds": 2,
        "league_id": season["id"], "description": "Приходите к 18:00", "deck_policy": "none",
        "self_registration": False, "max_players": 5}, headers=org)
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    card = (await client.get(f"/tournaments/{tid}")).json()
    assert card["league"]["name"] == "Зима" and card["description"] == "Приходите к 18:00"
    assert card["deck_policy"] == "none" and card["self_registration"] is False and card["max_players"] == 5

    # саморегистрация выключена: записывает только организатор
    p1, p1_id = await reg(client, 1)
    assert (await client.post(f"/tournaments/{tid}/register", headers=p1)).status_code == 403
    assert (await client.post(f"/tournaments/{tid}/players", json={"user_id": p1_id}, headers=org)).status_code == 201
    # гости по имени; тот же ник в клубе - тот же гость
    guests = []
    for name in ("Гость Аня", "Гость Боря", "Гость Вася", "Гость Галя"):
        g = (await client.post(f"/tournaments/{tid}/players", json={"nickname": name}, headers=org)).json()
        assert g["guest"] is True
        guests.append(g["user_id"])
    assert (await client.post(f"/tournaments/{tid}/players", json={"nickname": "гость аня"}, headers=org)).status_code in (400, 409)
    assert (await client.post(f"/tournaments/{tid}/players", json={"nickname": "Лишний"}, headers=org)).status_code == 400  # лимит 5
    hints = (await client.get(f"/clubs/{club['id']}/players?q=гость", headers=org)).json()
    assert {h["nickname"] for h in hints} >= {"Гость Аня", "Гость Боря"} and all(h["guest"] for h in hints)
    assert (await client.delete(f"/tournaments/{tid}/players/{guests[3]}", headers=org)).status_code == 204
    assert (await client.patch(f"/tournaments/{tid}", json={"rounds": 3, "name": "Берсерк #1 (3 тура)"},
                               headers=org)).status_code == 204

    # деклисты на этот турнир не принимаются
    deck = (await client.post("/decks", json={"name": "Колода", "game": "berserk", "text": "1 Карта"}, headers=p1)).json()
    assert (await client.put(f"/decks/{deck['id']}/attach/{tid}", headers=p1)).status_code == 400

    assert (await client.post(f"/tournaments/{tid}/start", headers=org)).status_code == 200
    assert (await client.patch(f"/tournaments/{tid}", json={"rounds": 2}, headers=org)).status_code == 400
    r1 = (await client.get(f"/tournaments/{tid}/round/1")).json()
    for m in r1:
        if m["p2_id"]:
            await client.post(f"/tournaments/matches/{m['match_id']}/result", json={"result": "p1"}, headers=org)
    assert (await client.post(f"/tournaments/{tid}/next-round", headers=org)).status_code == 200

    # исправление результата прошлого тура
    first = next(m for m in r1 if m["p2_id"])
    assert (await client.post(f"/tournaments/matches/{first['match_id']}/result", json={"result": "p2"},
                              headers=org)).status_code == 204
    assert next(m for m in (await client.get(f"/tournaments/{tid}/round/1")).json()
                if m["match_id"] == first["match_id"])["result"] == "p2"

    # выбывание: игрок остаётся в таблице, но в 3-м туре пар не получает
    r2 = (await client.get(f"/tournaments/{tid}/round/2")).json()
    for m in r2:
        if m["p2_id"]:
            await client.post(f"/tournaments/matches/{m['match_id']}/result", json={"result": "draw"}, headers=org)
    dropped = guests[0]
    assert (await client.post(f"/tournaments/{tid}/players/{dropped}/drop", json={"dropped": True},
                              headers=org)).status_code == 204
    assert (await client.post(f"/tournaments/{tid}/next-round", headers=org)).status_code == 200
    r3 = (await client.get(f"/tournaments/{tid}/round/3")).json()
    assert dropped not in {x for m in r3 for x in (m["p1_id"], m["p2_id"])}
    standings = (await client.get(f"/tournaments/{tid}/standings")).json()
    assert len(standings) == 4 and next(s for s in standings if s["user_id"] == dropped)["dropped"] is True
    for m in r3:
        if m["p2_id"]:
            await client.post(f"/tournaments/matches/{m['match_id']}/result", json={"result": "p1"}, headers=org)
    assert (await client.post(f"/tournaments/{tid}/finish", headers=org)).status_code == 200

    # таблица сезона = сумма очков турниров сезона
    table = (await client.get(f"/leagues/{season['id']}")).json()["standings"]
    final = {s["user_id"]: s["points"] for s in standings}
    final = {s["user_id"]: s["points"] for s in (await client.get(f"/tournaments/{tid}/standings")).json()}
    assert {r["user_id"]: r["points"] for r in table} == final and all(r["events"] == 1 for r in table)

    # гость зарегистрировался - организатор переносит его историю на аккаунт
    _, real_id = await reg(client, 7)
    merged = await client.post(f"/clubs/{club['id']}/guests/{guests[1]}/merge", json={"email": "l7@test.io"}, headers=org)
    assert merged.status_code == 200, merged.text
    table2 = {r["user_id"]: r["points"] for r in (await client.get(f"/leagues/{season['id']}")).json()["standings"]}
    assert guests[1] not in table2 and table2[real_id] == final[guests[1]]
    assert (await client.post(f"/clubs/{club['id']}/guests/{guests[1]}/merge", json={"email": "l7@test.io"},
                              headers=org)).status_code == 404


@pytestmark_int
async def test_required_decklists_block_start_unless_forced(client):
    org, _, club = await setup(client)
    tid = (await client.post("/tournaments", json={"club_id": club["id"], "name": "Строгий", "deck_policy": "required"},
                             headers=org)).json()["id"]
    for i in (1, 2):
        h, _ = await reg(client, i)
        await client.post(f"/tournaments/{tid}/register", headers=h)
    r = await client.post(f"/tournaments/{tid}/start", headers=org)
    assert r.status_code == 409 and "Игрок1" in r.json()["detail"] and "Игрок2" in r.json()["detail"]
    assert (await client.post(f"/tournaments/{tid}/start?force=true", headers=org)).status_code == 200
