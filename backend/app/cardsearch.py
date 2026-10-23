"""Язык запросов Картотеки в духе Scryfall.

    сол ring                 слова - в названии (английском или русском), все сразу
    !"Sol Ring"              точное название
    t:существо  t:elf        тип (английский или русский)
    o:"возьмите карту"       текст правил
    c:rg  c=rg  c<=rg  c:m   цвета: содержит / ровно / в пределах; m - многоцветная, c - бесцветная
    id:wub                   цветовая идентичность в пределах (подходит в колоду командира)
    mv<=3  pow>=4  tou<2     мана-стоимость, сила, выносливость (loy - верность)
    r:mythic  r>=rare        редкость
    s:cmm                    сет (код)
    f:commander  banned:modern  restricted:vintage
    is:gamechanger is:commander is:dfc is:russian is:vanilla
    kw:flying  a:"John Avon"  usd<1  eur>=5
    -t:creature              отрицание
    t:elf or t:goblin        «или»; скобки группируют: (c:r or c:g) mv<=2
    order:mv  dir:desc       сортировка прямо в запросе
    *                        все карты игры

Ключи понимаются и по-русски: тип:, текст:, цвет:, ид:, мв:, сила:, редкость:, сет:, формат:, есть:, художник:.
"""
import re
from dataclasses import dataclass, field

from sqlalchemy import Float, and_, case, cast, false, func, not_, or_, select, true
from sqlalchemy.sql.elements import ColumnElement

from .cardimport import norm_name
from .models import Card

KEYS = {
    "name": "name", "n": "name", "имя": "name", "название": "name",
    "t": "type", "type": "type", "тип": "type",
    "o": "oracle", "oracle": "oracle", "text": "oracle", "текст": "oracle",
    "c": "color", "color": "color", "colors": "color", "цвет": "color",
    "id": "identity", "identity": "identity", "ci": "identity", "ид": "identity",
    "mv": "mv", "cmc": "mv", "мв": "mv", "мана": "mv",
    "pow": "pow", "power": "pow", "сила": "pow",
    "tou": "tou", "toughness": "tou", "выносливость": "tou",
    "loy": "loy", "loyalty": "loy", "верность": "loy",
    "r": "rarity", "rarity": "rarity", "редкость": "rarity",
    "s": "set", "set": "set", "e": "set", "edition": "set", "сет": "set",
    "f": "format", "format": "format", "legal": "format", "формат": "format",
    "banned": "banned", "запрещена": "banned", "restricted": "restricted", "ограничена": "restricted",
    "is": "is", "есть": "is",
    "kw": "keyword", "keyword": "keyword", "keywords": "keyword", "способность": "keyword",
    "a": "artist", "artist": "artist", "художник": "artist",
    "usd": "usd", "цена": "usd", "eur": "eur",
    "game": "game", "игра": "game",
    "order": "order", "сортировка": "order", "dir": "dir",
}
COLOR_WORDS = {
    "w": "W", "white": "W", "белый": "W", "белая": "W",
    "u": "U", "blue": "U", "синий": "U", "синяя": "U",
    "b": "B", "black": "B", "черный": "B", "чёрный": "B", "черная": "B", "чёрная": "B",
    "r": "R", "red": "R", "красный": "R", "красная": "R",
    "g": "G", "green": "G", "зеленый": "G", "зелёный": "G", "зеленая": "G", "зелёная": "G",
}
GUILDS = {  # пары и тройки цветов по названиям, как у Scryfall
    "azorius": "WU", "dimir": "UB", "rakdos": "BR", "gruul": "RG", "selesnya": "GW", "orzhov": "WB", "izzet": "UR",
    "golgari": "BG", "boros": "RW", "simic": "GU", "esper": "WUB", "grixis": "UBR", "jund": "BRG", "naya": "RGW",
    "bant": "GWU", "abzan": "WBG", "jeskai": "URW", "sultai": "BGU", "mardu": "RWB", "temur": "GUR",
}
RARITY = {"common": 0, "c": 0, "обычная": 0, "uncommon": 1, "u": 1, "необычная": 1, "rare": 2, "r": 2, "редкая": 2,
          "mythic": 3, "m": 3, "мифическая": 3, "special": 4, "особая": 4, "bonus": 5, "бонусная": 5}
