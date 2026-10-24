"""Парсер текстовых деклистов (Moxfield / Archidekt / MTGO / просто «1 Название») и проверка EDH."""
import re
from collections import Counter
from dataclasses import dataclass

HEADERS = {
    "commander": "commander", "commanders": "commander", "командир": "commander", "командиры": "commander",
    "deck": "main", "main": "main", "maindeck": "main", "mainboard": "main", "колода": "main",
    "sideboard": "side", "side": "side", "сайдборд": "side", "companion": "side", "maybeboard": "side",
    # «Респонс»: герой, приказы, основная и дополнительная колода
    "герой": "commander", "hero": "commander", "приказы": "orders", "приказ": "orders", "orders": "orders",
    "основная колода": "main", "дополнительная колода": "side", "доп. колода": "side", "доп колода": "side",
}
BASICS = {"plains", "island", "swamp", "mountain", "forest", "wastes", "равнина", "остров", "болото", "гора", "лес"}
LINE_RE = re.compile(r"^(?:SB:\s*)?(\d+)\s*[xXхХ]?\s+(.+)$")


@dataclass
class ParsedCard:
    qty: int
    name: str
    section: str = "main"        # main | side | commander | orders («Респонс»)
    is_commander: bool = False
    tail: bool = False           # последний блок после пустой строки в списке без заголовков (Moxfield/MTGO)
    set_code: str | None = None  # издание из строки «1 Sol Ring (CMM) 410»
    number: str | None = None


PRINT_RE = re.compile(r"\s+\(([A-Za-z0-9]{2,6})\)(?:\s+([\w★-]+))?$")


def _clean_name(name: str) -> tuple[str, str | None, str | None]:
    """Название без пометок Archidekt/Moxfield и издание, если указано: (имя, сет, номер)."""
    name = name.strip()
    name = re.sub(r"(\s*\[[^\]]*\])+$", "", name)               # [Ramp] - категории Archidekt
    name = re.sub(r"(\s+\*\w+\*)+$", "", name)                   # *F* - фойл
    m = PRINT_RE.search(name)                                    # (CMM) 400
    if not m:
        return name.strip(), None, None
    return name[:m.start()].strip(), m.group(1).lower(), m.group(2)


def parse_decklist(text: str) -> tuple[list[ParsedCard], list[str]]:
    cards: list[ParsedCard] = []
    errors: list[str] = []
    section = "main"
    headers = False
    block, block_cards = 0, 0         # блоки разделены пустыми строками
    blocks: list[int] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            if block_cards:
                block, block_cards = block + 1, 0
            continue
        if line.startswith("//") or line.startswith("#"):
            continue
        header = re.sub(r"\s*\(\d+\)\s*:?\s*$|:\s*$", "", line).lower()
        if header in HEADERS and not LINE_RE.match(line):
            section = HEADERS[header]
            headers = True
            continue
        sb = line.upper().startswith("SB:")
        m = LINE_RE.match(line)
        qty, name = (int(m.group(1)), m.group(2)) if m else (1, line)
        name, set_code, number = _clean_name(name)
        if not name:
            errors.append(raw)
            continue
        sec = "side" if sb else section
        cards.append(ParsedCard(qty, name, sec, is_commander=sec == "commander", set_code=set_code, number=number))
        blocks.append(block)
        block_cards += 1
    # Moxfield и MTGO без заголовков: последний блок после пустой строки - командир или сайдборд
    last = max(blocks, default=0)
    if not headers and last > 0:
        for c, b in zip(cards, blocks):
            if b == last and c.section == "main":
                c.tail = True
    return cards, errors


def resolve_tail(cards: list[ParsedCard], commander_format: bool, can_command) -> list[ParsedCard]:
    """Хвостовой блок без заголовков: в командирском формате 1-2 легендарные карты - командиры, иначе - сайдборд.
    can_command(name) -> bool проверяет по базе карт, может ли карта быть командиром."""
    tail = [c for c in cards if c.tail]
    if not tail or any(c.is_commander for c in cards):
        return cards
    if commander_format:
        if sum(c.qty for c in tail) <= 2 and all(can_command(c.name) for c in tail):
            for c in tail:
                c.section, c.is_commander = "commander", True
        return cards
    for c in tail:
        c.section = "side"
    return cards


def apply_commander(cards: list[ParsedCard], commander: str | None) -> list[ParsedCard]:
    """Если командир передан отдельно и в списке не отмечен - отмечаем (или добавляем)."""
    if not commander or any(c.is_commander for c in cards):
        return cards
    target = commander.strip().lower()
    for c in cards:
        if c.name.lower() == target:
            c.is_commander, c.section = True, "commander"
            return cards
    cards.append(ParsedCard(1, commander.strip(), "commander", True))
    return cards


def validate_edh(cards: list[ParsedCard]) -> list[str]:
    """Предупреждения (не блокируют сохранение): размер, командир, singleton."""
    warns = []
    playing = [c for c in cards if c.section != "side"]
    total = sum(c.qty for c in playing)
    if total != 100:
        warns.append(f"В колоде {total} карт вместо 100")
    cmd = [c for c in cards if c.is_commander]
    if not cmd:
        warns.append("Командир не указан")
    elif sum(c.qty for c in cmd) > 2:
        warns.append("Командиров больше двух")
    counts = Counter()
    for c in playing:
        counts[c.name.lower()] += c.qty
    dupes = sorted(n for n, q in counts.items() if q > 1 and n not in BASICS)
    if dupes:
        warns.append("Повторяются карты (singleton): " + ", ".join(dupes[:10]))
    return warns
