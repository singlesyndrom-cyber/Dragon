"""Кнопки бота и напоминания: запись из анонса, лист ожидания, отмена, напоминания о турнире и брони. RUN_INTEGRATION=1."""
import os
from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.skipif(not os.getenv("RUN_INTEGRATION"), reason="нужен PostgreSQL (RUN_INTEGRATION=1)")

if os.getenv("RUN_INTEGRATION"):
    from zoneinfo import ZoneInfo

    import httpx
    from sqlalchemy import select, update

    from app import tg_actions
    from app.config import settings
    from app.db import Base, SessionLocal, engine
    from app.main import app
    from app.models import AuthAccount, OutboxMessage, Provider, TableBooking, Tournament, TournamentPlayer, User
    from tests.helpers import make_creator


@pytest.fixture
async def client():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await engine.dispose()


async def club_and_event(c, **extra):
    r = await c.post("/auth/register", json={"email": "o@example.com", "password": "password1", "nickname": "Орг"})
    org = {"Authorization": f"Bearer {r.json()['access_token']}"}
    await make_creator(c, org)
    cid = (await c.post("/clubs", json={"name": "Дракон"}, headers=org)).json()["id"]
    when = (datetime.now(timezone.utc) + timedelta(hours=20)).replace(tzinfo=None, microsecond=0).isoformat()
    tid = (await c.post("/tournaments", json={"club_id": cid, "name": "Командир", "format": "edh", "starts_at": when,
                                              **extra}, headers=org)).json()["id"]
    return org, cid, tid


async def linked(*players):
    """Игроки, у которых Telegram привязан к аккаунту сайта (как после привязки в кабинете)."""
    from app.auction_service import get_or_create_tg_user
    async with SessionLocal() as s:
        for tg_id, username, name in players:
            await get_or_create_tg_user(s, tg_id, username, name)


async def outbox(kind):
    async with SessionLocal() as s:
        return (await s.execute(select(OutboxMessage).where(OutboxMessage.kind == kind)
                                .order_by(OutboxMessage.id))).scalars().all()


async def test_register_from_announcement_and_waitlist(client):
    org, cid, tid = await club_and_event(client, max_players=2)
    await linked((444, "vova", None), (111, "masha", "Маша"), (222, None, "Петя"), (333, "x", None))
    async with SessionLocal() as s:
        assert "Записано 1 из 2" in await tg_actions.register(s, 444, "vova", None, tid)
        text = await tg_actions.register(s, 111, "masha", "Маша", tid)
    assert text.startswith("✅ masha (№") and "вы записаны на «Командир»" in text and "Записано 2 из 2" in text
    async with SessionLocal() as s:
        # повторное нажатие
        assert (await tg_actions.register(s, 111, "masha", "Маша", tid)).startswith("Вы уже записаны на «Командир»")
        # второй игрок - мест нет, встаёт в очередь
        assert "листе ожидания (1-й)" in await tg_actions.register(s, 222, None, "Петя", tid)
        user = (await s.execute(select(User).join(AuthAccount, AuthAccount.user_id == User.id).where(
            AuthAccount.provider == Provider.telegram, AuthAccount.external_id == "111"))).scalar_one()
    assert user.player_no is not None                                   # аккаунт платформы создан по Telegram
    card = (await client.get(f"/tournaments/{tid}")).json()
    assert [p["nickname"] for p in card["participants"]] == ["masha", "vova"] and card["waitlist"][0]["nickname"] == "Петя"
    assert [m["user_id"] for m in (await client.get(f"/clubs/{cid}/members", headers=org)).json() if m["nickname"] == "masha"]

    # Маша отменяет запись кнопкой - Петя записан и получает сообщение
    async with SessionLocal() as s:
        assert await tg_actions.unregister(s, 111, "masha", "Маша", tid) == "Запись на «Командир» отменена."
        assert await tg_actions.unregister(s, 111, "masha", "Маша", tid) == "Вы не были записаны на этот турнир."
    card = (await client.get(f"/tournaments/{tid}")).json()
    assert [p["nickname"] for p in card["participants"]] == ["vova", "Петя"]
    assert (await outbox("waitlist_promoted"))[0].chat_id == "222"

    # турнир без самозаписи - кнопка честно отказывает
    await client.patch(f"/tournaments/{tid}", json={"self_registration": False}, headers=org)
    async with SessionLocal() as s:
        assert "записывает организатор" in await tg_actions.register(s, 333, "x", None, tid)


async def test_tournament_reminders(client):
    org, cid, tid = await club_and_event(client)
    await linked((111, "masha", "Маша"))
    async with SessionLocal() as s:
        await tg_actions.register(s, 111, "masha", "Маша", tid)
    r = await client.post("/auth/register", json={"email": "site@example.com", "password": "password1", "nickname": "Сайт"})
    await client.post(f"/tournaments/{tid}/register", headers={"Authorization": f"Bearer {r.json()['access_token']}"})
    async with SessionLocal() as s:
        assert await tg_actions.tournament_reminders(s) == 1               # у второго нет Telegram
        assert await tg_actions.tournament_reminders(s) == 0               # один раз
        flags = set((await s.execute(select(TournamentPlayer.reminded))).scalars())
    assert flags == {True}
    msg = (await outbox("tournament_reminder"))[0]
    assert msg.chat_id == "111" and "«Командир» в клубе «Дракон»" in msg.text
    assert msg.buttons == [[{"text": "Отменить запись", "callback_data": f"unreg:{tid}"}]]
    # за двое суток напоминания ещё нет
    async with SessionLocal() as s:
        await s.execute(update(Tournament).values(starts_at=datetime.now(timezone.utc) + timedelta(hours=48)))
        await s.execute(update(TournamentPlayer).values(reminded=False))
        await s.commit()
        assert await tg_actions.tournament_reminders(s) == 0


