import random

from app.edh import seat, settle, table_sizes


def test_win_moves_money_and_conserves_total():
    banks = {1: 1000.0, 2: 1000.0, 3: 500.0, 4: 2000.0}
    d = settle(banks, winner=1)
    assert d[2] == -70 and d[3] == -35 and d[4] == -140
    assert d[1] == 245
    assert abs(sum(d.values())) < 1e-9


def test_draw_burns_7_percent_each():
    d = settle({1: 1000.0, 2: 1000.0, 3: 100.0, 4: 1000.0}, winner=None)
    assert d == {1: -70, 2: -70, 3: -7, 4: -70}


def test_three_and_five_player_tables():
    d3 = settle({1: 1000.0, 2: 1000.0, 3: 1000.0}, winner=2)
    assert d3[2] == 140 and d3[1] == d3[3] == -70
    d5 = settle({i: 1000.0 for i in range(5)}, winner=0)
    assert d5[0] == 280


def test_table_sizes():
    for n in range(3, 60):
        s = table_sizes(n)
        assert sum(s) == n and all(3 <= x <= 5 for x in s)


def test_seat_everyone_once_and_brackets_separate():
    players = [(i, 2) for i in range(8)] + [(100 + i, 4) for i in range(4)]
    tables = seat(players, random.Random(1))
    ids = [u for _, t in tables for u in t]
    assert sorted(ids) == sorted(u for u, _ in players)
    for br, t in tables:
        assert len({0 if u < 100 else 1 for u in t}) == 1  # брекеты не смешаны


def test_small_bracket_merges_to_nearest():
    players = [(1, 1), (2, 1)] + [(10 + i, 2) for i in range(4)]
    tables = seat(players, random.Random(2))
    assert sorted(u for _, t in tables for u in t) == sorted(u for u, _ in players)
    assert all(3 <= len(t) <= 5 for _, t in tables)


def test_random_seating_varies():
    players = [(i, 3) for i in range(8)]
    seen = {tuple(map(tuple, (t for _, t in seat(players, random.Random(s))))) for s in range(10)}
    assert len(seen) > 1
