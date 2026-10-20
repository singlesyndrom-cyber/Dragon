"""Интеграционные тесты аукциона: сервис (то, что вызывает бот) и API сайта на PostgreSQL."""
import os
from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.skipif(not os.getenv("RUN_INTEGRATION"), reason="нужен PostgreSQL (RUN_INTEGRATION=1)")

if os.getenv("RUN_INTEGRATION"):
    import httpx
    from sqlalchemy import select, update

    from app import auction_service as svc
    from app.auction import AuctionError
    from app.db import Base, SessionLocal, engine
    from app.main import app
    from app.models import GlobalRole, OutboxMessage, User
    from app.security import create_token

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
async def env():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c, \
            SessionLocal() as s:
        yield c, s
    await engine.dispose()


def auth(user):
    return {"Authorization": f"Bearer {create_token(user.id)}"}


async def outbox(_s=None):
    async with SessionLocal() as fresh:   # отдельная сессия: видим то, что закоммитили сервис и API
        return (await fresh.execute(select(OutboxMessage).order_by(OutboxMessage.id))).scalars().all()


async def test_full_auction(env):
    c, s = env
    seller = await svc.get_or_create_tg_user(s, 1001, "seller_tg", "Продавец")
    b1 = await svc.get_or_create_tg_user(s, 1002, None, "Анна")
    b2 = await svc.get_or_create_tg_user(s, 1003, "boris", "Борис")
    assert (await svc.get_or_create_tg_user(s, 1001, "seller_new", "x")).id == seller.id  # идемпотентно
    assert seller.tg_username == "seller_new"

    with pytest.raises(AuctionError, match="Стартовая цена"):
        await svc.create_lot(s, seller, "Sol Ring", "NM", 5, 24, "file1", now=NOW)
    lot = await svc.create_lot(s, seller, "  Sol   Ring ", "NM", 100, 24, "file1", now=NOW)
    assert lot.title == "Sol Ring" and lot.ends_at == NOW + timedelta(hours=24)
    await svc.attach_post(s, lot.id, "@trade", 77)

    t = NOW + timedelta(minutes=1)
    for who, amount, msg in [(seller, 100, "свой лот"), (b1, 50, "100 ₽")]:
        with pytest.raises(AuctionError, match=msg):
            await svc.place_bid(s, lot.id, who, amount, now=t)
    await svc.place_bid(s, lot.id, b1, 100, now=t)
    with pytest.raises(AuctionError, match="лидирует"):
        await svc.place_bid(s, lot.id, b1, 200, now=t)
    with pytest.raises(AuctionError, match="110 ₽"):
        await svc.place_bid(s, lot.id, b2, 105, now=t)
    out = await svc.place_bid(s, lot.id, b2, 110, now=t)
    assert out.previous_leader_id == b1.id and not out.extended
    msgs = await outbox(s)
    assert [(m.kind, m.chat_id) for m in msgs] == [("auction_outbid", "1002")]
    assert "110 ₽" in msgs[0].text and "https://t.me/trade/77" in msgs[0].text

    # антиснайпинг: ставка за 2 минуты до конца продлевает торги до «сейчас + 5 минут»
    late = lot.ends_at - timedelta(minutes=2)
    out = await svc.place_bid(s, lot.id, b1, 200, now=late)
    assert out.extended and out.lot.ends_at == late + timedelta(minutes=5)

    # второй лот без ставок и третий - для отмены
    lot2 = await svc.create_lot(s, seller, "Mana Crypt", "LP", 5000, 1, "file2", now=NOW)
    lot3 = await svc.create_lot(s, seller, "Arcane Signet", "MP", 50, 72, None, now=NOW)

    # API: публичный просмотр
    lots = (await c.get("/auctions/lots")).json()
    assert {x["id"] for x in lots} == {lot.id, lot2.id, lot3.id}
    detail = (await c.get(f"/auctions/lots/{lot.id}")).json()
    assert detail["current_price"] == 200 and detail["leader"] == "Анна" and detail["next_bid"] == 210
    assert [b["amount"] for b in detail["bids_history"]] == [200, 110, 100] and detail["bids_history"][0]["extended"]
    assert detail["photo_url"] == f"/auctions/lots/{lot.id}/photo" and "chat_id" not in detail
    assert (await c.get(f"/auctions/lots/{lot3.id}")).json()["photo_url"] is None

    # снятие: чужой лот нельзя, со ставками - только админ, без ставок - продавец
    assert (await c.post(f"/auctions/lots/{lot3.id}/cancel", headers=auth(b1))).status_code == 400
    assert (await c.post(f"/auctions/lots/{lot.id}/cancel", headers=auth(seller))).status_code == 400
    assert (await c.post(f"/auctions/lots/{lot3.id}/cancel", headers=auth(seller))).status_code == 204

    # завершение по времени
    assert await svc.finish_due(s, now=NOW + timedelta(minutes=30)) == []
    finished = await svc.finish_due(s, now=NOW + timedelta(days=2))
    assert set(finished) == {lot.id, lot2.id}
    with pytest.raises(AuctionError, match="завершены"):
        await svc.place_bid(s, lot.id, b2, 1000, now=NOW + timedelta(days=2))
    await s.refresh(lot)
    await s.refresh(lot2)
    assert lot.status.value == "sold" and lot2.status.value == "unsold"

    msgs = [(m.kind, m.chat_id) for m in await outbox(s)]
    assert ("auction_won", "1002") in msgs and ("auction_sold", "1001") in msgs and ("auction_unsold", "1001") in msgs
    won = next(m for m in await outbox(s) if m.kind == "auction_won")
    assert "@seller_new" in won.text and won.buttons[0][0]["callback_data"].startswith("deal:")
    sold = next(m for m in await outbox(s) if m.kind == "auction_sold")
    assert 'tg://user?id=1002' in sold.text   # у покупателя нет username - ссылка по id

    deals = (await c.get("/auctions/deals/mine", headers=auth(b1))).json()
    assert len(deals) == 1 and deals[0]["role"] == "buyer" and deals[0]["price"] == 200
    deal_id = deals[0]["id"]

    # оценка до подтверждения невозможна; посторонний не участвует
    assert (await c.post(f"/auctions/deals/{deal_id}/rate", json={"score": 5}, headers=auth(b1))).status_code == 400
    assert (await c.post(f"/auctions/deals/{deal_id}/confirm", json={"ok": True}, headers=auth(b2))).status_code == 400
    r = await c.post(f"/auctions/deals/{deal_id}/confirm", json={"ok": True}, headers=auth(b1))
    assert r.json() == {"status": "pending"}
    assert (await c.post(f"/auctions/deals/{deal_id}/confirm", json={"ok": True}, headers=auth(b1))).status_code == 400
    deal = await svc.confirm_deal(s, deal_id, seller, True)            # продавец подтверждает через бота
    assert deal.status == "completed"
    rate_msgs = [m for m in await outbox(s) if m.kind == "deal_rate"]
    assert {m.chat_id for m in rate_msgs} == {"1001", "1002"} and len(rate_msgs[0].buttons[0]) == 5

    assert (await c.post(f"/auctions/deals/{deal_id}/rate", json={"score": 4, "comment": "Всё ок"},
                         headers=auth(b1))).status_code == 201
    assert (await c.post(f"/auctions/deals/{deal_id}/rate", json={"score": 5}, headers=auth(b1))).status_code == 400
    await svc.rate_deal(s, deal_id, seller, 5)                         # продавец оценивает покупателя
    rs = (await c.get(f"/auctions/users/{seller.id}/rating")).json()
    assert rs["seller_avg"] == 4.0 and rs["seller_count"] == 1 and rs["deals_completed"] == 1
    rb = (await c.get(f"/auctions/users/{b1.id}/rating")).json()
    assert rb["buyer_avg"] == 5.0 and rb["seller_count"] == 0
    # рейтинг продавца виден в карточке лота
    assert (await c.get(f"/auctions/lots/{lot.id}")).json()["seller_avg"] == 4.0