RARITY_NAMES = ["common", "uncommon", "rare", "mythic", "special", "bonus"]
FORMATS = {"commander": "commander", "edh": "commander", "командир": "commander", "коммандер": "commander",
           "standard": "standard", "стандарт": "standard", "pioneer": "pioneer", "modern": "modern", "модерн": "modern",
           "legacy": "legacy", "легаси": "legacy", "vintage": "vintage", "винтаж": "vintage", "pauper": "pauper",
           "паупер": "pauper", "duel": "duel", "brawl": "brawl"}
ORDERS = {"name": "name", "имя": "name", "mv": "mv", "cmc": "mv", "мв": "mv", "rarity": "rarity", "редкость": "rarity",
          "usd": "usd", "цена": "usd", "eur": "eur", "set": "set", "сет": "set", "pow": "pow", "power": "pow",
          "tou": "tou", "color": "color", "цвет": "color"}
OPS = ("<=", ">=", "!=", "<", ">", "=", ":")
TOKEN = re.compile(r'\s*(?:(\()|(\))|(-?)([^\s()":<>=!]+)(<=|>=|!=|<|>|=|:)("([^"]*)"|[^\s()]*)|(-?)!"([^"]*)"|(-?)"([^"]*)"|(-?)([^\s()]+))')


@dataclass
class Parsed:
    where: ColumnElement
    warnings: list[str] = field(default_factory=list)
    order: str | None = None
    direction: str | None = None
    game: str | None = None
    words: list[str] = field(default_factory=list)   # слова названия без ключей - для «точное совпадение выше»


class _Tok:
    def __init__(self, kind, neg=False, key=None, op=None, value=None):
        self.kind, self.neg, self.key, self.op, self.value = kind, neg, key, op, value


def tokenize(q: str) -> list[_Tok]:
    out, pos = [], 0
    while pos < len(q):
        m = TOKEN.match(q, pos)
        if not m or m.end() == pos:
            break
        pos = m.end()
        if m.group(1):
            out.append(_Tok("("))
        elif m.group(2):
            out.append(_Tok(")"))
        elif m.group(4) is not None:
            val = m.group(7) if m.group(7) is not None else m.group(6)
            out.append(_Tok("term", bool(m.group(3)), m.group(4).lower(), m.group(5), val))
        elif m.group(9) is not None:
            out.append(_Tok("exact", bool(m.group(8)), value=m.group(9)))
        elif m.group(11) is not None:
            out.append(_Tok("word", bool(m.group(10)), value=m.group(11)))
        elif m.group(13):
            word = m.group(13)
            if not m.group(12) and word.lower() in ("or", "или"):
                out.append(_Tok("or"))
            elif not m.group(12) and word.lower() in ("and", "и"):
                continue
            else:
                out.append(_Tok("word", bool(m.group(12)), value=word))
    return out


def _num(v: str) -> float | None:
    try:
        return float(v.replace(",", "."))
    except ValueError:
        return None


def _cmp(col, op: str, v):
    return {"<": col < v, ">": col > v, "<=": col <= v, ">=": col >= v, "!=": col != v}.get(op, col == v)


def _numeric_extra(key: str):
    """Сила/выносливость/верность лежат строками («*», «1+*»): сравниваем только числовые."""
    raw = Card.extra[key].astext
    return case((raw.op("~")(r"^\d+(\.\d+)?$"), cast(raw, Float)), else_=None)


def _colors(value: str) -> tuple[list[str] | None, str | None]:
    v = value.lower()
    if v in GUILDS:
        return list(GUILDS[v]), None
    if v in ("c", "colorless", "бесцветная", "бесцветный"):
        return [], None
    if v in ("m", "multicolor", "многоцветная", "многоцвет"):
        return None, "multi"
    if v in COLOR_WORDS:
        return [COLOR_WORDS[v]], None
    letters = [COLOR_WORDS.get(ch) for ch in v]
    if v and all(letters):
        return sorted(set(letters)), None
    return None, "bad"


