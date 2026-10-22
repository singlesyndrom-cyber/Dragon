"""Столы клуба и бронирование.

Организатор клуба заводит столы и часы работы. Участник клуба бронирует стол на дату и время:
начало и длительность кратны 30 минутам, бронь целиком внутри часов работы этого дня, без пересечений
с другими бронями стола. Бронь подтверждается сразу; организаторы клуба получают сообщение бота в личку
о новой брони и об отмене.
"""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import notify
from ..config import settings
from ..db import get_session
from ..deps import current_user, is_club_organizer, optional_user
from ..models import AuthAccount, Club, ClubMember, ClubRole, ClubTable, Provider, TableBooking, User

router = APIRouter(tags=["tables"])

STEP = 30                     # минут: шаг начала и длительности брони
MAX_DURATION = 12 * 60        # одна бронь - не дольше 12 часов
DAYS_AHEAD = 60               # бронировать можно на 60 дней вперёд
MAX_ACTIVE = 3                # будущих броней у игрока в одном клубе (организаторов не ограничиваем)
DEFAULT_HOURS = {str(d): ["10:00", "23:00"] for d in range(7)}
WEEKDAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]


def _tz() -> ZoneInfo:
    return ZoneInfo(settings.app_timezone)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _minutes(hhmm: str) -> int:
    """'18:30' -> 1110; допускается '24:00' (закрытие в полночь)."""
    try:
        h, m = hhmm.split(":")
        v = int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        raise ValueError("время в формате ЧЧ:ММ")
    if not 0 <= v <= 1440 or int(m) >= 60:
        raise ValueError("время в формате ЧЧ:ММ")
    return v


def _hhmm(dt: datetime) -> str:
    return dt.astimezone(_tz()).strftime("%H:%M")


def hours_of(club: Club) -> dict:
    return club.opening_hours if club.opening_hours is not None else DEFAULT_HOURS


def window(club: Club, d: date) -> tuple[datetime, datetime] | None:
    """Часы работы клуба в этот день; закрытие раньше открытия - работа после полуночи (до утра)."""
    day = hours_of(club).get(str(d.weekday()))
    if not day:
        return None
    o, c = _minutes(day[0]), _minutes(day[1])
    start = datetime.combine(d, time(0), tzinfo=_tz()) + timedelta(minutes=o)
    end = datetime.combine(d, time(0), tzinfo=_tz()) + timedelta(minutes=c if c > o else c + 1440)
    return start, end


async def _club(session: AsyncSession, club_id: int) -> Club:
    club = await session.get(Club, club_id)
    if not club:
        raise HTTPException(404, "Клуб не найден")
    return club


async def _require_org(session: AsyncSession, club_id: int, user: User):
    if not await is_club_organizer(session, club_id, user):
        raise HTTPException(403, "Столы и часы работы настраивает организатор клуба")


async def _table(session: AsyncSession, club_id: int, table_id: int, lock: bool = False) -> ClubTable:
    q = select(ClubTable).where(ClubTable.id == table_id, ClubTable.club_id == club_id)
    t = (await session.execute(q.with_for_update() if lock else q)).scalar_one_or_none()
    if not t:
        raise HTTPException(404, "Стол не найден")
    return t


def _table_out(t: ClubTable) -> dict:
    return {"id": t.id, "name": t.name, "seats": t.seats, "games": t.games, "description": t.description}


# ---------- столы (организатор) ----------
class TableIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    seats: int = Field(default=4, ge=1, le=30)
    games: str = Field(default="", max_length=64)
    description: str = Field(default="", max_length=300)


class TablePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    seats: int | None = Field(default=None, ge=1, le=30)
    games: str | None = Field(default=None, max_length=64)
    description: str | None = Field(default=None, max_length=300)


@router.get("/clubs/{club_id}/tables")
async def list_tables(club_id: int, session: AsyncSession = Depends(get_session)):
    await _club(session, club_id)
    rows = (await session.execute(select(ClubTable).where(ClubTable.club_id == club_id)
                                  .order_by(ClubTable.id))).scalars()
    return [_table_out(t) for t in rows]


