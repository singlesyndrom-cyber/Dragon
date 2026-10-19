from app.swiss import MatchRec, compute_standings, default_rounds, pair_round


def mk(n):
    return {i: (float(100 - i), i) for i in range(1, n + 1)}  # id -> (club_rating, seed)


def test_round1_even():
    pairs = pair_round(mk(8), [])
    assert len(pairs) == 4 and all(b is not None for _, b in pairs)
    assert sorted(x for p in pairs for x in p) == list(range(1, 9))


def test_round1_odd_has_one_bye():
    pairs = pair_round(mk(7), [])
    assert sum(1 for _, b in pairs if b is None) == 1


def test_no_rematch_and_unique_bye():
    players = mk(5)
    matches = []
    seen = set()
    byes = set()
    for rnd in range(3):
        pairs = pair_round(players, matches)
        for a, b in pairs:
            if b is None:
                assert a not in byes
                byes.add(a)
                matches.append(MatchRec(a, None, None))
            else:
                assert frozenset((a, b)) not in seen
                seen.add(frozenset((a, b)))
                matches.append(MatchRec(a, b, "p1"))


def test_points_and_tiebreak_by_club_rating_after_one_round():
    players = {1: (10.0, 1), 2: (50.0, 2), 3: (30.0, 3), 4: (20.0, 4)}
    ms = [MatchRec(1, 2, "p1"), MatchRec(3, 4, "p1")]
    st = compute_standings(players, ms)
    # у 1 и 3 по 3 очка; OWP/Buchholz у 1 и 3 равны по нулю очков соперников,
    # у 1 соперник с рейтингом 50, но решает именно club_rating игрока: у 3 он выше
    assert [r.player_id for r in st][:2] == [3, 1]
    assert st[0].points == 3 and st[2].points == 0


def test_draw_and_bye_scoring():
    players = {1: (0.0, 1), 2: (0.0, 2), 3: (0.0, 3)}
    st = compute_standings(players, [MatchRec(1, 2, "draw"), MatchRec(3, None, None)])
    pts = {r.player_id: r.points for r in st}
    assert pts == {1: 1, 2: 1, 3: 3}


def test_default_rounds():
    assert [default_rounds(n) for n in (2, 3, 8, 9, 16)] == [1, 2, 3, 4, 4]