async def test_disputed_complaint_ban(env):
    c, s = env
    seller = await svc.get_or_create_tg_user(s, 2001, None, "Продавец")
    buyer = await svc.get_or_create_tg_user(s, 2002, None, "Покупатель")
    admin = await svc.get_or_create_tg_user(s, 2003, None, "Админ")
    await s.execute(update(User).where(User.id == admin.id).values(role=GlobalRole.admin))
    await s.commit()

    lot = await svc.create_lot(s, seller, "Black Lotus", "HP", 1000, 1, None, now=NOW)
    await svc.place_bid(s, lot.id, buyer, 1000, now=NOW)
    await svc.finish_due(s, now=NOW + timedelta(hours=2))
    deal_id = (await c.get("/auctions/deals/mine", headers=auth(buyer))).json()[0]["id"]
    await svc.confirm_deal(s, deal_id, seller, True)
    assert (await svc.confirm_deal(s, deal_id, buyer, False)).status == "disputed"
    disp = (await c.get("/admin/deals/disputed", headers=auth(admin))).json()
    assert [d["id"] for d in disp] == [deal_id] and disp[0]["seller_nick"] == "Продавец"
    assert (await c.post(f"/auctions/deals/{deal_id}/rate", json={"score": 1}, headers=auth(buyer))).status_code == 400

    # жалоба: только между участниками сделки
    assert (await c.post("/auctions/complaints", json={"against_user_id": seller.id, "deal_id": deal_id,
                                                       "text": "Не отправил карту"}, headers=auth(admin))).status_code == 400
    r = await c.post("/auctions/complaints", json={"against_user_id": seller.id, "deal_id": deal_id,
                                                   "text": "Не отправил карту"}, headers=auth(buyer))
    assert r.status_code == 201
    assert (await c.get("/admin/complaints", headers=auth(buyer))).status_code == 403
    comps = (await c.get("/admin/complaints", headers=auth(admin))).json()
    assert len(comps) == 1 and comps[0]["against_user_id"] == seller.id
    assert comps[0]["against_nick"] == "Продавец" and comps[0]["from_nick"] == "Покупатель"

    # блокировка: продавец больше не может выставлять лоты и ставить
    assert (await c.post(f"/admin/users/{seller.id}/ban", json={"banned": True}, headers=auth(admin))).status_code == 204
    await s.refresh(seller)
    assert seller.is_banned
    with pytest.raises(AuctionError, match="заблокирован"):
        await svc.create_lot(s, seller, "Mox Pearl", "NM", 100, 1, None, now=NOW)
    assert (await c.get("/auth/me", headers=auth(seller))).status_code == 401
    assert (await c.post(f"/admin/complaints/{comps[0]['id']}/resolve", headers=auth(admin))).status_code == 204
    assert (await c.get("/admin/complaints", headers=auth(admin))).json() == []


async def test_lot_limit(env):
    c, s = env
    seller = await svc.get_or_create_tg_user(s, 3001, None, "Оптовик")
    for i in range(10):
        await svc.create_lot(s, seller, f"Карта {i}", "NM", 100, 24, None, now=NOW)
    with pytest.raises(AuctionError, match="не больше 10"):
        await svc.create_lot(s, seller, "Лишняя", "NM", 100, 24, None, now=NOW)
