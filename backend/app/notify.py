"""Производители событий: кладут сообщения в очередь outbox в текущей транзакции (без коммита).
Отправкой занимается отдельный процесс бота (app/bot)."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from .config import settings
from .models import (Article, Club, ClubMember, EdhSeat, EdhTable, EdhTableStatus, Match, OutboxMessage,
                     OutboxStatus, Tournament, TournamentFormat, TournamentPlayer, TournamentStatus, User)
from .reports import ReportData, esc, format_announce, format_article, format_report


def site_url(path: str) -> str | None:
    base = settings.public_base_url.rstrip("/")
    return f"{base}{path}" if base else None


async def enqueue(session, kind: str, chat_id: str | int | None, text: str, photo_url: str | None = None,
                  dedup_key: str | None = None, buttons: list | None = None, channel: str = "tg") -> None:
    if not chat_id:
        return
    stmt = pg_insert(OutboxMessage).values(
        kind=kind, channel=channel, chat_id=str(chat_id), text=text, photo_url=photo_url, parse_mode="HTML", buttons=buttons,
        status=OutboxStatus.pending, attempts=0, next_attempt_at=datetime.now(timezone.utc), dedup_key=dedup_key)
    if dedup_key:
        stmt = stmt.on_conflict_do_nothing(index_elements=[OutboxMessage.dedup_key])
    await session.execute(stmt)


async def club_vk(session, club_id: int):
    from .models import ClubVk
    cfg = await session.get(ClubVk, club_id)
    return cfg if cfg and cfg.group_id else None


async def broadcast(session, club: Club, kind: str, text: str, dedup: str, buttons: list | None = None,
                    photo_url: str | None = None, link: str | None = None) -> int:
    """Сообщение клуба во все его каналы: чат Telegram, беседа VK, стена сообщества VK. Возвращает число каналов."""
    n = 0
    if club.telegram_chat_id:
        await enqueue(session, kind, club.telegram_chat_id, text, photo_url=photo_url, buttons=buttons,
                      dedup_key=f"{dedup}:{club.telegram_chat_id}")
        n += 1
    cfg = await club_vk(session, club.id)
    if cfg and cfg.group_token and cfg.peer_id and cfg.chat_enabled:
        await enqueue(session, kind, f"{club.id}:{cfg.peer_id}", text, buttons=buttons, channel="vk",
                      dedup_key=f"{dedup}:vk:{cfg.peer_id}")
        n += 1
    if cfg and cfg.wall_enabled and cfg.wall_token:
        # на стене кнопок нет: ссылка на сайт - вложением (VK покажет карточку)
        await enqueue(session, kind, str(club.id), text, photo_url=link, channel="vkwall",
                      dedup_key=f"{dedup}:vkwall:{cfg.group_id}")
        n += 1
    return n


ANNOUNCE_AHEAD = timedelta(days=7)   # анонс в чат - не раньше чем за неделю до турнира


async def on_tournament_created(session, t: Tournament) -> None:
    """Анонс сразу, если турнир в ближайшую неделю (или без даты); дальние анонсирует announce_due."""
    from . import leagues   # единые часы платформы (тесты сезона их подменяют)
    starts = t.starts_at if t.starts_at.tzinfo else t.starts_at.replace(tzinfo=timezone.utc)
    if starts - leagues.now() > ANNOUNCE_AHEAD:
        return
    await announce(session, t)


async def announce(session, t: Tournament) -> bool:
    club = await session.get(Club, t.club_id)
    if not club:
        return False
    url = site_url(f"/tournaments/{t.id}")
    text = format_announce(t.name, club.name, t.game, t.format.value, t.starts_at, settings.app_timezone,
                           url, t.rounds_total)
    if not await broadcast(session, club, "tournament_announce", text, f"t-announce:{t.id}",
                           buttons=announce_buttons(t), link=url):
        return False
    t.announced = True
    return True


def announce_buttons(t: Tournament) -> list | None:
    """Кнопки под анонсом: запись прямо из Telegram (если разрешена самозапись) и ссылка на сайт."""
    rows = []
    if t.self_registration:
        rows.append([{"text": "✅ Записаться", "callback_data": f"reg:{t.id}"}])
    url = site_url(f"/tournaments/{t.id}")
    if url and url.startswith("https://"):
        rows.append([{"text": "Подробнее на сайте", "url": url}])
    return rows or None


async def announce_due(session) -> int:
    """Анонсировать турниры, до которых осталось меньше недели и которые ещё не анонсированы (серии)."""
    from . import leagues
    now = leagues.now()
    due = (await session.execute(select(Tournament).where(
        Tournament.announced.is_(False), Tournament.status == TournamentStatus.registration,
        Tournament.starts_at > now, Tournament.starts_at <= now + ANNOUNCE_AHEAD)
        .order_by(Tournament.starts_at))).scalars().all()
    n = 0
    for t in due:
        n += await announce(session, t)
    await session.commit()
    return n


async def on_article_published(session, a: Article) -> None:
    club = await session.get(Club, a.club_id) if a.club_id else None
    url = site_url(f"/news/{a.slug}")
    text = format_article(a.title, a.summary, url, club.name if club else None)
    if club:
        await broadcast(session, club, "article", text, f"article:{a.id}", photo_url=a.cover_url, link=url)
        return
    chat = settings.telegram_global_chat_id
    if chat:
        await enqueue(session, "article", chat, text, photo_url=a.cover_url, dedup_key=f"article:{a.id}:{chat}")


async def _nicknames(session, ids) -> dict[int, str]:
    return dict((await session.execute(select(User.id, User.nickname).where(User.id.in_(set(ids))))).all())


async def on_tournament_finished(session, t: Tournament, swiss_table=None) -> None:
    """Автоотчёт: итоги, поздравление, статистика, обновлённая таблица лиги.
    swiss_table - результат compute_standings (для швейцарки), считается ДО обновления лиги."""
    club = await session.get(Club, t.club_id)
    if not club or not (club.telegram_chat_id or await club_vk(session, club.id)):
        return

    if t.format == TournamentFormat.edh:
        rows = (await session.execute(
            select(EdhSeat.user_id, func.sum(EdhSeat.delta)).join(EdhTable, EdhTable.id == EdhSeat.table_id)
            .where(EdhTable.tournament_id == t.id, EdhTable.status == EdhTableStatus.finished)
            .group_by(EdhSeat.user_id))).all()
        rows = sorted(rows, key=lambda r: -(r[1] or 0))
        tables = (await session.execute(select(func.count(), func.count().filter(EdhTable.outcome != "win"))
                  .where(EdhTable.tournament_id == t.id, EdhTable.status == EdhTableStatus.finished))).one()
        league_rows = (await session.execute(select(ClubMember.user_id, ClubMember.edh_bank).where(
            ClubMember.club_id == t.club_id).order_by(ClubMember.edh_bank.desc()).limit(10))).all()
        names = await _nicknames(session, [r[0] for r in rows] + [r[0] for r in league_rows])
        standings = [(i, names.get(u, "?"), f"{(net or 0):+.0f}") for i, (u, net) in enumerate(rows, 1)]
        # поздравляем только тех, кто ушёл в плюс: «3-е место» с минусом в банке поздравлением не назовёшь
        podium = [(i, names.get(u, "?")) for i, (u, net) in enumerate(rows[:3], 1) if (net or 0) > 0]
        league = [(i, names.get(u, "?"), f"{bank:.0f}") for i, (u, bank) in enumerate(league_rows, 1)]
        stats = [f"Сыграно столов: {tables[0]}", f"Партий без победителя (ничья/таймер): {tables[1]}"]
        participants, league_title = len(rows), "Банк клуба (рейтинг EDH)"
    else:
        table = swiss_table or []
        league_rows = (await session.execute(select(ClubMember.user_id, ClubMember.league_points).where(
            ClubMember.club_id == t.club_id).order_by(ClubMember.league_points.desc()).limit(10))).all()
        names = await _nicknames(session, [r.player_id for r in table] + [r[0] for r in league_rows])
        standings = [(r.rank, names.get(r.player_id, "?"), f"{r.points} оч.") for r in table]
        podium = [(p, n) for p, n, _ in standings[:3]]
        league = [(i, names.get(u, "?"), f"{lp} оч.") for i, (u, lp) in enumerate(league_rows, 1)]
        played, draws = (await session.execute(select(func.count(), func.count().filter(Match.result == "draw"))
                         .where(Match.tournament_id == t.id, Match.p2_user_id.is_not(None)))).one()
        stats = [f"Сыграно матчей: {played}", f"Ничьих: {draws}"]
        participants, league_title = len(table), "Лига клуба"

    if t.league_id:   # турнир сезона: в отчёт - таблица сезона, а не общая лига клуба
        from . import leagues as L
        from .models import League, LeagueKind
        season = await session.get(League, t.league_id)
        if season:
            if season.kind == LeagueKind.edh:
                srows = await L.edh_table(session, season)
                league = [(i, r["nickname"], f"{r['bank']:.0f}") for i, r in enumerate(srows[:10], 1)]
            else:
                srows = await L.berserk_table(session, season)
                league = [(i, r["nickname"], f"{r['points']} оч.") for i, r in enumerate(srows[:10], 1)]
            league_title = f"Сезон «{season.name}»"
    judge = await session.get(User, t.judge_id) if t.judge_id else None
    judge_label = (judge.nickname + (f" (№{judge.player_no})" if judge.player_no else "")) if judge else None
    data = ReportData(title=t.name, club=club.name, game=t.game, fmt=t.format.value, date=t.starts_at,
                      participants=participants, rounds=t.current_round or None,
                      podium=podium, standings=standings, league_title=league_title,
                      league=league, stats=stats, url=site_url(f"/tournaments/{t.id}"), tz=settings.app_timezone,
                      judge=judge_label)
    await broadcast(session, club, "tournament_report", format_report(data), f"t-report:{t.id}", link=data.url)



async def to_user(session, user_id: int, kind: str, text: str, buttons: list | None = None,
                  dedup_key: str | None = None, club_id: int | None = None) -> bool:
    """Сообщение игроку в личку: в Telegram, если привязан, и от сообщества VK клуба (club_id), если у игрока
    привязан VK. Возвращает True, если хоть один канал есть."""
    from .models import AuthAccount, Provider
    accs = dict((await session.execute(select(AuthAccount.provider, AuthAccount.external_id).where(
        AuthAccount.user_id == user_id, AuthAccount.provider.in_([Provider.telegram, Provider.vk])))).all())
    sent = False
    chat = accs.get(Provider.telegram)
    if chat:
        await enqueue(session, kind, chat, text, buttons=buttons, dedup_key=f"{dedup_key}:{chat}" if dedup_key else None)
        sent = True
    vk_id = accs.get(Provider.vk)
    if vk_id and club_id:
        cfg = await club_vk(session, club_id)
        if cfg and cfg.group_token and cfg.dm_enabled:
            await enqueue(session, kind, f"{club_id}:{vk_id}", text, buttons=buttons, channel="vk",
                          dedup_key=f"{dedup_key}:vk:{club_id}:{vk_id}" if dedup_key else None)
            sent = True
    return sent
