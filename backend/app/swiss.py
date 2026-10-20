"""Чистая логика швейцарской системы: без БД и FastAPI, легко тестируется.

Очки: победа 3, ничья 1, поражение 0. Bye (пропуск тура) = победа (3 очка).
Тайбрейки по порядку: OWP, Buchholz, рейтинг клуба, жребий (seed).
Для турнира в 1 тур OWP и Buchholz почти ничего не разрешают, поэтому
запасной критерий - рейтинг клуба, затем seed.
"""
from dataclasses import dataclass

WIN, DRAW, LOSS = 3, 1, 0
MIN_WP = 0.33  # нижний порог OWP, как в стандартных правилах ККИ


@dataclass(frozen=True)
class MatchRec:
    p1: int
    p2: int | None          # None = bye для p1
    result: str | None      # "p1" | "p2" | "draw" | None (ещё не сыграно)


@dataclass
class Row:
    player_id: int
    points: int = 0
    wins: int = 0
    rounds: int = 0
    owp: float = 0.0
    buchholz: int = 0
    club_rating: float = 0.0
    seed: int = 0
    rank: int = 0


def _score(m: MatchRec) -> tuple[int, int]:
    """Очки (p1, p2) за сыгранный матч."""
    if m.p2 is None:
        return WIN, 0
    return {"p1": (WIN, LOSS), "p2": (LOSS, WIN), "draw": (DRAW, DRAW)}[m.result]


def compute_standings(players: dict[int, tuple[float, int]], matches: list[MatchRec]) -> list[Row]:
    """players: id -> (club_rating, seed). Учитываются только завершённые матчи."""
    rows = {pid: Row(pid, club_rating=r, seed=s) for pid, (r, s) in players.items()}
    opponents: dict[int, list[int]] = {pid: [] for pid in players}

    for m in matches:
        if m.p2 is not None and m.result is None:
            continue
        s1, s2 = _score(m)
        r1 = rows[m.p1]
        r1.points += s1
        r1.rounds += 1
        r1.wins += s1 == WIN
        if m.p2 is not None:
            r2 = rows[m.p2]
            r2.points += s2
            r2.rounds += 1
            r2.wins += s2 == WIN
            opponents[m.p1].append(m.p2)
            opponents[m.p2].append(m.p1)

    def wp(r: Row) -> float:
        return max(MIN_WP, r.points / (WIN * r.rounds)) if r.rounds else MIN_WP

    for pid, row in rows.items():
        opps = opponents[pid]
        row.buchholz = sum(rows[o].points for o in opps)
        row.owp = sum(wp(rows[o]) for o in opps) / len(opps) if opps else 0.0

    ordered = sorted(rows.values(),
                     key=lambda r: (-r.points, -r.owp, -r.buchholz, -r.club_rating, r.seed))
    for i, r in enumerate(ordered, 1):
        r.rank = i
    return ordered


def _pair(order: list[int], played: set[frozenset]) -> list[tuple[int, int]] | None:
    """Бэктрекинг: верхнему игроку ищем лучшего из оставшихся без повторной встречи."""
    if not order:
        return []
    a = order[0]
    for i in range(1, len(order)):
        b = order[i]
        if frozenset((a, b)) in played:
            continue
        sub = _pair(order[1:i] + order[i + 1:], played)
        if sub is not None:
            return [(a, b)] + sub
    return None


def pair_round(players: dict[int, tuple[float, int]], matches: list[MatchRec],
               active: set[int] | None = None) -> list[tuple[int, int | None]]:
    """Возвращает пары (p1, p2); p2=None означает bye.
    players - все участники (для таблицы); active - кто играет дальше (без выбывших)."""
    if not matches:
        order = [pid for pid, _ in sorted(players.items(), key=lambda kv: kv[1][1])]  # жребий
    else:
        order = [r.player_id for r in compute_standings(players, matches)]
    if active is not None:
        order = [p for p in order if p in active]

    played = {frozenset((m.p1, m.p2)) for m in matches if m.p2 is not None}
    had_bye = {m.p1 for m in matches if m.p2 is None}

    bye = None
    if len(order) % 2:
        # bye получает самый нижний в таблице, у кого его ещё не было, если остальных можно спарить
        candidates = [p for p in reversed(order) if p not in had_bye] or list(reversed(order))
        for cand in candidates:
            rest = [p for p in order if p != cand]
            pairs = _pair(rest, played)
            if pairs is not None:
                bye = cand
                break
        else:
            bye = candidates[0]
            pairs = _pair([p for p in order if p != bye], set())
    else:
        pairs = _pair(order, played)
        if pairs is None:  # повторных встреч не избежать (мало игроков для числа туров)
            pairs = _pair(order, set())

    result: list[tuple[int, int | None]] = list(pairs)
    if bye is not None:
        result.append((bye, None))
    return result


def default_rounds(n_players: int) -> int:
    """Стандарт: ceil(log2(n)), минимум 1."""
    return max(1, (n_players - 1).bit_length())
