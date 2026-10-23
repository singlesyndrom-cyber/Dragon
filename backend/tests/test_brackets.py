"""Оценка брекета Commander по карточкам (без базы)."""
from app.brackets import assess, mismatch


def card(name, text="", gc=False):
    return (name, text, gc)


def test_clean_deck_is_1_2():
    a = assess([card("Sol Ring", "{T}: Add {C}{C}."), card("Llanowar Elves", "{T}: Add {G}.")])
    assert a["min_bracket"] == 1 and a["label"] == "1–2" and not a["reasons"]
    assert mismatch(1, a) is None and mismatch(2, a) is None


def test_game_changers_count():
    three = assess([card(n, gc=True) for n in ("Rhystic Study", "Cyclonic Rift", "Smothering Tithe")])
    assert three["min_bracket"] == 3 and mismatch(3, three) is None and "не ниже 3" in mismatch(2, three)
    four = assess([card(n, gc=True) for n in ("Rhystic Study", "Cyclonic Rift", "Smothering Tithe", "Demonic Tutor")])
    assert four["min_bracket"] == 4 and four["label"] == "4+"


def test_mass_land_denial_by_name_and_text():
    assert assess([card("Armageddon")])["mld"] == ["Armageddon"]
    a = assess([card("Some New Card", "Destroy all lands. Each player gains 3 life.")])
    assert a["min_bracket"] == 4 and a["mld"] == ["Some New Card"]
    assert assess([card("Strip Mine", "{T}, Sacrifice Strip Mine: Destroy target land.")])["mld"] == []


def test_extra_turns_and_chaining():
    one = assess([card("Time Warp", "Target player takes an extra turn after this one.")])
    assert one["min_bracket"] == 2 and "не ниже 2" in mismatch(1, one) and mismatch(2, one) is None
    many = assess([card(n, "Take an extra turn after this one.") for n in ("Time Warp", "Temporal Manipulation", "Capture of Jingzhou")])
    assert many["min_bracket"] == 4


def test_two_card_combos():
    a = assess([card("Thassa's Oracle", gc=True), card("Demonic Consultation")])
    assert a["combos"] == [["Demonic Consultation", "Thassa's Oracle"]] and a["min_bracket"] == 3
    assert assess([card("Thassa's Oracle", gc=True)])["combos"] == []
    # двусторонние: совпадение по лицевой стороне
    assert assess([card("Boom // Bust")])["mld"] == ["Boom // Bust"]
