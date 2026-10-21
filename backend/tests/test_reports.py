import random
from datetime import datetime, timezone

from app.botutil import MAX_ATTEMPTS, backoff_seconds, parse_chat_id
from app.reports import (PODIUM_TEMPLATES, WINNER_TEMPLATES, ReportData, congratulations, format_announce,
                         format_article, format_report)


def data(n=3, **kw):
    names = [f"Игрок{i}" for i in range(1, n + 1)]
    base = dict(title="Пятничный EDH", club="Клуб <Тест>", game="mtg", fmt="edh",
                date=datetime(2026, 10, 23, 15, 0, tzinfo=timezone.utc), participants=n, rounds=2,
                podium=[(i + 1, names[i]) for i in range(min(3, n))],
                standings=[(i + 1, names[i], f"+{100 - i}") for i in range(n)],
                league_title="Банк клуба", league=[(i + 1, names[i], "1000") for i in range(n)],
                stats=["Сыграно столов: 4"], url="https://x.test/t/1")
    base.update(kw)
    return ReportData(**base)


def test_template_counts():
    assert len(WINNER_TEMPLATES) >= 5 and len(PODIUM_TEMPLATES) >= 5


def test_congrats_places_and_distinct_podium_templates():
    for seed in range(30):
        lines = congratulations([(1, "A"), (2, "B"), (3, "C")], random.Random(seed))
        assert len(lines) == 3 and "A" in lines[0] and "🥈" in lines[1] and "🥉" in lines[2]
        assert lines[1].replace("B", "").replace("🥈", "") != lines[2].replace("C", "").replace("🥉", "")


def test_congrats_two_players_and_empty():
    assert len(congratulations([(1, "A"), (2, "B")])) == 2
    assert congratulations([]) == []


def test_variety_across_seeds():
    assert len({congratulations([(1, "A")], random.Random(s))[0] for s in range(40)}) >= 4


def test_report_escapes_html_in_names_and_club():
    text = format_report(data(podium=[(1, "<script>x</script>")],
                              standings=[(1, "<b>&", "1")]), random.Random(1))
    assert "<script>" not in text and "&lt;script&gt;" in text and "Клуб &lt;Тест&gt;" in text


def test_report_fits_telegram_limit_with_huge_tables():
    text = format_report(data(n=200), random.Random(1))
    assert len(text) <= 4000 and text.count("<b>") == text.count("</b>")


def test_report_contains_sections():
    text = format_report(data(), random.Random(1))
    for part in ("Итоги турнира", "Итоговая таблица", "Статистика турнира", "Банк клуба", "23.10.2026"):
        assert part in text


def test_announce_and_article():
    a = format_announce("Кубок", "Клуб", "berserk", "fast_swiss", None, "Europe/Moscow", "https://x.test/t/2", 1)
    assert "Берсерк" in a and "Быстрый швейцарец" in a and "https://x.test/t/2" in a
    assert "70 минут" in format_announce("E", "C", "mtg", "edh", None, "Europe/Moscow", None)
    art = format_article("Заголовок <1>", "Кратко", "https://x.test/n/a", None)
    assert "&lt;1&gt;" in art and "Читать полностью" in art


def test_backoff_and_chat_id():
    assert [backoff_seconds(i) for i in (1, 2, 3)] == [30, 60, 120]
    assert backoff_seconds(20) == 3600 and MAX_ATTEMPTS == 8
    assert parse_chat_id(" -1001234567890 ") == -1001234567890 and parse_chat_id("@club") == "@club"


def test_templates_keep_nickname_in_nominative():
    """Ники не склоняются: шаблон не должен ставить ник после предлога или как дополнение («у Света»)."""
    import re
    bad = re.compile(r"(?:^|\s)(?:у|за|для|от|с|к|о|об|остановить|поздравляем)\s+<b>\{name\}", re.IGNORECASE)
    for tpl in WINNER_TEMPLATES + PODIUM_TEMPLATES:
        assert not bad.search(tpl), tpl
