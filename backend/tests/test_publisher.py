"""Кабинет издателя: назначение администратором, доступ только к своим играм, обзор, клубы, итоги турниров,
деклисты только игроков с согласием, выгрузка CSV. RUN_INTEGRATION=1."""
import os

import pytest

pytestmark = pytest.mark.skipif(not os.getenv("RUN_INTEGRATION"), reason="нужен PostgreSQL (RUN_INTEGRATION=1)")

if os.getenv("RUN_INTEGRATION"):
    import httpx
    from sqlalchemy import update

    from app.db import Base, SessionLocal, engine
    from app.main import app
    from app.models import GlobalRole, User
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
    r = await c.post("/auth/register", json={"email": f"p{n}@example.com", "password": "password1", "nickname": f"Игрок{n}"})
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    return h, (await c.get("/auth/me", headers=h)).json()


async def finished_berserk(c, org, cid, players, name):
    tid = (await c.post("/tournaments", json={"club_id": cid, "name": name, "game": "berserk", "format": "swiss",
                                              "rounds": 1}, headers=org)).json()["id"]
    for h, _ in players:
        deck = (await c.post("/decks", json={"name": "Колода", "game": "berserk", "text": "3 Огненный дракон\n2 Лучник"},
                             headers=h)).json()["id"]
        assert (await c.post(f"/tournaments/{tid}/register?deck_id={deck}", headers=h)).status_code == 204
    assert (await c.post(f"/tournaments/{tid}/start", headers=org)).status_code == 200
    for m in (await c.get(f"/tournaments/{tid}/round/1")).json():
        if m.get("p2_id"):
            await c.post(f"/tournaments/matches/{m['match_id']}/result", json={"result": "p1"}, headers=org)
    assert (await c.post(f"/tournaments/{tid}/finish", headers=org)).status_code == 200
    return tid


async def test_publisher_cabinet(client):
    c = client
    admin, adm = await reg(c, 0)
    async with SessionLocal() as s:
        await s.execute(update(User).where(User.id == adm["id"]).values(role=GlobalRole.admin))
        await s.commit()
    org, _ = await reg(c, 1)
    await make_creator(c, org)
    cid = (await c.post("/clubs", json={"name": "Дракон", "city": "Москва"}, headers=org)).json()["id"]
    a, b = await reg(c, 2), await reg(c, 3)
    await finished_berserk(c, org, cid, [a, b], "Берсерк-кубок")

    pub_h, pub = await reg(c, 9)
    assert (await c.get("/publisher/me", headers=pub_h)).status_code == 403
    assert (await c.put("/admin/publishers", json={"player_no": pub["player_no"], "name": "Издательство", "games": ["berserk"]},
                        headers=org)).status_code == 403
    r = await c.put("/admin/publishers", json={"player_no": pub["player_no"], "name": "Издательство", "games": ["berserk"]},
                    headers=admin)
    assert r.status_code == 200 and r.json()["games"] == ["berserk"]
    assert (await c.get("/auth/me", headers=pub_h)).json()["is_publisher"] is True
    assert (await c.get("/publisher/me", headers=pub_h)).json()["games"] == [{"code": "berserk", "title": "Берсерк"}]
    assert (await c.get("/publisher/mtg/overview", headers=pub_h)).status_code == 403     # чужая игра
    assert (await c.get("/publisher/berserk/overview", headers=org)).status_code == 403   # не издатель

    ov = (await c.get("/publisher/berserk/overview", headers=pub_h)).json()
    assert (ov["tournaments"], ov["participations"], ov["players"], ov["clubs"]) == (1, 2, 2, 1)
    assert ov["formats"] == {"swiss": 1} and len(ov["by_month"]) == 1
    clubs = (await c.get("/publisher/berserk/clubs", headers=pub_h)).json()
    assert [(x["name"], x["city"], x["tournaments"], x["players"]) for x in clubs] == [("Дракон", "Москва", 1, 2)]
    ts = (await c.get("/publisher/berserk/tournaments", headers=pub_h)).json()
    assert ts[0]["name"] == "Берсерк-кубок" and ts[0]["participants"] == 2 and ts[0]["winner"] in ("Игрок2", "Игрок3")

    # деклисты: без согласия - пусто; дал согласие - видны его колода, ник и место
    assert (await c.get("/publisher/berserk/decklists", headers=pub_h)).json()["items"] == []
    r = await c.put("/me/publisher-consent", json={"enabled": True}, headers=a[0])
    assert r.json()["publisher_consent"] is True and r.json()["publisher_consent_at"]
    assert (await c.get("/auth/me", headers=a[0])).json()["publisher_consent"] is True
    dl = (await c.get("/publisher/berserk/decklists", headers=pub_h)).json()
    assert [d["player"] for d in dl["items"]] == ["Игрок2"] and dl["consented_players"] == 1
    assert {x["name"] for x in dl["items"][0]["cards"]} == {"Огненный дракон", "Лучник"} and dl["items"][0]["place"] in (1, 2)

    # выгрузка CSV для Excel
    csv = await c.get("/publisher/berserk/export/decklists.csv", headers=pub_h)
    assert csv.status_code == 200 and csv.text.startswith("﻿Дата;Клуб;Турнир")
    assert "Игрок2" in csv.text and "Игрок3" not in csv.text
    assert "Берсерк-кубок" in (await c.get("/publisher/berserk/export/tournaments.csv", headers=pub_h)).text
    assert (await c.get("/publisher/berserk/export/nope.csv", headers=pub_h)).status_code == 404
    # мета без имён
    meta = (await c.get("/publisher/berserk/meta", headers=pub_h)).json()
    assert meta["tournament_decks"] == 2 and "Игрок" not in str(meta)
    bk = meta["berserk"]["tournaments"]          # карт в базе нет - стихий нет: «Нейтральные»
    assert bk["decks"] == 2 and bk["combos"][0]["key"] == "Нейтральные" and bk["combos"][0]["games"] == 2
    assert bk["archetypes"][0]["key"] == "Колода" and bk["archetypes"][0]["wins"] == 1
    pub_meta = (await c.get("/meta/berserk")).json()            # публичная страница меты: «Берсерк» отдельно
    assert pub_meta["entries"] == 2 and pub_meta["tournaments"]["decks"] == 2
    assert (await c.get("/meta/commanders", params={"game": "mtg"})).json()["entries"] == 0

    # отзыв согласия и снятие роли
    await c.put("/me/publisher-consent", json={"enabled": False}, headers=a[0])
    assert (await c.get("/publisher/berserk/decklists", headers=pub_h)).json()["items"] == []
    pid = (await c.get("/admin/publishers", headers=admin)).json()[0]["id"]
    assert (await c.delete(f"/admin/publishers/{pid}", headers=admin)).status_code == 204
    assert (await c.get("/publisher/berserk/overview", headers=pub_h)).status_code == 403
    assert (await c.get("/publisher/mtg/overview", headers=admin)).status_code == 200      # администратор видит всё
