from datetime import datetime, timedelta, timezone

import pytest

from app.auction import (AuctionError, bid_step, check_bid, check_lot, deal_status, extend_end, min_next_bid,
                         money, parse_price)
from app.auction_texts import deal_buttons, lot_caption, post_url, rate_buttons, user_link

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)


def bid(**kw):
    base = dict(amount=100, start_price=100, current_price=None, seller_id=1, leader_id=None, bidder_id=2,
                ends_at=NOW + timedelta(hours=1), now=NOW, active=True)
    base.update(kw)
    check_bid(**base)


def test_steps_and_min_bid():
    assert bid_step(100) == 10 and bid_step(1000) == 50 and bid_step(1010) == 51
    assert min_next_bid(100, None) == 100 and min_next_bid(100, 300) == 315


def test_bid_rules():
    bid()
    for kw, msg in [(dict(bidder_id=1), "свой лот"), (dict(leader_id=2, current_price=100), "лидирует"),
                    (dict(amount=99), "100 ₽"), (dict(amount=105, current_price=100), "110 ₽"),
                    (dict(active=False), "завершены"), (dict(ends_at=NOW), "завершены"),
                    (dict(amount=None), "числом"), (dict(amount=10**9), "максимум")]:
        with pytest.raises(AuctionError, match=msg):
            bid(**kw)


def test_anti_sniping():
    assert extend_end(NOW + timedelta(minutes=30), NOW) == NOW + timedelta(minutes=30)
    assert extend_end(NOW + timedelta(minutes=2), NOW) == NOW + timedelta(minutes=5)
    assert extend_end(NOW + timedelta(seconds=299), NOW) == NOW + timedelta(minutes=5)
    assert extend_end(NOW + timedelta(minutes=5), NOW) == NOW + timedelta(minutes=5)


def test_check_lot():
    assert check_lot("  Sol   Ring ", "NM", 100, 24) == "Sol Ring"
    for args in [("x", "NM", 100, 24), ("Sol", "XX", 100, 24), ("Sol", "NM", 5, 24),
                 ("Sol", "NM", None, 24), ("Sol", "NM", 100, 5)]:
        with pytest.raises(AuctionError):
            check_lot(*args)


def test_parse_price():
    for s, v in [("1500", 1500), ("1 500 ₽", 1500), ("1500р", 1500), ("1500 руб.", 1500), ("2 000 рублей", 2000)]:
        assert parse_price(s) == v, s
    for s in ["", None, "abc", "-5", "1.5", "15 000 000 000"]:
        assert parse_price(s) is None, s


def test_deal_status():
    assert deal_status(None, True) == "pending" and deal_status(True, None) == "pending"
    assert deal_status(True, True) == "completed" and deal_status(False, False) == "failed"
    assert deal_status(True, False) == "disputed"


def test_texts():
    assert money(1234567) == "1 234 567 ₽"
    assert post_url("@trade", 5) == "https://t.me/trade/5"
    assert post_url("-1001234", 7) == "https://t.me/c/1234/7" and post_url("123", 1) is None
    assert user_link("Ник<", 42, None) == '<a href="tg://user?id=42">Ник&lt;</a>' and user_link("x", 1, "bob") == "@bob"
    cap = lot_caption(lot_id=3, title="<Sol Ring>" * 50, condition="NM", seller="Пётр", seller_avg=4.5, seller_count=2,
                      start_price=100, current_price=200, leader="Анна", bids=3, ends_at=NOW, status="active",
                      next_bid=210, tz="Europe/Moscow")
    assert len(cap) <= 1024 and "&lt;Sol Ring&gt;" in cap and "210 ₽" in cap and "⭐ 4.5 (2)" in cap
    assert "15:00" in cap  # 12:00 UTC = 15:00 МСК
    sold = lot_caption(lot_id=3, title="Sol", condition="LP", seller="П", seller_avg=None, seller_count=0,
                       start_price=100, current_price=200, leader="А", bids=1, ends_at=NOW, status="sold",
                       next_bid=210, tz="Europe/Moscow")
    assert "Продано за <b>200 ₽</b>" in sold and "новый продавец" in sold
    assert len(rate_buttons(9)[0]) == 5 and all(len(b["callback_data"]) <= 64 for b in rate_buttons(10**9)[0])
    assert deal_buttons(4)[0][0]["callback_data"] == "deal:4:ok"
