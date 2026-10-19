"""Политика доставки очереди (чистая логика)."""
import re

MAX_ATTEMPTS = 8


def backoff_seconds(attempts: int) -> int:
    """30 c, 1 мин, 2 мин ... не больше часа."""
    return min(30 * 2 ** max(attempts - 1, 0), 3600)


def parse_chat_id(raw: str) -> int | str:
    raw = raw.strip()
    return int(raw) if re.fullmatch(r"-?\d+", raw) else raw  # «@channel» остаётся строкой
