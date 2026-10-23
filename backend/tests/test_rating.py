"""Рейтинг силы: формулы Glicko-2 и защита от накрутки (без базы)."""
from datetime import datetime, timedelta, timezone

import pytest

from app.rating import (PAIR_CAP, START_RD, Event, compute, discipline, glicko2, idle_rd)

T0 = datetime(2026, 10, 1, 18, tzinfo=timezone.utc)


def test_glickman_example():
    # пример из статьи Glickman «Example of the Glicko-2 system»: 1464.06, 151.52, 0.05999
    r, rd, vol = glicko2(1500, 200, 0.06, [(1400, 30, 1), (1550, 100, 0), (1700, 300, 0)])
    assert r == pytest.approx(1464.06, abs=0.05)
    assert rd == pytest.approx(151.52, abs=0.05)
    assert vol == pytest.approx(0.05999, abs=1e-5)


def test_idle_rd_grows_but_capped():
    assert idle_rd(60, 0.06, 0) == 60
    assert idle_rd(60, 0.06, 52) > idle_rd(60, 0.06, 4) > 60
    assert idle_rd(300, 0.06, 10_000) == START_RD


def test_disciplines():
    assert discipline("mtg", "edh", None) == "mtg_edh"
    assert discipline("mtg", "swiss", {"config": {}}) == "mtg_draft"
    assert discipline("mtg", "swiss", None) == "mtg_constructed"
    assert discipline("berserk", "fast_swiss", None) == "berserk_constructed"
    assert discipline("berserk", "swiss", {"config": {}}) == "berserk_draft"


def swiss(eid, at, tier="club", players=(1, 2, 3, 4)):
    """Два стола: 1 бьёт 2, 3 бьёт 4."""
    a, b, c, d = players
    return Event(eid, "berserk_constructed", at, tier, [(a, b, 1.0), (c, d, 1.0)])


def test_winner_goes_up_and_small_events_skipped():
    res = compute([swiss(1, T0), Event(2, "berserk_constructed", T0 + timedelta(days=1), "club", [(1, 2, 1.0), (2, 3, 0.5)])])
    p = res.players
    assert p[(1, "berserk_constructed")].rating > 1500 > p[(2, "berserk_constructed")].rating
    assert 2 in res.skipped and 1 not in res.skipped              # три игрока - не рейтинговый
    assert p[(1, "berserk_constructed")].games == 1               # пропущенный турнир партий не добавил


def test_pair_cap_against_farming():
    # одни и те же четверо играют каждую неделю: после PAIR_CAP встреч за 30 дней пары не засчитываются
    events = [swiss(i, T0 + timedelta(days=7 * i)) for i in range(PAIR_CAP + 1)]
    res = compute(events)
    last = [c for c in res.changes if c["tournament_id"] == PAIR_CAP]
    assert not last and PAIR_CAP in res.skipped                   # все пары исчерпали лимит - турнир не учтён
    # через 30 дней лимит освобождается
    later = compute(events[:PAIR_CAP] + [swiss(99, T0 + timedelta(days=7 * (PAIR_CAP - 1) + 31))])
    assert 99 not in later.skipped


def test_pair_cap_not_applied_to_championships():
    events = [swiss(i, T0 + timedelta(days=i), tier="regional") for i in range(PAIR_CAP + 2)]
    res = compute(events)
    assert not res.skipped and res.players[(1, "berserk_constructed")].games == PAIR_CAP + 2


def test_disciplines_are_separate():
    a = swiss(1, T0)
    b = Event(2, "berserk_draft", T0 + timedelta(days=1), "club", [(2, 1, 1.0), (4, 3, 1.0)])
    p = compute([a, b]).players
    assert p[(1, "berserk_constructed")].rating > 1500 and p[(1, "berserk_draft")].rating < 1500
