"""Оценка брекета колоды Commander по официальной системе Commander Brackets (Wizards of the Coast).

Правила брекетов (на 2026 год, бета; сверяйте с magic.wizards.com при обновлениях):
- 1 «Exhibition» и 2 «Core»: без Game Changers, без массового уничтожения земель (MLD),
  без комбо из двух карт; экстра-ходы - в малом количестве и без цепочек (в 1 - лучше без них);
- 3 «Upgraded»: до трёх Game Changers, без MLD, комбо из двух карт - не в ранней игре,
  экстра-ходы - мало и без цепочек;
- 4 «Optimized» и 5 «cEDH»: ограничений, кроме бан-листа, нет.
Ограничение на тутора убрано в обновлении октября 2025.

Список Game Changers берётся из Scryfall (флаг game_changer) и обновляется вместе с базой карт.
MLD, экстра-ходы и комбо распознаются по названиям и тексту карт - это подсказка судье, а не вердикт:
брекет - договорённость за столом, намерение колоды важнее счётчиков.
1 и 2 по карточкам не различить (разница - в задумке колоды), поэтому оценка «1–2».
"""
import re

# Массовое лишение земель: уничтожить/изгнать/вернуть много земель, держать их повёрнутыми или менять их ману.
MLD_NAMES = {
    "armageddon", "ravages of war", "ruination", "sunder", "winter orb", "static orb", "blood moon",
    "magus of the moon", "back to basics", "jokulhaups", "obliterate", "decree of annihilation", "catastrophe",
    "worldfire", "cataclysm", "tectonic break", "epicenter", "wildfire", "burning of xinye", "destructive force",
    "boom // bust", "impending disaster", "global ruin", "keldon firebombers", "hokori, dust drinker",
    "rising waters", "mana vortex", "contamination", "infernal darkness", "stasis", "apocalypse", "devastation",
    "thoughts of ruin", "acid rain", "desolation angel", "myojin of infinite rage", "fall of the thran",
    "realm razer", "sway of the stars", "upheaval", "hall of gemstone", "storm cauldron",
    "bend or break", "limited resources", "tsunami", "flashfires", "boil",
    
}
MLD_TEXT = re.compile(
    r"destroy all (?:[\w ,]*?)lands|exile all (?:[\w ,]*?)lands|return all lands"
    r"|each player sacrifices (?:all|\w+) lands|lands don't untap|nonbasic lands are mountains"
    r"|each player can't untap more than", re.I)
EXTRA_TURN = re.compile(r"extra turn", re.I)

# Известные комбо из двух карт (бесконечный цикл или мгновенная победа). Не исчерпывающий список.
COMBOS: list[tuple[str, str]] = [
    ("thassa's oracle", "demonic consultation"), ("thassa's oracle", "tainted pact"),
    ("laboratory maniac", "demonic consultation"), ("jace, wielder of mysteries", "demonic consultation"),
    ("isochron scepter", "dramatic reversal"), ("heliod, sun-crowned", "walking ballista"),
    ("exquisite blood", "sanguine bond"), ("exquisite blood", "vito, thorn of the dusk rose"),
    ("kiki-jiki, mirror breaker", "zealous conscripts"), ("kiki-jiki, mirror breaker", "pestermite"),
    ("kiki-jiki, mirror breaker", "deceiver exarch"), ("kiki-jiki, mirror breaker", "restoration angel"),
    ("kiki-jiki, mirror breaker", "felidar guardian"), ("splinter twin", "pestermite"), ("splinter twin", "deceiver exarch"),
    ("saheeli rai", "felidar guardian"), ("basalt monolith", "rings of brighthearth"),
    ("basalt monolith", "power artifact"), ("grim monolith", "power artifact"),
    ("niv-mizzet, parun", "curiosity"), ("niv-mizzet, the firemind", "curiosity"),
    ("niv-mizzet, parun", "ophidian eye"), ("niv-mizzet, parun", "tandem lookout"),
    ("painter's servant", "grindstone"), ("mikaeus, the unhallowed", "triskelion"),
    ("devoted druid", "vizier of remedies"), ("devoted druid", "quillspike"),
    ("worldgorger dragon", "animate dead"), ("dualcaster mage", "twinflame"), ("dualcaster mage", "heat shimmer"),
    ("underworld breach", "lion's eye diamond"), ("bloodchief ascension", "mindcrank"), ("earthcraft", "squirrel nest"),
    ("godo, bandit warlord", "helm of the host"), ("food chain", "eternal scourge"),
    ("food chain", "misthollow griffin"), ("kinnan, bonder prodigy", "basalt monolith"),
    ("auriok salvagers", "lion's eye diamond"), ("peregrine drake", "deadeye navigator"),
    ("palinchron", "deadeye navigator"), ]
_COMBO_SET = {tuple(sorted(p)) for p in COMBOS}

NAMES = {1: "Exhibition", 2: "Core", 3: "Upgraded", 4: "Optimized", 5: "cEDH"}


def _key(name: str) -> str:
    return " ".join(name.lower().replace("’", "'").split())


def assess(cards: list[tuple[str, str | None, bool]]) -> dict:
    """cards: (название, текст Oracle, Game Changer) основной колоды и командиров.
    Возвращает минимальный брекет по карточкам и причины."""
    names = {}
    for name, text, gc in cards:
        names.setdefault(_key(name), (name, text or "", gc))
    keys = set(names)
    front = {k.split(" // ")[0]: k for k in keys}
    game_changers = sorted(n for n, _, gc in names.values() if gc)
    mld = sorted(n for k, (n, t, _) in names.items() if k in MLD_NAMES or k.split(" // ")[0] in MLD_NAMES or MLD_TEXT.search(t))
    extra = sorted(n for n, t, _ in names.values() if EXTRA_TURN.search(t))
    combos = sorted([names[front.get(a, a)][0], names[front.get(b, b)][0]] for a, b in _COMBO_SET
                    if (a in keys or a in front) and (b in keys or b in front))

    level, reasons = 1, []
    gc_n = len(game_changers)
    if gc_n > 3:
        level = 4
        reasons.append(f"Game Changers: {gc_n} — больше трёх, это брекет 4+")
    elif gc_n:
        level = max(level, 3)
        reasons.append(f"Game Changers: {gc_n} — в брекетах 1–2 их нет, в 3 — до трёх")
    if mld:
        level = 4
        reasons.append(f"Массовое лишение земель ({', '.join(mld)}) — разрешено только с брекета 4")
    if len(extra) >= 3:
        level = 4
        reasons.append(f"Экстра-ходов {len(extra)} — похоже на цепочку, в брекетах 1–3 их мало и без цепочек")
    elif extra:
        level = max(level, 2)
        reasons.append(f"Экстра-ходы: {len(extra)} — допустимо с брекета 2 в малом количестве, без цепочек")
    if combos:
        level = max(level, 3)
        reasons.append("Комбо из двух карт: " + "; ".join(" + ".join(c) for c in combos)
                       + " — в брекете 3 только не в ранней игре; если собирается рано — это 4")
    label = "1–2" if level <= 2 else f"{level}+" if level == 4 else str(level)
    return {"min_bracket": level, "label": label, "game_changers": game_changers, "mld": mld, "extra_turns": extra,
            "combos": combos, "reasons": reasons}


def mismatch(declared: int | None, a: dict) -> str | None:
    """Предупреждение судье: заявленный брекет ниже, чем показывают карты."""
    if declared is None or a["min_bracket"] <= declared:
        return None
    return f"Заявлен брекет {declared}, а по карточкам — не ниже {a['min_bracket']}: " + "; ".join(a["reasons"])
