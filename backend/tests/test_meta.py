from app.meta import Game, build_entry, card_usage, commander_stats


def entry(i, cmd, cards):
    rows = [(cmd, True, "commander")] if cmd else []
    rows += [(c, False, "main") for c in cards]
    return build_entry(i, rows)


def test_build_entry_excludes_basics_side_and_commander():
    e = build_entry(1, [("Atraxa", True, "commander"), ("Sol Ring", False, "main"), ("Forest", False, "main"),
                        ("Snow-Covered Island", False, "main"), ("Swords", False, "side")])
    assert e.commander == "Atraxa" and list(e.cards.values()) == ["Sol Ring"]


def test_partner_commanders_key_is_order_independent():
    a = build_entry(1, [("Thrasios", True, "commander"), ("Tymna", True, "commander")])
    b = build_entry(2, [("Tymna", True, "commander"), ("Thrasios", True, "commander")])
    assert a.commander == b.commander == "Thrasios / Tymna"


def test_commander_stats_rates_and_edge():
    es = [entry(1, "Atraxa", []), entry(2, "Atraxa", []), entry(3, "Krenko", [])]
    gs = [Game(1, "win", 0.25), Game(1, "loss", 0.25), Game(2, "draw", 0.25), Game(2, "loss", 0.25),
          Game(3, "win", 0.25), Game(3, "win", 0.25)]
    r = {x["commander"]: x for x in commander_stats(es, gs, min_games=3)}
    a, k = r["Atraxa"], r["Krenko"]
    assert a["decks"] == 2 and abs(a["pick_rate"] - 0.6667) < 1e-4
    assert a["games"] == 4 and a["wins"] == 1 and a["draws"] == 1 and a["losses"] == 2
    assert a["win_rate"] == 0.25 and a["edge"] == 0.0 and a["reliable"] is True
    assert k["win_rate"] == 1.0 and k["edge"] == 0.75 and k["reliable"] is False


def test_no_games_gives_none_not_zero():
    r = commander_stats([entry(1, "Atraxa", [])], [])[0]
    assert r["win_rate"] is None and r["edge"] is None and r["games"] == 0


def test_card_usage_global_and_per_commander():
    es = [entry(1, "A", ["Sol Ring", "Swords"]), entry(2, "A", ["Sol Ring"]), entry(3, "B", ["Sol Ring", "Bolt"])]
    g = card_usage(es)
    assert g["decks_in_scope"] == 3 and g["cards"][0] == {"card": "Sol Ring", "decks": 3, "usage_pct": 100.0}
    a = card_usage(es, commander="a")
    assert a["decks_in_scope"] == 2
    assert {c["card"]: c["usage_pct"] for c in a["cards"]} == {"Sol Ring": 100.0, "Swords": 50.0}
    assert [c["card"] for c in card_usage(es, min_decks=2)["cards"]] == ["Sol Ring"]
