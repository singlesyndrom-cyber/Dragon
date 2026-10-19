"""Аналитика меты (чистая логика, без БД).

Запись (Entry) = одна колода, поданная на один завершённый турнир.
Игра (Game) = результат одного участника в одном матче/за одним EDH-столом.
Ожидаемый винрейт: швейцарка 0.5, EDH-стол из N игроков 1/N. Разница с ним (edge)
честнее сырого винрейта, потому что столы бывают по 3, 4 и 5 человек.
"""
from collections import Counter, defaultdict
from dataclasses import dataclass

from .decklist import BASICS

NO_COMMANDER = "(без командира)"


@dataclass
class Entry:
    id: int
    commander: str            # ключ командира; для партнёров - имена через " / "
    cards: dict[str, str]     # lower -> отображаемое имя (основная колода, без командиров и базовых земель)


@dataclass(frozen=True)
class Game:
    entry_id: int
    outcome: str              # win | draw | loss  (draw в EDH = ничья или истечение таймера)
    expected: float


def _is_basic(low: str) -> bool:
    return low in BASICS or (low.startswith("snow-covered ") and low[13:] in BASICS)


def build_entry(entry_id: int, rows: list[tuple[str, bool, str]]) -> Entry:
    """rows: (name, is_commander, section)."""
    cmd, cards = [], {}
    for name, is_cmd, section in rows:
        if is_cmd:
            cmd.append(name)
        elif section == "main" and not _is_basic(name.lower()):
            cards.setdefault(name.lower(), name)
    return Entry(entry_id, " / ".join(sorted(cmd)), cards)


def commander_stats(entries: list[Entry], games: list[Game], min_games: int = 5) -> list[dict]:
    by_id = {e.id: e for e in entries}
    total = len(entries)
    st = defaultdict(lambda: {"decks": 0, "wins": 0, "draws": 0, "losses": 0, "games": 0, "exp": 0.0})
    for e in entries:
        st[e.commander or NO_COMMANDER]["decks"] += 1
    for g in games:
        e = by_id.get(g.entry_id)
        if not e:
            continue
        s = st[e.commander or NO_COMMANDER]
        s["games"] += 1
        s[{"win": "wins", "draw": "draws", "loss": "losses"}[g.outcome]] += 1
        s["exp"] += g.expected
    out = []
    for name, s in st.items():
        n = s["games"]
        wr = s["wins"] / n if n else None
        ex = s["exp"] / n if n else None
        out.append({
            "commander": name, "decks": s["decks"], "pick_rate": round(s["decks"] / total, 4) if total else 0.0,
            "games": n, "wins": s["wins"], "draws": s["draws"], "losses": s["losses"],
            "win_rate": None if wr is None else round(wr, 4),
            "expected_win_rate": None if ex is None else round(ex, 4),
            "edge": None if wr is None else round(wr - ex, 4),
            "reliable": n >= min_games,
        })
    return sorted(out, key=lambda r: (-r["decks"], -r["games"], r["commander"]))


def card_usage(entries: list[Entry], commander: str | None = None, min_decks: int = 1, limit: int = 50) -> dict:
    """Процент колод (в выборке или у одного командира), где встречается карта."""
    pool = [e for e in entries if commander is None or e.commander.lower() == commander.strip().lower()]
    total = len(pool)
    counts, names = Counter(), {}
    for e in pool:
        for low, disp in e.cards.items():
            counts[low] += 1
            names.setdefault(low, disp)
    rows = [{"card": names[k], "decks": c, "usage_pct": round(100 * c / total, 1)}
            for k, c in sorted(counts.items(), key=lambda kv: (-kv[1], names[kv[0]])) if c >= min_decks]
    return {"decks_in_scope": total, "cards": rows[:limit]}