@router.post("/clubs/{club_id}/tables", status_code=201)
async def add_table(club_id: int, data: TableIn, user: User = Depends(current_user),
                    session: AsyncSession = Depends(get_session)):
    await _club(session, club_id)
    await _require_org(session, club_id, user)
    count = (await session.execute(select(func.count()).select_from(ClubTable)
                                   .where(ClubTable.club_id == club_id))).scalar_one()
    if count >= 50:
        raise HTTPException(400, "В клубе не может быть больше 50 столов")
    t = ClubTable(club_id=club_id, name=data.name.strip(), seats=data.seats, games=data.games.strip(),
                  description=data.description.strip())
    session.add(t)
    await session.commit()
    await session.refresh(t)
    return _table_out(t)


@router.patch("/clubs/{club_id}/tables/{table_id}")
async def edit_table(club_id: int, table_id: int, data: TablePatch, user: User = Depends(current_user),
                     session: AsyncSession = Depends(get_session)):
    await _require_org(session, club_id, user)
    t = await _table(session, club_id, table_id)
    for k, v in data.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(t, k, v.strip() if isinstance(v, str) else v)
    await session.commit()
    return _table_out(t)


@router.delete("/clubs/{club_id}/tables/{table_id}", status_code=204)
async def delete_table(club_id: int, table_id: int, user: User = Depends(current_user),
                       session: AsyncSession = Depends(get_session)):
    await _require_org(session, club_id, user)
    t = await _table(session, club_id, table_id, lock=True)
    future = (await session.execute(select(func.count()).select_from(TableBooking).where(
        TableBooking.table_id == t.id, TableBooking.status == "active", TableBooking.ends_at > _now()))).scalar_one()
    if future:
        raise HTTPException(409, f"На этот стол есть будущие брони ({future}). Сначала отмените их.")
    await session.delete(t)
    await session.commit()


# ---------- часы работы ----------
class HoursIn(BaseModel):
    days: dict[str, list[str] | None]   # "0".."6" -> ["12:00", "23:00"] или null (выходной)

    @field_validator("days")
    @classmethod
    def check(cls, v):
        out = {}
        for k, day in v.items():
            if k not in {str(i) for i in range(7)}:
                raise ValueError("дни недели: 0 (пн) … 6 (вс)")
            if not day:
                continue
            if len(day) != 2:
                raise ValueError("укажите открытие и закрытие")
            o, c = _minutes(day[0]), _minutes(day[1])
            if o % STEP or c % STEP:
                raise ValueError("время кратно 30 минутам")
            if o == c or o == 1440:
                raise ValueError("открытие и закрытие не должны совпадать")
            out[k] = [f"{o // 60:02d}:{o % 60:02d}", f"{c // 60:02d}:{c % 60:02d}"]
        return out


@router.get("/clubs/{club_id}/hours")
async def get_hours(club_id: int, session: AsyncSession = Depends(get_session)):
    club = await _club(session, club_id)
    return {"days": hours_of(club), "custom": club.opening_hours is not None}


@router.put("/clubs/{club_id}/hours")
async def set_hours(club_id: int, data: HoursIn, user: User = Depends(current_user),
                    session: AsyncSession = Depends(get_session)):
    club = await _club(session, club_id)
    await _require_org(session, club_id, user)
    club.opening_hours = data.days
    await session.commit()
    return {"days": hours_of(club), "custom": True}


