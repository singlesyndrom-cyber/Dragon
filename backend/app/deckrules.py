"""Правила форматов MTG для конструктора колод.

Проверка не мешает сохранять колоду: черновик может быть неполным. Она возвращает список замечаний,
которые редактор показывает рядом с колодой: «error» - колода не пройдёт проверку на турнире, «warn» - стоит
посмотреть. Легальность карт берётся из данных Scryfall (Card.legalities).
"""
import re
from collections import Counter
from dataclasses import dataclass

FORMATS: dict[str, dict] = {
    "commander": {"title": "Commander (EDH)", "size": 100, "commander": True},
    "duel": {"title": "Duel Commander", "size": 100, "commander": True},
    "brawl": {"title": "Brawl", "size": 100, "commander": True},
    "standard": {"title": "Standard", "size": 60},
    "pioneer": {"title": "Pioneer", "size": 60},
    "modern": {"title": "Modern", "size": 60},
    "legacy": {"title": "Legacy", "size": 60},
    "vintage": {"title": "Vintage", "size": 60},
    "pauper": {"title": "Pauper", "size": 60},
    "casual": {"title": "Свободный", "size": 0},
    # классический «Берсерк» (Расширенные правила 6.1-1, глоссарий «Колода констрактед / лимитед»)
    "berserk": {"title": "Берсерк: констрактед", "size": 30, "max": 50, "copies": 3, "game": "berserk",
                "sideboard": False},
    "berserk_limited": {"title": "Берсерк: лимитед", "size": 30, "copies": None, "game": "berserk",
                        "sideboard": False},
}
GAME_FORMATS = {"berserk": "berserk"}      # формат по умолчанию для колод не-MTG
SIDEBOARD_MAX = 15
COPIES_WORD = {3: "трёх", 4: "четырёх"}
ANY_NUMBER = re.compile(r"a deck can have any number of cards named", re.I)
UP_TO = re.compile(r"a deck can have up to (\w+) cards named", re.I)
WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}


@dataclass
class Entry:
    """Строка колоды с данными карты (card - None, если карта не нашлась в базе)."""
    name: str
    qty: int
    section: str           # main | side | commander
    card: object | None    # models.Card


def _copies_limit(card, singleton: bool) -> int | None:
    """Сколько копий можно. None - без ограничений."""
    if card is None:
        return 1 if singleton else 4
    if "basic" in (card.type_line or "").lower() and "land" in (card.type_line or "").lower():
        return None
    text = card.text or ""
    if ANY_NUMBER.search(text):
        return None
    m = UP_TO.search(text)
    if m:
        return WORDS.get(m.group(1).lower(), 4)
    return 1 if singleton else 4


def can_be_commander(card, fmt: str) -> bool:
    t = (card.type_line or "").lower()
    if "legendary" in t and ("creature" in t or (fmt == "brawl" and "planeswalker" in t)):
        return True
    return "can be your commander" in (card.text or "").lower()


def _pairs(cards: list) -> bool:
    """Два командира допустимы: оба с Partner / Friends forever, или командир + Background."""
    texts = [(c.text or "").lower() for c in cards]
    types = [(c.type_line or "").lower() for c in cards]
    if all("partner" in x or "friends forever" in x or "doctor's companion" in x for x in texts):
        return True
    return any("background" in t for t in types) and any("choose a background" in x for x in texts)


def check(entries: list[Entry], fmt: str) -> list[dict]:
    """Замечания к колоде: [{"level": "error"|"warn", "text": ...}]."""
    rules = FORMATS.get(fmt) or FORMATS["casual"]
    out: list[dict] = []

    def err(t):
        out.append({"level": "error", "text": t})

    def warn(t):
        out.append({"level": "warn", "text": t})

    playing = [e for e in entries if e.section in ("main", "commander")]
    side = [e for e in entries if e.section == "side"]
    total = sum(e.qty for e in playing)
    is_cmd = rules.get("commander", False)

    if rules["size"]:
        if is_cmd and total != rules["size"]:
            err(f"В колоде {total} карт, нужно ровно {rules['size']} (с командиром)")
        elif not is_cmd and total < rules["size"]:
            err(f"В основной колоде {total} карт, нужно не меньше {rules['size']}")
        elif rules.get("max") and total > rules["max"]:
            err(f"В колоде {total} карт, можно не больше {rules['max']}")
        if not is_cmd and rules.get("sideboard", True) and sum(e.qty for e in side) > SIDEBOARD_MAX:
            err(f"В сайдборде {sum(e.qty for e in side)} карт, можно не больше {SIDEBOARD_MAX}")

    if is_cmd:
        cmd = [e for e in entries if e.section == "commander"]
        cards = [e.card for e in cmd if e.card is not None]
        if not cmd:
            err("Не выбран командир")
        elif sum(e.qty for e in cmd) > 2:
            err("Командиров больше двух")
        else:
            bad = [c.name for c in cards if not can_be_commander(c, fmt)]
            if bad:
                err("Не может быть командиром: " + ", ".join(bad))
            if len(cards) == 2 and not _pairs(cards):
                err("Два командира возможны только с Partner, Friends forever или Background")
        if cards:
            identity = set()
            for c in cards:
                identity |= set((c.extra or {}).get("color_identity") or [])
            outside = sorted({e.name for e in playing if e.card is not None and e.section == "main"
                              and not set((e.card.extra or {}).get("color_identity") or []) <= identity})
            if outside:
                colors = "".join(c for c in "WUBRG" if c in identity) or "бесцветный"
                err(f"Вне цветов командира ({colors}): " + ", ".join(outside[:12])
                    + (" и др." if len(outside) > 12 else ""))

    # копии: в командирских форматах singleton считается по колоде с командиром, иначе - основа + сайд
    pool = playing if is_cmd else playing + side
    counts: Counter = Counter()
    cards_by_name: dict = {}
    for e in pool:
        counts[e.name] += e.qty
        cards_by_name.setdefault(e.name, e.card)
    if rules["size"]:
        too_many = []
        for name, n in counts.items():
            limit = rules["copies"] if "copies" in rules else _copies_limit(cards_by_name[name], is_cmd)
            if limit is not None and n > limit:
                too_many.append(f"{name} ×{n}")
        if too_many:
            err(("Singleton — одна копия каждой карты: " if is_cmd
                 else f"Больше {COPIES_WORD.get(rules.get('copies', 4))} копий: ")
                + ", ".join(sorted(too_many)[:12]))

    if fmt in FORMATS and fmt != "casual" and "game" not in rules:
        banned, not_legal, restricted = set(), set(), set()
        for e in playing + side:
            if e.card is None:
                continue
            status = (e.card.legalities or {}).get(fmt)
            if status == "banned":
                banned.add(e.name)
            elif status == "not_legal":
                not_legal.add(e.name)
            elif status == "restricted" and counts.get(e.name, 0) > 1:
                restricted.add(e.name)
        title = rules["title"]
        if banned:
            err(f"Запрещены в {title}: " + ", ".join(sorted(banned)[:12]))
        if not_legal:
            err(f"Не легальны в {title}: " + ", ".join(sorted(not_legal)[:12]) + (" и др." if len(not_legal) > 12 else ""))
        if restricted:
            err("Ограничены (одна копия): " + ", ".join(sorted(restricted)))

    unmatched = sorted({e.name for e in entries if e.card is None})
    if unmatched:
        warn("Не найдены в базе карт: " + ", ".join(unmatched[:12]) + (" и др." if len(unmatched) > 12 else ""))
    return out
