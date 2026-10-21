"""Тексты сообщений для Telegram (HTML). Чистая логика без БД и без aiogram."""
import html
import random
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

GAME_LABELS = {"mtg": "Magic: The Gathering", "berserk": "Берсерк"}
FORMAT_LABELS = {"swiss": "Швейцарская система", "fast_swiss": "Быстрый швейцарец",
                 "edh": "EDH — банк с нулевой суммой"}
MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}
TG_LIMIT = 4000  # запас до лимита Telegram в 4096

# Шаблоны нейтральны по роду и падежу: ник стоит только в именительном (подлежащее или после тире),
# потому что ники не склоняются - «у Света», «за Вера» звучали бы с ошибкой.
WINNER_TEMPLATES = [
    "🥇 Сегодня побеждает <b>{name}</b>! Безупречная игра и заслуженное первое место. Поздравляем!",
    "👑 Корона вечера — <b>{name}</b>! Первое место и всеобщее уважение за столом. Браво!",
    "🏆 Сегодня никто не смог остановить игрока <b>{name}</b>. Первое место — поздравляем с победой!",
    "🎉 Золото — <b>{name}</b>! Холодная голова, точные решения и капля удачи. Поздравляем!",
    "🔥 Первое место — <b>{name}</b>! Блестящий турнир и главный приз вечера. Официально поздравляем!",
    "⭐ Чемпион этого вечера — <b>{name}</b>. Отличная игра от первого хода до последнего. Поздравляем!",
]
PODIUM_TEMPLATES = [
    "{medal} <b>{name}</b> — {place}-е место. Сильный результат, поздравляем!",
    "{medal} На {place}-м месте <b>{name}</b>. Отличная игра и заслуженный пьедестал!",
    "{medal} {place}-е место — <b>{name}</b>. Так держать!",
    "{medal} Пьедестал покорён: <b>{name}</b> с {place}-м местом. Поздравляем!",
    "{medal} <b>{name}</b> — {place}-е место и заслуженные аплодисменты!",
    "{medal} Достойный результат: <b>{name}</b>, {place}-е место. Поздравляем!",
]


def esc(s) -> str:
    return html.escape(str(s), quote=False)


def fmt_dt(dt: datetime | None, tz: str) -> str:
    if dt is None:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(tz))
    return dt.astimezone(ZoneInfo(tz)).strftime("%d.%m.%Y %H:%M")


def congratulations(podium: list[tuple[int, str]], rng: random.Random | None = None) -> list[str]:
    """podium: [(место, ник), ...]. Для 2-го и 3-го места шаблоны не повторяются."""
    rng = rng or random.Random()
    lines = []
    first = [p for p in podium if p[0] == 1]
    rest = [p for p in podium if p[0] in (2, 3)]
    if first:
        lines.append(rng.choice(WINNER_TEMPLATES).format(name=esc(first[0][1])))
    for tpl, (place, name) in zip(rng.sample(PODIUM_TEMPLATES, k=len(rest)), rest):
        lines.append(tpl.format(medal=MEDALS[place], place=place, name=esc(name)))
    return lines


def format_announce(name: str, club: str, game: str, fmt: str, starts_at: datetime | None, tz: str,
                    url: str | None, rounds: int | None = None) -> str:
    lines = ["🗓 <b>Анонс турнира</b>", f"<b>{esc(name)}</b>", "",
             f"🏠 Клуб: {esc(club)}", f"🎴 Игра: {esc(GAME_LABELS.get(game, game))}",
             f"⚙️ Формат: {esc(FORMAT_LABELS.get(fmt, fmt))}"]
    if fmt == "edh":
        lines.append("⏱ Партия — 70 минут, рассадка случайная внутри брекетов")
    if rounds:
        lines.append(f"🔁 Туров: {rounds}")
    lines.append(f"📅 Начало: {fmt_dt(starts_at, tz)}")
    if url:
        lines += ["", f'📝 <a href="{esc(url)}">Регистрация и подробности</a>']
    return "\n".join(lines)


def format_article(title: str, summary: str, url: str | None, club: str | None) -> str:
    lines = [f"📰 <b>{esc(title)}</b>"]
    if club:
        lines.append(f"<i>{esc(club)}</i>")
    if summary:
        lines += ["", esc(summary[:600])]
    if url:
        lines += ["", f'👉 <a href="{esc(url)}">Читать полностью</a>']
    return "\n".join(lines)


@dataclass
class ReportData:
    title: str
    club: str
    game: str
    fmt: str
    date: datetime | None
    participants: int
    rounds: int | None
    podium: list[tuple[int, str]]
    standings: list[tuple[int, str, str]]        # место, ник, значение («9 оч.» / «+245»)
    league_title: str
    league: list[tuple[int, str, str]]
    stats: list[str] = field(default_factory=list)
    url: str | None = None
    tz: str = "Europe/Moscow"
    judge: str | None = None                      # «Алексей (№1007)» - главный судья


def _table(rows: list[tuple[int, str, str]], limit: int) -> list[str]:
    return [f"{p}. {esc(n)} — {esc(v)}" for p, n, v in rows[:limit]]


def format_report(d: ReportData, rng: random.Random | None = None) -> str:
    congrats = congratulations(d.podium, rng)   # выбираем фразы один раз, до сокращений
    for limit in (15, 10, 5, 3, 0):
        head = [f"🏆 <b>Итоги турнира «{esc(d.title)}»</b>",
                f"{esc(d.club)} · {esc(FORMAT_LABELS.get(d.fmt, d.fmt))} · {esc(GAME_LABELS.get(d.game, d.game))}",
                f"📅 {fmt_dt(d.date, d.tz)} · 👥 Участников: {d.participants}"
                + (f" · Туров: {d.rounds}" if d.rounds else "")]
        if d.judge:
            head.append(f"⚖️ Судья: {esc(d.judge)}")
        parts = ["\n".join(head)]
        if congrats:
            parts.append("\n".join(congrats))
        if limit and d.standings:
            parts.append("\n".join(["📊 <b>Итоговая таблица</b>"] + _table(d.standings, limit)))
        if d.stats:
            parts.append("\n".join(["📈 <b>Статистика турнира</b>"] + [esc(s) for s in d.stats]))
        if limit and d.league:
            parts.append("\n".join([f"🏅 <b>{esc(d.league_title)}</b>"] + _table(d.league, min(limit, 10))))
        if d.url:
            parts.append(f'🔗 <a href="{esc(d.url)}">Подробности на сайте</a>')
        text = "\n\n".join(parts)
        if len(text) <= TG_LIMIT:
            break
    return text