# ---------- расписание дня ----------
@router.get("/clubs/{club_id}/bookings")
async def day_schedule(club_id: int, day: date = Query(alias="date"), user: User | None = Depends(optional_user),
                       session: AsyncSession = Depends(get_session)):
    """Столы и брони на день. Имена бронирующих видят участники клуба; остальным - только занятость."""
    club = await _club(session, club_id)
    win = window(club, day)
    member = False
    if user:
        member = bool((await session.execute(select(ClubMember.id).where(
            ClubMember.club_id == club_id, ClubMember.user_id == user.id))).first()) \
            or await is_club_organizer(session, club_id, user)
    tables = (await session.execute(select(ClubTable).where(ClubTable.club_id == club_id)
                                    .order_by(ClubTable.id))).scalars().all()
    # брони, задевающие сутки и рабочее окно дня (в том числе работа после полуночи)
    lo = datetime.combine(day, time(0), tzinfo=_tz())
    hi = max(lo + timedelta(days=1), win[1] if win else lo)
    rows = (await session.execute(
        select(TableBooking, User.nickname, User.player_no).join(User, User.id == TableBooking.user_id)
        .where(TableBooking.club_id == club_id, TableBooking.status == "active",
               TableBooking.starts_at < hi, TableBooking.ends_at > lo)
        .order_by(TableBooking.starts_at))).all()
    by_table: dict[int, list] = {}
    for b, nick, no in rows:
        by_table.setdefault(b.table_id, []).append({
            "id": b.id, "start": b.starts_at, "end": b.ends_at, "from": _hhmm(b.starts_at), "to": _hhmm(b.ends_at),
            "mine": bool(user and b.user_id == user.id),
            "nickname": nick if member else None, "player_no": no if member else None,
            "note": b.note if (user and b.user_id == user.id) else ""})
    return {"club_id": club_id, "date": day, "weekday": WEEKDAYS[day.weekday()],
            "open": {"from": _hhmm(win[0]), "to": _hhmm(win[1]), "start": win[0], "end": win[1]} if win else None,
            "member": member, "step": STEP, "max_duration": MAX_DURATION, "days_ahead": DAYS_AHEAD,
            "tables": [{**_table_out(t), "bookings": by_table.get(t.id, [])} for t in tables]}


# ---------- бронирование ----------
class BookingIn(BaseModel):
    model_config = {"populate_by_name": True}
    table_id: int
    day: date = Field(alias="date")
    start: str = Field(pattern=r"^\d{2}:\d{2}$")      # местное время клуба
    duration: int = Field(ge=STEP, le=MAX_DURATION)   # минут
    note: str = Field(default="", max_length=200)


def when(b: TableBooking) -> str:
    s, e = b.starts_at.astimezone(_tz()), b.ends_at.astimezone(_tz())
    return f"{WEEKDAYS[s.weekday()]} {s:%d.%m}, {s:%H:%M}–{e:%H:%M}"


def gets_bookings(m: ClubMember) -> bool:
    """Получает ли участник штаба клуба сообщения о бронях (по умолчанию - организаторы)."""
    if m.role != ClubRole.organizer and not m.judge_games:
        return False
    return m.booking_notify if m.booking_notify is not None else m.role == ClubRole.organizer


async def notify_staff(session: AsyncSession, club: Club, actor: User, text: str, dedup: str):
    """Сообщение бота в личку тем организаторам и судьям клуба, кто получает брони и привязал Telegram
    (кроме того, кто действовал)."""
    rows = (await session.execute(
        select(ClubMember, AuthAccount.external_id).join(AuthAccount, AuthAccount.user_id == ClubMember.user_id)
        .where(ClubMember.club_id == club.id, AuthAccount.provider == Provider.telegram,
               AuthAccount.user_id != actor.id))).all()
    for m, chat in rows:
        if gets_bookings(m):
            await notify.enqueue(session, "booking", chat, text, dedup_key=f"{dedup}:{chat}")


class NotifyIn(BaseModel):
    enabled: bool


@router.get("/clubs/{club_id}/booking-recipients")
async def booking_recipients(club_id: int, user: User = Depends(current_user),
                             session: AsyncSession = Depends(get_session)):
    """Организаторы и судьи клуба: кто получает сообщения о бронях и привязан ли у него Telegram."""
    await _club(session, club_id)
    await _require_org(session, club_id, user)
    rows = (await session.execute(
        select(ClubMember, User.nickname, User.player_no).join(User, User.id == ClubMember.user_id)
        .where(ClubMember.club_id == club_id, (ClubMember.role == ClubRole.organizer) | (ClubMember.judge_games != ""))
        .order_by(ClubMember.role.desc(), User.nickname))).all()
    tg = set((await session.execute(select(AuthAccount.user_id).where(
        AuthAccount.provider == Provider.telegram, AuthAccount.user_id.in_([m.user_id for m, _, _ in rows])))).scalars()) \
        if rows else set()
    return [{"user_id": m.user_id, "nickname": nick, "player_no": no, "organizer": m.role == ClubRole.organizer,
             "judge_games": [g for g in m.judge_games.split(",") if g], "enabled": gets_bookings(m),
             "telegram": m.user_id in tg, "me": m.user_id == user.id} for m, nick, no in rows]