def _color_clause(col, op: str, value: str, default_op: str, warnings: list) -> ColumnElement:
    want, special = _colors(value)
    if special == "multi":
        return func.jsonb_array_length(col) >= 2
    if special == "bad":
        warnings.append(f"Не понял цвет «{value}»: используйте буквы w u b r g, c (бесцветная) или m (многоцветная)")
        return true()
    op = default_op if op == ":" else op
    if want == []:       # бесцветная
        return func.coalesce(func.jsonb_array_length(col), 0) == 0
    if op in ("=",):
        return and_(col.contains(want), col.contained_by(want))
    if op == "!=":
        return not_(and_(col.contains(want), col.contained_by(want)))
    if op == "<=":
        return col.contained_by(want)
    if op == "<":
        return and_(col.contained_by(want), not_(col.contains(want)))
    if op == ">":
        return and_(col.contains(want), not_(col.contained_by(want)))
    return col.contains(want)   # >= и «:» для c - «содержит эти цвета»


def _like(text: str) -> str:
    return "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _term(t: _Tok, p: Parsed) -> ColumnElement | None:
    key = KEYS.get(t.key)
    v = (t.value or "").strip()
    op = t.op
    if key is None:
        p.warnings.append(f"Неизвестный параметр «{t.key}:» — он не учтён")
        return None
    if key in ("order", "dir", "game"):
        if key == "order":
            p.order = ORDERS.get(v.lower()) or p.order
        elif key == "dir":
            p.direction = "desc" if v.lower() in ("desc", "убыв") else "asc"
        else:
            p.game = {"magic": "mtg", "mtg": "mtg", "мтг": "mtg", "берсерк": "berserk"}.get(v.lower(), v.lower())
        return None
    if not v:
        p.warnings.append(f"Пустое значение у «{t.key}{op}»")
        return None
    lv = norm_name(v)
    if key == "name":
        return or_(Card.name_lower.contains(lv), Card.name_ru_lower.contains(lv))
    if key == "type":
        return or_(Card.type_line.ilike(_like(v)), Card.type_ru.ilike(_like(v)))
    if key == "oracle":
        return or_(Card.text.ilike(_like(v)), Card.text_ru.ilike(_like(v)))
    if key == "color":
        return _color_clause(Card.extra["colors"], op, v, ">=", p.warnings)
    if key == "identity":
        return _color_clause(Card.extra["color_identity"], op, v, "<=", p.warnings)
    if key in ("mv", "pow", "tou", "loy", "usd", "eur"):
        n = _num(v)
        if n is None:
            p.warnings.append(f"«{t.key}{op}{v}»: нужно число")
            return None
        col = {"mv": Card.cmc, "usd": Card.prices["usd"].as_float(), "eur": Card.prices["eur"].as_float(),
               "pow": _numeric_extra("power"), "tou": _numeric_extra("toughness"),
               "loy": _numeric_extra("loyalty")}[key]
        return _cmp(col, op, n)
    if key == "rarity":
        r = RARITY.get(v.lower())
        if r is None:
            p.warnings.append(f"Редкость «{v}»: common, uncommon, rare, mythic")
            return None
        names = {"<": RARITY_NAMES[:r], "<=": RARITY_NAMES[:r + 1], ">": RARITY_NAMES[r + 1:],
                 ">=": RARITY_NAMES[r:], "!=": [x for x in RARITY_NAMES if x != RARITY_NAMES[r]]}.get(op, [RARITY_NAMES[r]])
        return Card.rarity.in_(names) if names else false()
    if key == "set":   # карта есть в сете, если хоть одно её издание оттуда
        from .models import CardPrint
        return or_(func.lower(Card.set_code) == v.lower(),
                   Card.id.in_(select(CardPrint.card_id).where(CardPrint.set_code == v.lower())))
    if key in ("format", "banned", "restricted"):
        fmt = FORMATS.get(v.lower())
        if not fmt:
            p.warnings.append(f"Формат «{v}» не знаю: commander, standard, pioneer, modern, legacy, vintage, pauper")
            return None
        status = {"format": "legal", "banned": "banned", "restricted": "restricted"}[key]
        return Card.legalities[fmt].astext == status
    if key == "keyword":
        return func.lower(Card.extra["keywords"].astext).contains(v.lower())
    if key == "artist":
        return Card.extra["artist"].astext.ilike(_like(v))
    if key == "is":
        iv = v.lower()
        if iv in ("gamechanger", "gc", "геймченджер"):
            return Card.is_game_changer.is_(True)
        if iv in ("commander", "командир"):
            return or_(and_(Card.type_line.ilike("%legendary%"), Card.type_line.ilike("%creature%")),
                       Card.text.ilike("%can be your commander%"))
        if iv in ("dfc", "двусторонняя", "mdfc", "transform"):
            return func.jsonb_array_length(func.coalesce(Card.extra["faces"], func.jsonb("[]"))) > 1
        if iv in ("russian", "ru", "русская", "рус"):
            return Card.name_ru.is_not(None)
        if iv in ("vanilla", "ванильная"):
            return or_(Card.text.is_(None), Card.text == "")
        p.warnings.append(f"«is:{v}» не знаю: gamechanger, commander, dfc, russian, vanilla")
        return None
    return None


