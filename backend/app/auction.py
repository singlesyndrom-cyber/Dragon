"""Правила аукциона (чистая логика, без БД и Telegram)."""
import math
import re
from datetime import datetime, timedelta

CONDITIONS = {"NM": "Near Mint", "LP": "Lightly Played", "MP": "Moderately Played",
              "HP": "Heavily Played", "DMG": "Damaged"}
DURATIONS_H = (1, 3, 6, 12, 24, 72)
SNIPE_WINDOW = timedelta(minutes=5)   # ставка в последние 5 минут...
SNIPE_EXTEND = timedelta(minutes=5)   # ...продлевает торги до «сейчас + 5 минут»
MIN_STEP = 10
STEP_PCT = 0.05
MIN_START = 10
MAX_PRICE = 10_000_000
MAX_ACTIVE_LOTS = 10
TITLE_MIN, TITLE_MAX = 2, 100


class AuctionError(Exception):
    """Понятная пользователю ошибка (текст уходит в бот и в API как есть)."""


def money(n: int) -> str:
    return f"{n:,}".replace(",", " ") + " ₽"


def bid_step(price: int) -> int:
    return max(MIN_STEP, math.ceil(price * STEP_PCT))


def min_next_bid(start_price: int, current_price: int | None) -> int:
    return start_price if current_price is None else current_price + bid_step(current_price)


def extend_end(ends_at: datetime, now: datetime) -> datetime:
    if ends_at - now < SNIPE_WINDOW:
        return max(ends_at, now + SNIPE_EXTEND)
    return ends_at


def check_bid(*, amount: int | None, start_price: int, current_price: int | None, seller_id: int,
              leader_id: int | None, bidder_id: int, ends_at: datetime, now: datetime, active: bool) -> None:
    if not active or now >= ends_at:
        raise AuctionError("Торги по этому лоту завершены")
    if bidder_id == seller_id:
        raise AuctionError("Нельзя делать ставки на свой лот")
    if leader_id == bidder_id:
        raise AuctionError("Ваша ставка уже лидирует")
    if amount is None:
        raise AuctionError("Укажите сумму ставки числом, например 1500")
    need = min_next_bid(start_price, current_price)
    if amount < need:
        raise AuctionError(f"Минимальная ставка сейчас {money(need)}")
    if amount > MAX_PRICE:
        raise AuctionError(f"Слишком большая ставка: максимум {money(MAX_PRICE)}")


def check_lot(title: str, condition: str, start_price: int | None, hours: int) -> str:
    title = re.sub(r"\s+", " ", title or "").strip()
    if not TITLE_MIN <= len(title) <= TITLE_MAX:
        raise AuctionError(f"Название — от {TITLE_MIN} до {TITLE_MAX} символов")
    if condition not in CONDITIONS:
        raise AuctionError("Выберите состояние карты: " + ", ".join(CONDITIONS))
    if start_price is None or not MIN_START <= start_price <= MAX_PRICE:
        raise AuctionError(f"Стартовая цена — от {money(MIN_START)} до {money(MAX_PRICE)}")
    if hours not in DURATIONS_H:
        raise AuctionError("Длительность: " + ", ".join(f"{h} ч" for h in DURATIONS_H))
    return title


def parse_price(text: str | None) -> int | None:
    if not text:
        return None
    s = re.sub(r"(?i)(₽|руб(лей|ля|ль)?\.?|р\.?)\s*$", "", text.strip())
    s = re.sub(r"[\s _]", "", s)
    return int(s) if re.fullmatch(r"\d{1,9}", s) else None


def deal_status(seller_ok: bool | None, buyer_ok: bool | None) -> str:
    """pending -> пока не ответили оба; completed -> оба подтвердили; failed -> оба отказались;
    disputed -> ответы расходятся (смотрит админ)."""
    if seller_ok is None or buyer_ok is None:
        return "pending"
    if seller_ok and buyer_ok:
        return "completed"
    if not seller_ok and not buyer_ok:
        return "failed"
    return "disputed"
