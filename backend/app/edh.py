"""Чистая логика EDH-рейтинга («банк с нулевой суммой и штрафным таймером») и рассадки.

Победа до таймера: каждый проигравший теряет 7% своего банка, победитель получает сумму.
Ничья / истечение 70 минут: каждый игрок теряет 7% своего банка (очки сгорают).
Стол: 3-5 игроков, проценты считаются от личного банка каждого.
"""
import random
from collections import defaultdict

RATE = 0.07
START_BANK = 1000.0
WEEKLY_BONUS = 150.0
MATCH_MINUTES = 70


def settle(banks: dict[int, float], winner: int | None, rate: float = RATE) -> dict[int, float]:
    """Возвращает изменение банка для каждого игрока стола."""
    if winner is None:
        return {pid: -round(b * rate, 2) for pid, b in banks.items()}
    if winner not in banks:
        raise ValueError("победитель не за столом")
    losses = {pid: round(b * rate, 2) for pid, b in banks.items() if pid != winner}
    deltas = {pid: -x for pid, x in losses.items()}
    deltas[winner] = round(sum(losses.values()), 2)
    return deltas


def table_sizes(n: int) -> list[int]:
    """Разбиение n игроков на столы по 3-5, предпочитая столы по 4."""
    if n < 3:
        raise ValueError("нужно минимум 3 игрока")
    r = n % 4
    if r == 0:
        return [4] * (n // 4)
    if r == 1:
        return [5] + [4] * ((n - 5) // 4)
    if r == 2:
        return [3, 3] + [4] * ((n - 6) // 4)
    return [3] + [4] * ((n - 3) // 4)


def seat(players: list[tuple[int, int]], rng: random.Random | None = None) -> list[tuple[int, list[int]]]:
    """players: (user_id, bracket). Случайная рассадка внутри брекетов, рейтинг игнорируется.
    Группы меньше 3 человек присоединяются к ближайшему брекету.
    Возвращает [(bracket, [user_id, ...]), ...]."""
    rng = rng or random.Random()
    if len(players) < 3:
        raise ValueError("нужно минимум 3 игрока")
    groups: dict[int, list[int]] = defaultdict(list)
    for uid, br in players:
        groups[br].append(uid)
    while len(groups) > 1:
        small = [b for b, m in groups.items() if len(m) < 3]
        if not small:
            break
        b = min(small)
        other = min((x for x in groups if x != b), key=lambda x: (abs(x - b), x))
        groups[other] += groups.pop(b)
    tables = []
    for br in sorted(groups):
        members = groups[br][:]
        rng.shuffle(members)
        i = 0
        for size in table_sizes(len(members)):
            tables.append((br, members[i:i + size]))
            i += size
    return tables
