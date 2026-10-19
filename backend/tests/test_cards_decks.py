from app.cardimport import extract_rows, normalize_generic, normalize_scryfall, norm_name
from app.decklist import apply_commander, parse_decklist, validate_edh

MOX = """Commander
1 Atraxa, Praetors' Voice

Deck
1 Sol Ring (CMM) 400
1x Arcane Signet [Ramp]
1 Lightning Bolt (LTR) 12 *F*
37 Forest

Sideboard
1 Swords to Plowshares
"""


def test_parse_sections_and_cleanup():
    cards, errs = parse_decklist(MOX)
    by = {c.name: c for c in cards}
    assert not errs
    assert by["Atraxa, Praetors' Voice"].is_commander
    assert {"Sol Ring", "Arcane Signet", "Lightning Bolt", "Forest"} <= set(by)
    assert by["Forest"].qty == 37 and by["Swords to Plowshares"].section == "side"


def test_no_headers_and_commander_param():
    cards, _ = parse_decklist("1 Sol Ring\n2 Island\nCommand Tower")
    assert [(c.name, c.qty) for c in cards] == [("Sol Ring", 1), ("Island", 2), ("Command Tower", 1)]
    cards = apply_commander(cards, "Sol Ring")
    assert cards[0].is_commander


def test_validate_edh():
    cards, _ = parse_decklist(MOX)
    w = " ".join(validate_edh(cards))
    assert "41 карт" in w  # 1+1+1+1+37 = 41 (сайдборд не считается)
    cards2, _ = parse_decklist("Commander\n1 A\nDeck\n1 B\n1 B\n97 Forest")
    assert "singleton" in " ".join(validate_edh(cards2)) and "Командир не указан" not in validate_edh(cards2)


def test_generic_russian_fields_and_extra():
    row = {"Название": "Огненный дракон", "Сет": "Начало", "Тип": "Существо", "Цена": 5,
           "Текст": ["Полёт", "Удар"], "Картинка": "http://x/1.jpg", "Сила": 6}
    c = normalize_generic(row)
    assert c["name"] == "Огненный дракон" and c["game"] == "berserk"
    assert c["mana_cost"] == "5" and c["text"] == "Полёт\nУдар" and c["image_url"].endswith("1.jpg")
    assert c["extra"] == {"Сила": 6} and len(c["external_id"]) == 40


def test_generic_mapping_override_and_missing_name():
    c = normalize_generic({"foo": "Карта", "bar": "Редкая"}, {"name": "foo", "rarity": "bar"})
    assert c["name"] == "Карта" and c["rarity"] == "Редкая"
    assert normalize_generic({"x": 1}) is None


def test_extract_rows():
    assert extract_rows([{"a": 1}, 5]) == [{"a": 1}]
    assert extract_rows({"cards": [{"a": 1}]}) == [{"a": 1}]
    assert extract_rows({"x": 1}) == []


def test_scryfall_dfc_and_filters():
    obj = {"oracle_id": "abc", "name": "Delver of Secrets // Insectile Aberration", "layout": "transform",
           "card_faces": [{"oracle_text": "Upkeep", "mana_cost": "{U}", "type_line": "Creature",
                           "image_uris": {"normal": "http://img"}}, {"oracle_text": "Flying"}],
           "cmc": 1.0, "legalities": {"commander": "legal"}, "set": "mid", "rarity": "common",
           "game_changer": False}
    c = normalize_scryfall(obj)
    assert c["image_url"] == "http://img" and c["mana_cost"] == "{U}" and c["commander_legal"] is True
    assert c["name_front"] == "delver of secrets" and "Flying" in c["text"]
    assert normalize_scryfall({"oracle_id": "t", "name": "Token", "layout": "token"}) is None
    assert norm_name("  Atraxa’s   Hold ") == "atraxa's hold"