async def test_booking_reminder_and_cancel_button(client):
    org, cid, _ = await club_and_event(client)
    table = (await client.post(f"/clubs/{cid}/tables", json={"name": "Стол 1"}, headers=org)).json()["id"]
    await client.put(f"/clubs/{cid}/hours", json={"days": {str(d): ["00:00", "24:00"] for d in range(7)}}, headers=org)
    async with SessionLocal() as s:
        from app.auction_service import get_or_create_tg_user
        u = await get_or_create_tg_user(s, 111, "masha", "Маша")
        uid = u.id
    tz = ZoneInfo(settings.app_timezone)
    start = (datetime.now(tz) + timedelta(minutes=90)).replace(second=0, microsecond=0)
    start = start.replace(minute=0 if start.minute < 30 else 30)
    if start <= datetime.now(tz):
        start += timedelta(minutes=30)
    async with SessionLocal() as s:   # бронь напрямую: тест про напоминание, не про форму
        s.add(TableBooking(club_id=cid, table_id=table, user_id=uid, starts_at=start, ends_at=start + timedelta(hours=2)))
        await s.commit()
        assert await tg_actions.booking_reminders(s) == 1
        assert await tg_actions.booking_reminders(s) == 0
        bid = (await s.execute(select(TableBooking.id))).scalar_one()
    msg = (await outbox("booking_reminder"))[0]
    assert msg.chat_id == "111" and "стол «Стол 1»" in msg.text and msg.buttons[0][0]["callback_data"] == f"bcancel:{bid}"
    async with SessionLocal() as s:
        assert await tg_actions.cancel_booking(s, 999, "chuzhoy", None, bid) == \
            "Отменить бронь может тот, кто бронировал, или организатор клуба"
        assert (await tg_actions.cancel_booking(s, 111, "masha", "Маша", bid)).startswith("Бронь на ")
        assert (await s.execute(select(TableBooking.status))).scalar_one() == "cancelled"


async def test_unlinked_button_asks_to_link_instead_of_new_account(client):
    """Кнопка у непривязанного Telegram не создаёт дубль: ссылка - войти и привязать или создать аккаунт."""
    org, cid, tid = await club_and_event(client)
    r = await client.post("/auth/register", json={"email": "p@example.com", "password": "password1", "nickname": "Маша"})
    site = {"Authorization": f"Bearer {r.json()['access_token']}"}
    me = (await client.get("/auth/me", headers=site)).json()
    async with SessionLocal() as s:
        need = await tg_actions.register(s, 111, "masha_tg", "Маша", tid)
        users_before = len((await s.execute(select(User.id))).all())
    assert isinstance(need, tg_actions.NeedLink) and "не связан с номером игрока" in need.text
    info = (await client.get(f"/auth/link-code/{need.code}")).json()
    assert info["provider_name"] == "Telegram" and info["who"] == "@masha_tg" and info["tournament"]["name"] == "Командир"
    assert (await client.post(f"/auth/link-code/{need.code}/claim")).status_code == 401
    r = (await client.post(f"/auth/link-code/{need.code}/claim", headers=site)).json()
    assert r["player_no"] == me["player_no"] and "вы записаны на «Командир»" in r["message"]
    assert [p["nickname"] for p in (await client.get(f"/tournaments/{tid}")).json()["participants"]] == ["Маша"]
    assert (await client.post(f"/auth/link-code/{need.code}/claim", headers=site)).status_code == 410   # одноразовая
    async with SessionLocal() as s:
        assert len((await s.execute(select(User.id))).all()) == users_before                # дубля нет
        # дальше кнопка работает сразу, по тому же номеру
        assert (await tg_actions.register(s, 111, "masha_tg", "Маша", tid)).startswith("Вы уже записаны")
        assert await tg_actions.unregister(s, 111, "masha_tg", "Маша", tid) == "Запись на «Командир» отменена."
        # второй Telegram к тому же аккаунту не привязать
        other = await tg_actions.register(s, 999, "second", None, tid)
    assert (await client.post(f"/auth/link-code/{other.code}/claim", headers=site)).status_code == 409

    # аккаунта на сайте нет: создаётся по ссылке, сразу вход и запись
    async with SessionLocal() as s:
        need = await tg_actions.register(s, 222, None, "Петя", tid)
    r = (await client.post(f"/auth/link-code/{need.code}/new")).json()
    assert r["player_no"] and r["access_token"] and "Петя (№" in r["message"]
    assert (await client.get("/auth/me", headers={"Authorization": f"Bearer {r['access_token']}"})).json()["nickname"] == "Петя"
    assert (await client.get("/auth/link-code/nope")).status_code == 404
