import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .. import notify
from ..db import get_session
from ..slug import slugify as translit_slug
from ..deps import JUDGE_GAMES, can_create_club, current_user, is_club_organizer, parse_judge_games, require_admin
from ..models import (AuthAccount, Club, ClubMember, ClubRole, ClubStats, ClubTable, GlobalRole, Provider,
                      TableBooking, Tournament,
                      TournamentPlayer, TournamentStatus, User)
from . import tables as tables_api

router = APIRouter(prefix="/clubs", tags=["clubs"])


class ClubIn(BaseModel):
    name: str = Field(min_length=2, max_length=128)
    description: str = ""
    city: str = ""
    telegram_chat_id: str | None = None


class ClubUpdate(BaseModel):
    description: str | None = None
    city: str | None = None
    telegram_chat_id: str | None = None


def slugify(name: str) -> str:
    """Латинский адрес клуба: «Дракон» -> drakon. Кириллица в адресах ломается при копировании и в мессенджерах."""
    return translit_slug(name, 60, fallback="club")


def club_out(c: Club) -> dict:
    s = c.stats
    return {"id": c.id, "name": c.name, "slug": c.slug, "city": c.city, "description": c.description,
            "rating": s.club_rating if s else 0, "tournaments_total": s.tournaments_total if s else 0,
            "avg_participants": s.avg_participants if s else 0,
            "busiest_weekday": s.busiest_weekday if s else None}


@router.get("")
async def list_clubs(session: AsyncSession = Depends(get_session)):
    res = await session.execute(select(Club).options(selectinload(Club.stats)).order_by(Club.name))
    return [club_out(c) for c in res.scalars()]


