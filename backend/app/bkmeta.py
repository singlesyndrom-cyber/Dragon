"""Мета «Берсерка»: связки стихий, архетипы (по названию колоды), профиль колод и результаты.

Колода «Берсерка» - не командир, а набор стихий: поэтому мета считается по связкам стихий (объективно, по картам)
и по архетипам (как игроки назвали колоду - «Слуа», «Механический дракон»). Результаты - по матчам швейцарки:
ожидаемый винрейт 50%, edge = винрейт минус ожидаемый.
"""
from collections import Counter, defaultdict

from sqlalchemy import select

from .meta import Entry, Game, commander_stats
from .models import Card, Deck, DeckCard

ELEMENT_ORDER = ["Степи", "Горы", "Леса", "Болота", "Тьма"]
NEUTRAL = "Нейтральная"
NO_ELEMENT = "Нейтральные"


def combo(elements: set[str]) -> str:
    """«Горы + Тьма»: стихии по порядку правил; нейтральные карты стихией не считаются."""
    els = [e for e in ELEMENT_ORDER if e in elements]
    return " + ".join(els) if els else NO_ELEMENT


def archetype_key(name: str | None) -> str:
    return " ".join((name or "").lower().replace("ё", "е").split()) or "(без названия)"


async def deck_profiles(session, deck_ids) -> dict[int, dict]:
    """deck_id -> связка стихий, название, размер, средняя стоимость, доли элитных и летающих (основная колода)."""
    ids = list(set(deck_ids))
    if not ids:
        return {}
    names = dict((await session.execute(select(Deck.id, Deck.name).where(Deck.id.in_(ids)))).all())
    acc: dict[int, dict] = defaultdict(lambda: {"size": 0, "cost": 0.0, "elite": 0, "flyers": 0, "elements": set()})
    rows = await session.execute(select(DeckCard.deck_id, DeckCard.qty, Card.cmc, Card.extra)
                                 .join(Card, Card.id == DeckCard.card_id)
                                 .where(DeckCard.deck_id.in_(ids), DeckCard.section != "side"))
    for deck_id, qty, cmc, extra in rows.all():
        ex = extra or {}
        a = acc[deck_id]
        a["size"] += qty
        a["cost"] += (cmc or 0) * qty
        a["elite"] += qty if ex.get("elite") else 0
        a["flyers"] += qty if "летающ" in (ex.get("kind") or "").lower() else 0
        a["elements"] |= {e for e in ex.get("elements") or [] if e != NEUTRAL}
    out = {}
    for d in ids:
        a = acc.get(d) or {"size": 0, "cost": 0.0, "elite": 0, "flyers": 0, "elements": set()}
        n = a["size"] or 1
        out[d] = {"name": names.get(d) or "", "combo": combo(a["elements"]), "elements": sorted(a["elements"]),
                  "size": a["size"], "avg_cost": a["cost"] / n, "elite_share": a["elite"] / n,
                  "flyer_share": a["flyers"] / n}
    return out


def _keyed(entry_keys: dict[int, str], games: list[Game], min_games: int) -> list[dict]:
    """Частота и результаты по ключу (связке стихий или архетипу) - тем же расчётом, что для командиров MTG."""
    fake = [Entry(eid, key, {}) for eid, key in entry_keys.items()]
    rows = commander_stats(fake, games, min_games)
    for r in rows:
        r["key"] = r.pop("commander")
    return rows


def summarize(profiles_by_entry: dict[int, dict], games: list[Game], min_games: int = 5) -> dict:
    """profiles_by_entry: entry_id -> профиль колоды (из deck_profiles). Колоды без карт из базы
    (список не распознан) не учитываются - иначе они дают «0 карт» и «Нейтральные»."""
    skipped = sum(1 for p in profiles_by_entry.values() if not p["size"])
    profiles_by_entry = {e: p for e, p in profiles_by_entry.items() if p["size"]}
    total = len(profiles_by_entry)
    if not total:
        return {"decks": 0, "skipped": skipped, "combos": [], "archetypes": [], "elements": [], "profile": None}
    combos = _keyed({e: p["combo"] for e, p in profiles_by_entry.items()}, games, min_games)
    shown: dict[str, Counter] = defaultdict(Counter)         # как чаще всего пишут название архетипа
    for p in profiles_by_entry.values():
        shown[archetype_key(p["name"])][p["name"].strip() or "(без названия)"] += 1
    arch = _keyed({e: archetype_key(p["name"]) for e, p in profiles_by_entry.items()}, games, min_games)
    for r in arch:
        r["key"] = shown[r["key"]].most_common(1)[0][0]
    el = Counter(e for p in profiles_by_entry.values() for e in p["elements"])
    n = lambda k: sum(p[k] for p in profiles_by_entry.values()) / total     # noqa: E731
    return {
        "decks": total, "skipped": skipped, "combos": combos, "archetypes": arch,
        "elements": [{"element": e, "decks": el[e], "share": round(el[e] / total, 4)} for e in ELEMENT_ORDER if el[e]],
        "profile": {"size": round(n("size"), 1), "avg_cost": round(n("avg_cost"), 2),
                    "elite_share": round(n("elite_share"), 3), "flyer_share": round(n("flyer_share"), 3),
                    "colors": round(sum(len(p["elements"]) for p in profiles_by_entry.values()) / total, 2)},
    }