async def _staff_member(session: AsyncSession, club_id: int, user_id: int) -> ClubMember:
    m = (await session.execute(select(ClubMember).where(ClubMember.club_id == club_id,
                                                        ClubMember.user_id == user_id))).scalar_one_or_none()
    if not m or (m.role != ClubRole.organizer and not m.judge_games):
        raise HTTPException(400, "Сообщения о бронях получают только организаторы и судьи клуба")
    return m


@router.put("/clubs/{club_id}/booking-recipients/{user_id}")
async def set_recipient(club_id: int, user_id: int, data: NotifyIn, user: User = Depends(current_user),
                        session: AsyncSession = Depends(get_session)):
    """Организатор включает или выключает сообщения о бронях любому организатору или судье клуба."""
    await _require_org(session, club_id, user)
    m = await _staff_member(session, club_id, user_id)
    m.booking_notify = data.enabled
    await session.commit()
    return {"user_id": user_id, "enabled": gets_bookings(m)}


@router.put("/clubs/{club_id}/booking-notify")
async def set_my_notify(club_id: int, data: NotifyIn, user: User = Depends(current_user),
                        session: AsyncSession = Depends(get_session)):
    """Организатор или судья сам подписывается на сообщения о бронях или отписывается от них."""
    m = await _staff_member(session, club_id, user.id)
    m.booking_notify = data.enabled
    await session.commit()
    return {"enabled": gets_bookings(m)}