@router.get("/managed")
async def managed_clubs(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    """Клубы, где пользователь может создавать турниры: организатор (админ - любые)."""
    q = select(Club).order_by(Club.name)
    if user.role != GlobalRole.admin:
        q = q.join(ClubMember, ClubMember.club_id == Club.id).where(
            ClubMember.user_id == user.id, ClubMember.role == ClubRole.organizer)
    return [{"id": c.id, "name": c.name, "slug": c.slug} for c in (await session.execute(q.limit(200))).scalars()]


@router.get("/judging")
async def judging_clubs(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    """Клубы, где пользователь - судья (не организатор), с его направлениями."""
    rows = (await session.execute(select(Club, ClubMember.judge_games).join(ClubMember, ClubMember.club_id == Club.id)
                                  .where(ClubMember.user_id == user.id, ClubMember.judge_games != "",
                                         ClubMember.role != ClubRole.organizer).order_by(Club.name))).all()
    return [{"id": c.id, "name": c.name, "slug": c.slug, "games": parse_judge_games(g)} for c, g in rows]


@router.get("/mine")
async def my_clubs(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    """Клубы, где пользователь участник: роль, очки лиги, банк EDH, ближайшие турниры и есть ли столы для брони."""
    rows = (await session.execute(select(Club, ClubMember).join(ClubMember, ClubMember.club_id == Club.id)
                                  .where(ClubMember.user_id == user.id).order_by(Club.name))).all()
    ids = [c.id for c, _ in rows]
    upcoming = dict((await session.execute(
        select(Tournament.club_id, func.count()).where(Tournament.club_id.in_(ids),
                                                       Tournament.status == TournamentStatus.registration)
        .group_by(Tournament.club_id))).all()) if ids else {}
    tables = dict((await session.execute(select(ClubTable.club_id, func.count()).where(ClubTable.club_id.in_(ids))
                                         .group_by(ClubTable.club_id))).all()) if ids else {}
    return [{"id": c.id, "name": c.name, "slug": c.slug, "city": c.city, "organizer": m.role == ClubRole.organizer,
             "league_points": m.league_points, "edh_bank": round(m.edh_bank, 1), "events_played": m.events_played,
             "upcoming": upcoming.get(c.id, 0), "tables": tables.get(c.id, 0),
             "staff": m.role == ClubRole.organizer or bool(m.judge_games),
             "booking_notify": tables_api.gets_bookings(m)} for c, m in rows]


@router.get("/{slug}")
async def get_club(slug: str, session: AsyncSession = Depends(get_session)):
    res = await session.execute(select(Club).where(Club.slug == slug).options(selectinload(Club.stats)))
    club = res.scalar_one_or_none()
    if not club:
        raise HTTPException(404, "Клуб не найден")
    return club_out(club)


@router.post("", status_code=201)
async def create_club(data: ClubIn, owner: User = Depends(current_user),
                      session: AsyncSession = Depends(get_session)):
    """Создать клуб может только пользователь со статусом «Создатель Клуба» (или администратор);
    создатель становится организатором клуба."""
    if not can_create_club(owner):
        raise HTTPException(403, "Создавать клубы могут пользователи со статусом «Создатель Клуба». "
                                 "Подайте заявку в личном кабинете")
    if (await session.execute(select(Club).where(func.lower(Club.name) == data.name.strip().lower()))).scalar_one_or_none():
        raise HTTPException(409, "Клуб с таким названием уже есть")
    base = slugify(data.name)
    taken = set((await session.execute(select(Club.slug).where(Club.slug.like(f"{base}%")))).scalars())
    slug, n = base, 2
    while slug in taken:
        slug, n = f"{base}-{n}", n + 1
    club = Club(**data.model_dump(), slug=slug, stats=ClubStats())
    club.members.append(ClubMember(user_id=owner.id, role=ClubRole.organizer))
    session.add(club)
    await session.commit()
    return {"id": club.id, "slug": club.slug}


@router.patch("/{club_id}")
async def update_club(club_id: int, data: ClubUpdate, user: User = Depends(current_user),
                      session: AsyncSession = Depends(get_session)):
    if not await is_club_organizer(session, club_id, user):
        raise HTTPException(403, "Нужны права организатора клуба")
    club = await session.get(Club, club_id)
    if not club:
        raise HTTPException(404, "Клуб не найден")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(club, k, v)
    await session.commit()
    return {"ok": True}


@router.post("/{club_id}/join", status_code=204)
async def join_club(club_id: int, user: User = Depends(current_user),
                    session: AsyncSession = Depends(get_session)):
    if not await session.get(Club, club_id):
        raise HTTPException(404, "Клуб не найден")
    res = await session.execute(select(ClubMember).where(ClubMember.club_id == club_id,
                                                         ClubMember.user_id == user.id))
    if res.scalar_one_or_none():
        raise HTTPException(409, "Вы уже в клубе")
    session.add(ClubMember(club_id=club_id, user_id=user.id))
    await session.commit()


@router.post("/{club_id}/leave", status_code=204)
async def leave_club(club_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    """Выйти из клуба. Организатор выйти не может; сначала нужно отменить запись на незавершённые турниры клуба.
    Будущие брони столов в этом клубе отменяются (организаторы получат сообщение). Очки лиги и банк обнуляются."""
    m = (await session.execute(select(ClubMember).where(ClubMember.club_id == club_id,
                                                        ClubMember.user_id == user.id))).scalar_one_or_none()
    if not m:
        raise HTTPException(404, "Вы не состоите в этом клубе")
    if m.role == ClubRole.organizer:
        raise HTTPException(400, "Организатор не может выйти из своего клуба")
    busy = (await session.execute(select(Tournament.name).join(TournamentPlayer, TournamentPlayer.tournament_id == Tournament.id)
                                  .where(Tournament.club_id == club_id, TournamentPlayer.user_id == user.id,
                                         Tournament.status != TournamentStatus.finished))).scalars().first()
    if busy:
        raise HTTPException(400, f"Вы участвуете в турнире «{busy}»: сначала отмените запись или дождитесь его окончания")
    club = await session.get(Club, club_id)
    now = datetime.now(timezone.utc)
    for b in (await session.execute(select(TableBooking).where(
            TableBooking.club_id == club_id, TableBooking.user_id == user.id, TableBooking.status == "active",
            TableBooking.ends_at > now))).scalars():
        b.status, b.cancelled_by, b.cancelled_at = "cancelled", user.id, now
        table = await session.get(ClubTable, b.table_id)
        await tables_api.notify_staff(
            session, club, user, f"❌ <b>Бронь отменена</b> (игрок вышел из клуба)\n🏠 {notify.esc(club.name)} · "
            f"стол «{notify.esc(table.name)}»\n🕒 {tables_api.when(b)}\n👤 {tables_api.who(user)}", f"booking:{b.id}:cancel")
    await session.delete(m)
    await session.commit()


@router.get("/{club_id}/leaderboard")
async def leaderboard(club_id: int, session: AsyncSession = Depends(get_session)):
    """Локальная лига клуба."""
    res = await session.execute(
        select(ClubMember).where(ClubMember.club_id == club_id)
        .options(selectinload(ClubMember.user)).order_by(ClubMember.league_points.desc()).limit(100))
    return [{"user_id": m.user_id, "nickname": m.user.nickname, "league_points": m.league_points,
             "edh_bank": round(m.edh_bank, 1), "events_played": m.events_played} for m in res.scalars()]


@router.post("/{club_id}/members/{user_id}/organizer", status_code=204)
async def make_organizer(club_id: int, user_id: int, admin: User = Depends(require_admin),
                         session: AsyncSession = Depends(get_session)):
    res = await session.execute(select(ClubMember).where(ClubMember.club_id == club_id,
                                                         ClubMember.user_id == user_id))
    m = res.scalar_one_or_none()
    if not m:
        raise HTTPException(404, "Участник не найден")
    m.role = ClubRole.organizer
    await session.commit()


@router.post("/{club_id}/telegram/test", status_code=202)
async def telegram_test(club_id: int, user: User = Depends(current_user),
                        session: AsyncSession = Depends(get_session)):
    """Проверка подключения: бот отправит тестовое сообщение в чат клуба."""
    if not await is_club_organizer(session, club_id, user):
        raise HTTPException(403, "Нужны права организатора клуба")
    club = await session.get(Club, club_id)
    if not club:
        raise HTTPException(404, "Клуб не найден")
    if not club.telegram_chat_id:
        raise HTTPException(400, "Сначала укажите telegram_chat_id в настройках клуба")
    await notify.enqueue(session, "test", club.telegram_chat_id,
                         f"✅ Бот подключён к клубу «{notify.esc(club.name)}». Анонсы и итоги будут приходить сюда.")
    await session.commit()
    return {"queued": True}


@router.get("/{club_id}/membership")
async def membership(club_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    """Роль текущего пользователя в клубе; организатору - ещё и настройки клуба для формы."""
    club = await session.get(Club, club_id)
    if not club:
        raise HTTPException(404, "Клуб не найден")
    m = (await session.execute(select(ClubMember).where(ClubMember.club_id == club_id,
                                                        ClubMember.user_id == user.id))).scalar_one_or_none()
    can_manage = await is_club_organizer(session, club_id, user)
    out = {"member": m is not None, "role": m.role if m else None, "can_manage": can_manage,
           "judge_games": list(JUDGE_GAMES) if can_manage else parse_judge_games(m.judge_games if m else ""),
           "edh_bank": round(m.edh_bank, 1) if m else None, "league_points": m.league_points if m else None}
    if can_manage:
        out["settings"] = {"description": club.description, "city": club.city,
                           "telegram_chat_id": club.telegram_chat_id}
    return out


class JudgeSet(BaseModel):
    player_no: int = Field(ge=1)
    games: list[str] = Field(default_factory=list)   # mtg / edh / berserk; пустой список - снять судейство


@router.get("/{club_id}/judges")
async def club_judges(club_id: int, session: AsyncSession = Depends(get_session)):
    """Судейский состав клуба: организаторы (судят все направления) и назначенные судьи с направлениями."""
    rows = (await session.execute(select(ClubMember, User.nickname, User.player_no)
                                  .join(User, User.id == ClubMember.user_id)
                                  .where(ClubMember.club_id == club_id,
                                         (ClubMember.role == ClubRole.organizer) | (ClubMember.judge_games != ""))
                                  .order_by(ClubMember.role.desc(), User.nickname))).all()
    return [{"user_id": m.user_id, "nickname": nick, "player_no": no,
             "organizer": m.role == ClubRole.organizer,
             "games": list(JUDGE_GAMES) if m.role == ClubRole.organizer else parse_judge_games(m.judge_games)}
            for m, nick, no in rows]


@router.put("/{club_id}/judges")
async def set_club_judge(club_id: int, data: JudgeSet, user: User = Depends(current_user),
                         session: AsyncSession = Depends(get_session)):
    """Организатор назначает судью клуба по номеру игрока и выбирает направления."""
    if not await is_club_organizer(session, club_id, user):
        raise HTTPException(403, "Нужны права организатора клуба")
    bad = [g for g in data.games if g not in JUDGE_GAMES]
    if bad:
        raise HTTPException(422, "Направления судейства: mtg, edh, berserk")
    target = (await session.execute(select(User).where(User.player_no == data.player_no))).scalar_one_or_none()
    if not target:
        raise HTTPException(404, f"Игрока с номером {data.player_no} нет: проверьте номер в его кабинете")
    m = (await session.execute(select(ClubMember).where(ClubMember.club_id == club_id,
                                                        ClubMember.user_id == target.id))).scalar_one_or_none()
    if m and m.role == ClubRole.organizer:
        raise HTTPException(400, f"{target.nickname} — организатор клуба и уже судит все направления")
    if not m:
        if not data.games:
            raise HTTPException(404, f"{target.nickname} не судья этого клуба")
        m = ClubMember(club_id=club_id, user_id=target.id)
        session.add(m)
    m.judge_games = ",".join(g for g in JUDGE_GAMES if g in data.games)
    await session.commit()
    return {"user_id": target.id, "nickname": target.nickname, "player_no": target.player_no,
            "games": parse_judge_games(m.judge_games)}


async def is_staff(session: AsyncSession, club_id: int, user: User) -> bool:
    """Штаб клуба: организатор (и администратор) или судья любого направления."""
    if await is_club_organizer(session, club_id, user):
        return True
    games = (await session.execute(select(ClubMember.judge_games).where(
        ClubMember.club_id == club_id, ClubMember.user_id == user.id))).scalar_one_or_none()
    return bool(games)


@router.get("/{club_id}/members")
async def club_members(club_id: int, tournament_id: int | None = None, user: User = Depends(current_user),
                       session: AsyncSession = Depends(get_session)):
    """Участники клуба для штаба: роль, лига, банк EDH, активность, Telegram.
    С tournament_id - ещё и записан ли каждый в этот турнир."""
    if not await session.get(Club, club_id):
        raise HTTPException(404, "Клуб не найден")
    if not await is_staff(session, club_id, user):
        raise HTTPException(403, "Список участников видят организаторы и судьи клуба")
    rows = (await session.execute(select(ClubMember, User).join(User, User.id == ClubMember.user_id)
                                  .where(ClubMember.club_id == club_id))).all()
    ids = [u.id for _, u in rows]
    last = dict((await session.execute(
        select(TournamentPlayer.user_id, func.max(Tournament.starts_at))
        .join(Tournament, Tournament.id == TournamentPlayer.tournament_id)
        .where(Tournament.club_id == club_id, Tournament.status != TournamentStatus.registration,
               TournamentPlayer.user_id.in_(ids))
        .group_by(TournamentPlayer.user_id))).all()) if ids else {}
    tg = set((await session.execute(select(AuthAccount.user_id).where(
        AuthAccount.provider == Provider.telegram, AuthAccount.user_id.in_(ids)))).scalars()) if ids else set()
    registered = set()
    if tournament_id:
        registered = set((await session.execute(select(TournamentPlayer.user_id).where(
            TournamentPlayer.tournament_id == tournament_id))).scalars())
    out = [{"user_id": u.id, "nickname": u.nickname, "player_no": u.player_no, "guest": u.is_guest,
            "organizer": m.role == ClubRole.organizer, "judge_games": parse_judge_games(m.judge_games),
            "league_points": m.league_points, "edh_bank": round(m.edh_bank, 1), "events_played": m.events_played,
            "joined_at": m.joined_at, "last_played": last.get(u.id), "telegram": u.id in tg,
            "registered": u.id in registered} for m, u in rows]
    return sorted(out, key=lambda r: (not r["organizer"], not r["judge_games"], r["guest"], r["nickname"].lower()))


@router.get("/{club_id}/players")
async def club_players(club_id: int, q: str = "", user: User = Depends(current_user),
                       session: AsyncSession = Depends(get_session)):
    """Подсказки для «Добавить игрока»: участники клуба (и гости клуба) по нику или номеру игрока.
    По точному номеру находится любой игрок платформы, даже если он ещё не играл в этом клубе."""
    if not await is_staff(session, club_id, user):
        raise HTTPException(403, "Нужны права организатора или судьи клуба")
    term = q.strip().lstrip("№#").strip()
    cols = (User.id, User.nickname, User.is_guest, User.player_no)
    out, seen = [], set()
    if term.isdigit():
        found = (await session.execute(select(*cols).where(User.player_no == int(term)))).first()
        if found:
            member = (await session.execute(select(ClubMember.id).where(
                ClubMember.club_id == club_id, ClubMember.user_id == found[0]))).first() is not None
            out.append({"user_id": found[0], "nickname": found[1], "guest": found[2], "player_no": found[3],
                        "member": member})
            seen.add(found[0])
    stmt = select(*cols).join(ClubMember, ClubMember.user_id == User.id).where(ClubMember.club_id == club_id)
    if term:
        stmt = stmt.where(User.nickname.ilike(f"%{term}%"))
    rows = (await session.execute(stmt.order_by(User.is_guest, User.nickname).limit(20))).all()
    out += [{"user_id": uid, "nickname": nick, "guest": guest, "player_no": no, "member": True}
            for uid, nick, guest, no in rows if uid not in seen]
    return out[:20]


class MergeIn(BaseModel):
    """Аккаунт, к которому привязать гостя: по email или по номеру игрока."""
    email: str | None = Field(default=None, min_length=3, max_length=255)
    player_no: int | None = Field(default=None, ge=1)


@router.post("/{club_id}/guests/{guest_id}/merge")
async def merge_guest(club_id: int, guest_id: int, data: MergeIn, user: User = Depends(current_user),
                      session: AsyncSession = Depends(get_session)):
    """Гость зарегистрировался: переносим его историю (турниры, матчи, столы EDH, банки) на аккаунт по email."""
    from sqlalchemy import delete, update
    from ..models import AuthAccount, EdhSeat, EdhTable, LeagueMember, Match, Provider, TournamentPlayer

    if not await is_club_organizer(session, club_id, user):
        raise HTTPException(403, "Нужны права организатора клуба")
    guest = await session.get(User, guest_id)
    if not guest or not guest.is_guest or guest.guest_club_id != club_id:
        raise HTTPException(404, "Гость этого клуба не найден")
    if data.player_no:
        target = (await session.execute(select(User.id).where(
            User.player_no == data.player_no, User.is_guest.is_(False)))).scalar_one_or_none()
        if not target:
            raise HTTPException(404, f"Игрока с номером {data.player_no} нет: проверьте номер в его кабинете")
    elif data.email:
        acc = (await session.execute(select(AuthAccount).where(
            AuthAccount.provider == Provider.email,
            AuthAccount.external_id == data.email.strip().lower()))).scalar_one_or_none()
        if not acc:
            raise HTTPException(404, "Аккаунт с таким email не найден: игрок должен сначала зарегистрироваться")
        target = acc.user_id
    else:
        raise HTTPException(422, "Укажите email или номер игрока")
    both = (await session.execute(select(TournamentPlayer.tournament_id).where(TournamentPlayer.user_id == target)
                                  .intersect(select(TournamentPlayer.tournament_id).where(
                                      TournamentPlayer.user_id == guest_id)))).all()
    if both:
        raise HTTPException(409, "Гость и аккаунт записаны в один и тот же турнир — объединение невозможно")
    g_leagues = set((await session.execute(select(LeagueMember.league_id).where(LeagueMember.user_id == guest_id))).scalars())
    t_leagues = set((await session.execute(select(LeagueMember.league_id).where(LeagueMember.user_id == target))).scalars())
    if g_leagues & t_leagues:
        raise HTTPException(409, "Гость и аккаунт уже играют в одном сезоне лиги — объединение невозможно")

    for model, col in ((TournamentPlayer, TournamentPlayer.user_id), (Match, Match.p1_user_id), (Match, Match.p2_user_id),
                       (EdhSeat, EdhSeat.user_id), (EdhTable, EdhTable.winner_user_id), (LeagueMember, LeagueMember.user_id)):
        await session.execute(update(model).where(col == guest_id).values({col.key: target}))
    g_mem = (await session.execute(select(ClubMember).where(ClubMember.club_id == club_id,
                                                            ClubMember.user_id == guest_id))).scalar_one_or_none()
    t_mem = (await session.execute(select(ClubMember).where(ClubMember.club_id == club_id,
                                                            ClubMember.user_id == target))).scalar_one_or_none()
    if g_mem and t_mem:
        t_mem.league_points += g_mem.league_points
        t_mem.events_played += g_mem.events_played
        await session.delete(g_mem)
    elif g_mem:
        g_mem.user_id = target
    await session.flush()
    await session.execute(delete(User).where(User.id == guest_id))   # без ленивой загрузки связей
    await session.commit()
    return {"merged_into": target}
