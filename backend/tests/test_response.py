"""ККИ «Респонс»: разбор выгрузки API и правила колоды (без базы)."""
import json
from pathlib import Path
from types import SimpleNamespace

from app import deckrules
from app.response import parse_payload, to_card

PAGE = json.loads((Path(__file__).parent / "fixtures" / "response_page1.json").read_text(encoding="utf-8"))


def test_parse_page():
    cards, meta = parse_payload(PAGE)
    assert len(cards) == 50 and meta["total"] == 427 and meta["last_page"] == 9
    by = {c["name"]: c for c in cards}
    adept = by["Адепт раздора"]
    assert adept["game"] == "response" and adept["external_id"] == "adept-razdora"
    assert adept["type_line"] == "Юнит — Эльф, Маг" and adept["cmc"] == 1 and adept["rarity"] == "Бронза"
    assert adept["set_name"] == "Королевства Ванстера" and adept["set_code"] == "kov"
    assert adept["image_url"].startswith("https://response-league.ru/api/v1/card-images/")
    assert adept["extra"]["factions"] == ["Хаос"] and adept["extra"]["strength"] == 1 and adept["extra"]["rulings"]
    hero = by["Аск’Азан, Нетленный"]
    assert hero["extra"]["hero"] and hero["extra"]["levels"][0]["influence"] == 4
    assert hero["text"].startswith("Уровень 1 (влияние 4):") and hero["cmc"] is None
    assert by["Аннигиляция"]["extra"]["order"] and by["Аннигиляция"]["type_line"] == "Приказ Заклинание"
    assert by["Детектив Юрген"]["extra"]["legendary"]
    # несколько страниц списком и битые записи
    many, _ = parse_payload([PAGE, {"data": [{"id": "", "name": "x"}, "мусор"], "meta": {}}])
    assert len(many) == 50
    assert to_card({"id": "x"}) is None


def entries(spec):
    """spec: [(qty, name, section, extra)] -> строки колоды с «картами» из базы."""
    return [deckrules.Entry(n, q, sec, SimpleNamespace(extra=ex, name=n) if ex is not None else None)
            for q, n, sec, ex in spec]


HERO = {"hero": True, "factions": ["Технологии", "Хаос"]}
ORDER = {"order": True, "factions": ["Хаос"]}
CHAOS = {"factions": ["Хаос"]}


def legal_deck():
    spec = [(1, "Азарион", "commander", HERO)] + [(1, f"Приказ {i}", "orders", ORDER) for i in range(5)]
    return spec + [(2, f"Карта {i}", "main", CHAOS) for i in range(15)]


def test_legal_duel_deck():
    assert deckrules.check(entries(legal_deck()), "response") == []


def test_duel_rules():
    spec = legal_deck()
    spec[1] = (2, "Приказ 0", "orders", ORDER)                                   # одинаковые приказы
    spec += [(1, "Природная", "main", {"factions": ["Природа"]}),                # не той фракции
             (2, "Легенда", "side", {"factions": ["Хаос"], "legendary": True}),  # легендарная ×2
             (1, "Карта 0", "side", CHAOS),                                       # третья копия через доп. колоду
             (1, "Мульти", "main", {"factions": ["Хаос", "Технологии", "Жизнь"]})]  # герой ⊂ карта - можно
    text = " | ".join(p["text"] for p in deckrules.check(entries(spec), "response"))
    assert "Приказов 6, нужно 5" in text and "Приказы должны быть разными" in text
    assert "нужно ровно 30" in text
    assert "Природная" in text and "Мульти" not in text.split("фракциям")[1]
    assert "Легенда ×2" in text and "Карта 0 ×3" in text


def test_hero_and_orders_required_and_limited_has_no_copy_limit():
    spec = [(4, "Карта", "main", CHAOS)] * 1 + [(26, "Другая", "main", {"factions": ["Природа"]})]
    text = " | ".join(p["text"] for p in deckrules.check(entries(spec), "response_limited"))
    assert "Не выбран герой" in text and "Приказов 0" in text and "копий" not in text and "фракциям" not in text
    heroes_in_main = [(1, "Азарион", "main", HERO)]
    assert any("Герои и приказы не кладутся" in p["text"] for p in deckrules.check(entries(heroes_in_main), "response"))