@router.post("/clubs/{club_id}/bookings/notify-test", status_code=202)
async def notify_test(club_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    """Организатор проверяет, что сообщения о бронях доходят: бот присылает ему в личку образец сообщения.
    Обычные уведомления о своих действиях организатор не получает, поэтому проверка - отдельной кнопкой."""
    club = await _club(session, club_id)
    await _require_org(session, club_id, user)
    chat = (await session.execute(select(AuthAccount.external_id).where(
        AuthAccount.user_id == user.id, AuthAccount.provider == Provider.telegram))).scalar_one_or_none()
    if not chat:
        raise HTTPException(400, "К вашему аккаунту не привязан Telegram: привяжите его в личном кабинете")
    table = (await session.execute(select(ClubTable.name).where(ClubTable.club_id == club_id)
                                   .order_by(ClubTable.id).limit(1))).scalar_one_or_none() or "Стол 1"
    start = datetime.now(_tz()).replace(hour=18, minute=0, second=0, microsecond=0) + timedelta(days=1)
    sample = TableBooking(starts_at=start, ends_at=start + timedelta(hours=3))
    await notify.enqueue(session, "booking_test", chat,
                         "🧪 <b>Проверка уведомлений о бронях</b>\nТак будет выглядеть сообщение о новой брони:\n\n"
                         f"📅 <b>Новая бронь стола</b>\n🏠 {notify.esc(club.name)} · стол «{notify.esc(table)}»\n"
                         f"🕒 {when(sample)}\n👤 {who(user)}\n💬 Пример комментария игрока")
    await session.commit()
    return {"queued": True}


def who(u: User) -> str:
    return notify.esc(u.nickname) + (f" (№{u.player_no})" if u.player_no else "")


@router.post("/clubs/{club_id}/bookings", status_code=201)
async def book(club_id: int, data: BookingIn, user: User = Depends(current_user),
               session: AsyncSession = Depends(get_session)):
    club = await _club(session, club_id)
    org = await is_club_organizer(session, club_id, user)
    is_member = (await session.execute(select(ClubMember.id).where(
        ClubMember.club_id == club_id, ClubMember.user_id == user.id))).first()
    if user.is_guest or not (is_member or org):
        raise HTTPException(403, "Бронировать столы могут участники клуба: вступите в клуб на его странице")
    try:
        start_min = _minutes(data.start)
    except ValueError:
        raise HTTPException(422, "Время начала в формате ЧЧ:ММ")
    if start_min % STEP or data.duration % STEP:
        raise HTTPException(422, "Начало и длительность брони - с шагом 30 минут")
    today = datetime.now(_tz()).date()
    if data.day > today + timedelta(days=DAYS_AHEAD):
        raise HTTPException(400, f"Бронировать можно не больше чем на {DAYS_AHEAD} дней вперёд")
    win = window(club, data.day)
    if not win:
        raise HTTPException(400, "В этот день клуб не работает")
    starts = datetime.combine(data.day, time(0), tzinfo=_tz()) + timedelta(minutes=start_min)
    if starts < win[0]:                    # время после полуночи относится к тому же рабочему дню
        starts += timedelta(days=1)
    ends = starts + timedelta(minutes=data.duration)
    if starts < win[0] or ends > win[1]:
        raise HTTPException(400, f"Клуб работает {_hhmm(win[0])}–{_hhmm(win[1])}: бронь должна в это уложиться")
    if starts < _now():
        raise HTTPException(400, "Это время уже прошло")

    table = await _table(session, club_id, data.table_id, lock=True)   # очередь на стол: без двойных броней
    if not org:
        active = (await session.execute(select(func.count()).select_from(TableBooking).where(
            TableBooking.club_id == club_id, TableBooking.user_id == user.id, TableBooking.status == "active",
            TableBooking.ends_at > _now()))).scalar_one()
        if active >= MAX_ACTIVE:
            raise HTTPException(400, f"У вас уже {active} будущих брони в этом клубе - это максимум")
    clash = (await session.execute(select(TableBooking).where(
        TableBooking.table_id == table.id, TableBooking.status == "active",
        TableBooking.starts_at < ends, TableBooking.ends_at > starts))).scalars().first()
    if clash:
        raise HTTPException(409, f"Стол «{table.name}» уже занят {_hhmm(clash.starts_at)}–{_hhmm(clash.ends_at)}")
    b = TableBooking(club_id=club_id, table_id=table.id, user_id=user.id, starts_at=starts, ends_at=ends,
                     note=data.note.strip())
    session.add(b)
    await session.flush()
    note = f"\n💬 {notify.esc(b.note)}" if b.note else ""
    await notify_staff(session, club, user,
                             f"📅 <b>Новая бронь стола</b>\n🏠 {notify.esc(club.name)} · стол «{notify.esc(table.name)}»\n"
                             f"🕒 {when(b)}\n👤 {who(user)}{note}", f"booking:{b.id}:new")
    await session.commit()
    return {"id": b.id, "table": table.name, "start": b.starts_at, "end": b.ends_at, "when": when(b)}


@router.delete("/bookings/{booking_id}", status_code=204)
async def cancel(booking_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    """Отменить бронь может тот, кто бронировал, и организатор клуба."""
    b = (await session.execute(select(TableBooking).where(TableBooking.id == booking_id)
                               .with_for_update())).scalar_one_or_none()
    if not b:
        raise HTTPException(404, "Бронь не найдена")
    if b.user_id != user.id and not await is_club_organizer(session, b.club_id, user):
        raise HTTPException(403, "Отменить бронь может тот, кто бронировал, или организатор клуба")
    if b.status != "active":
        raise HTTPException(409, "Бронь уже отменена")
    if b.ends_at <= _now():
        raise HTTPException(400, "Бронь уже прошла")
    b.status, b.cancelled_by, b.cancelled_at = "cancelled", user.id, _now()
    club = await session.get(Club, b.club_id)
    table = await session.get(ClubTable, b.table_id)
    owner = await session.get(User, b.user_id)
    by = "" if owner.id == user.id else f"\n✋ Отменил: {who(user)}"
    await notify_staff(session, club, user,
                             f"❌ <b>Бронь отменена</b>\n🏠 {notify.esc(club.name)} · стол «{notify.esc(table.name)}»\n"
                             f"🕒 {when(b)}\n👤 {who(owner)}{by}", f"booking:{b.id}:cancel")
    await session.commit()


@router.get("/bookings/mine")
async def my_bookings(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(
        select(TableBooking, ClubTable.name, Club.name, Club.slug)
        .join(ClubTable, ClubTable.id == TableBooking.table_id).join(Club, Club.id == TableBooking.club_id)
        .where(TableBooking.user_id == user.id, TableBooking.status == "active", TableBooking.ends_at > _now())
        .order_by(TableBooking.starts_at))).all()
    return [{"id": b.id, "club": club, "club_slug": slug, "club_id": b.club_id, "table": tname,
             "start": b.starts_at, "end": b.ends_at, "when": when(b), "note": b.note} for b, tname, club, slug in rows]