def _word(text: str) -> ColumnElement:
    if text == "*":          # «все карты» - удобно для просмотра игры целиком с фильтрами и сортировкой
        return true()
    lv = norm_name(text)
    return or_(Card.name_lower.contains(lv), Card.name_ru_lower.contains(lv))


def parse(q: str) -> Parsed:
    """Запрос -> условие WHERE + предупреждения о том, что не понято."""
    p = Parsed(where=true())
    toks = tokenize(q or "")
    pos = 0

    def atom():
        nonlocal pos
        t = toks[pos]
        pos += 1
        if t.kind == "(":
            inner = expr()
            if pos < len(toks) and toks[pos].kind == ")":
                pos += 1
            else:
                p.warnings.append("Не хватает закрывающей скобки")
            return inner
        if t.kind == "term":
            c = _term(t, p)
        elif t.kind == "exact":
            v = norm_name(t.value)     # двусторонние - и по лицевой стороне: !"Malakir Rebirth"
            c = or_(Card.name_lower == v, Card.name_ru_lower == v, Card.name_front == v, Card.name_ru_front == v)
        else:
            c = _word(t.value)
            if not t.neg and t.value != "*":
                p.words.append(t.value)
        if c is None:
            return None
        # NULL (нет русского типа, нет цен) - «не подходит»: иначе NOT NULL выкинул бы карту и из отрицания
        return not_(func.coalesce(c, false())) if t.neg else c

    def conj():
        nonlocal pos
        parts = []
        while pos < len(toks) and toks[pos].kind not in ("or", ")"):
            c = atom()
            if c is not None:
                parts.append(c)
        return and_(*parts) if parts else None

    def expr():
        nonlocal pos
        alts = [conj()]
        while pos < len(toks) and toks[pos].kind == "or":
            pos += 1
            alts.append(conj())
        alts = [a for a in alts if a is not None]
        if not alts:
            return None
        return alts[0] if len(alts) == 1 else or_(*alts)

    while pos < len(toks):
        if toks[pos].kind == ")":
            p.warnings.append("Лишняя закрывающая скобка")
            pos += 1
            continue
        c = expr()
        if c is not None:
            p.where = and_(p.where, c)
    return p


def relevance(words: list[str]) -> list:
    """Для поиска по названию: точное совпадение, затем «начинается с», затем остальное (по алфавиту дальше)."""
    if not words:
        return []
    phrase = norm_name(" ".join(words))
    exact = or_(Card.name_lower == phrase, Card.name_front == phrase, Card.name_ru_lower == phrase,
                Card.name_ru_front == phrase)
    prefix = or_(Card.name_lower.startswith(phrase), Card.name_ru_lower.startswith(phrase))
    return [case((exact, 0), (prefix, 1), else_=2)]


def order_by(order: str | None, direction: str | None) -> list:
    desc = direction == "desc"
    col = {"mv": Card.cmc, "rarity": case({n: i for i, n in enumerate(RARITY_NAMES)}, value=Card.rarity, else_=9),
           "usd": Card.prices["usd"].as_float(), "eur": Card.prices["eur"].as_float(), "set": Card.set_code,
           "pow": _numeric_extra("power"), "tou": _numeric_extra("toughness"),
           "color": func.jsonb_array_length(func.coalesce(Card.extra["colors"], func.jsonb("[]")))}.get(order or "name")
    if col is None:
        return [Card.name_lower.desc() if desc else Card.name_lower]
    return [(col.desc().nulls_last() if desc else col.asc().nulls_last()), Card.name_lower]
