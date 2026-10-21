"""Заявки на статус «Создатель Клуба»: игрок подаёт заявку в кабинете, администратор или модератор
одобряет или отклоняет её в админке. Только этот статус (или роль администратора) даёт право создать клуб.

Статус нельзя выдать себе через API: его меняют только approve и /admin/users/{номер}/roles,
а они требуют прав модератора или администратора.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .. import mailer, notify
from .. import ratelimit as rl
from ..db import get_session
from ..deps import can_create_club, current_user, require_admin, require_moderator
from ..models import AuthAccount, ClubCreatorRequest, CreatorRequestStatus, GlobalRole, Provider, User

router = APIRouter(tags=["club creators"])

STATUS_TEXT = {"pending": "на рассмотрении", "approved": "одобрена", "rejected": "отклонена"}


class RequestIn(BaseModel):
    club_name: str = Field(min_length=2, max_length=128)
    city: str = Field(default="", max_length=64)
    about: str = Field(min_length=10, max_length=1000)


class RejectIn(BaseModel):
    reason: str = Field(default="", max_length=500)


class RolesIn(BaseModel):
    is_club_creator: bool | None = None
    is_moderator: bool | None = None


def _out(r: ClubCreatorRequest) -> dict:
    return {"id": r.id, "status": r.status, "status_text": STATUS_TEXT[r.status], "club_name": r.club_name,
            "city": r.city, "about": r.about, "reject_reason": r.reject_reason,
            "created_at": r.created_at, "decided_at": r.decided_at}


async def _email(session: AsyncSession, user_id: int) -> str | None:
    return (await session.execute(select(AuthAccount.external_id).where(
        AuthAccount.user_id == user_id, AuthAccount.provider == Provider.email))).scalar_one_or_none()


async def _tg(session: AsyncSession, user_id: int) -> str | None:
    return (await session.execute(select(AuthAccount.external_id).where(
        AuthAccount.user_id == user_id, AuthAccount.provider == Provider.telegram))).scalar_one_or_none()


# ---------- игрок ----------
@router.get("/creator-requests/mine")
async def my_request(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    """Последняя заявка и есть ли статус. Кабинет показывает по этому ответу форму или текущий статус."""
    last = (await session.execute(select(ClubCreatorRequest).where(ClubCreatorRequest.user_id == user.id)
                                  .order_by(ClubCreatorRequest.id.desc()).limit(1))).scalar_one_or_none()
    return {"is_club_creator": can_create_club(user), "request": _out(last) if last else None}


@router.post("/creator-requests", status_code=201)
async def create_request(data: RequestIn, user: User = Depends(current_user),
                         session: AsyncSession = Depends(get_session)):
    if can_create_club(user):
        raise HTTPException(409, "У вас уже есть статус «Создатель Клуба»")
    if user.is_guest:
        raise HTTPException(403, "Сначала зарегистрируйтесь")
    pending = (await session.execute(select(ClubCreatorRequest.id).where(
        ClubCreatorRequest.user_id == user.id, ClubCreatorRequest.status == CreatorRequestStatus.pending.value)))
    if pending.first():
        raise HTTPException(409, "Заявка уже отправлена и находится на рассмотрении")
    await rl.check(session, rl.CREATOR_REQUEST, str(user.id))
    req = ClubCreatorRequest(user_id=user.id, status=CreatorRequestStatus.pending.value,
                             club_name=" ".join(data.club_name.split()), city=data.city.strip(),
                             about=data.about.strip())
    session.add(req)
    await rl.hit(session, rl.CREATOR_REQUEST, str(user.id))
    try:
        await session.commit()
    except IntegrityError:   # две заявки одновременно: вторую не пускает уникальный индекс
        await session.rollback()
        raise HTTPException(409, "Заявка уже отправлена и находится на рассмотрении")
    await session.refresh(req)
    return _out(req)


# ---------- админ и модератор ----------
@router.get("/admin/creator-requests")
async def list_requests(status: str | None = Query(None, pattern="^(pending|approved|rejected)$"),
                        _: User = Depends(require_moderator), session: AsyncSession = Depends(get_session)):
    q = select(ClubCreatorRequest, User).join(User, User.id == ClubCreatorRequest.user_id)
    if status:
        q = q.where(ClubCreatorRequest.status == status)
    rows = (await session.execute(q.order_by(ClubCreatorRequest.status != "pending",
                                             ClubCreatorRequest.id.desc()).limit(200))).all()
    deciders = {r.decided_by for r, _ in rows if r.decided_by}
    names = dict((await session.execute(select(User.id, User.nickname).where(User.id.in_(deciders)))).all()) \
        if deciders else {}
    out = []
    for r, u in rows:
        out.append({**_out(r), "user": {"id": u.id, "nickname": u.nickname, "player_no": u.player_no,
                                        "email": await _email(session, u.id), "banned": u.is_banned},
                    "decided_by": names.get(r.decided_by)})
    return out


async def _decide(session: AsyncSession, request_id: int, moderator: User, approve: bool, reason: str = ""):
    req = (await session.execute(select(ClubCreatorRequest).where(ClubCreatorRequest.id == request_id)
                                 .with_for_update())).scalar_one_or_none()
    if not req:
        raise HTTPException(404, "Заявка не найдена")
    if req.status != CreatorRequestStatus.pending.value:
        raise HTTPException(409, f"Заявка уже {STATUS_TEXT[req.status]}")
    req.status = (CreatorRequestStatus.approved if approve else CreatorRequestStatus.rejected).value
    req.reject_reason = "" if approve else reason.strip()
    req.decided_by, req.decided_at = moderator.id, datetime.now(timezone.utc)
    user = await session.get(User, req.user_id)
    if approve:
        user.is_club_creator = True
    return req, user


def _letter(user: User, req: ClubCreatorRequest) -> tuple[str, str]:
    link = notify.site_url("/clubs/new") or "/clubs/new"
    if req.status == CreatorRequestStatus.approved.value:
        return ("Заявка «Создатель Клуба» одобрена",
                f"Здравствуйте, {user.nickname}!\n\nВаша заявка на статус «Создатель Клуба» одобрена. "
                f"Теперь вы можете создать клуб «{req.club_name}»: {link}")
    reason = f"\n\nПричина: {req.reject_reason}" if req.reject_reason else ""
    return ("Заявка «Создатель Клуба» отклонена",
            f"Здравствуйте, {user.nickname}!\n\nВаша заявка на статус «Создатель Клуба» отклонена.{reason}\n\n"
            "Вы можете исправить заявку и отправить её снова в личном кабинете.")


async def _notify(session: AsyncSession, background: BackgroundTasks, user: User, req: ClubCreatorRequest):
    """Уведомление: на сайте статус виден в кабинете; дополнительно - письмо и сообщение бота, если есть куда."""
    subject, body = _letter(user, req)
    tg = await _tg(session, user.id)
    if tg:
        await notify.enqueue(session, "creator_request", tg, notify.esc(body))
    email = await _email(session, user.id)
    if email:
        background.add_task(mailer.send_mail, email, subject, body)


@router.post("/admin/creator-requests/{request_id}/approve")
async def approve(request_id: int, background: BackgroundTasks, moderator: User = Depends(require_moderator),
                  session: AsyncSession = Depends(get_session)):
    req, user = await _decide(session, request_id, moderator, approve=True)
    await _notify(session, background, user, req)
    await session.commit()
    return _out(req)


@router.post("/admin/creator-requests/{request_id}/reject")
async def reject(request_id: int, data: RejectIn, background: BackgroundTasks,
                 moderator: User = Depends(require_moderator), session: AsyncSession = Depends(get_session)):
    req, user = await _decide(session, request_id, moderator, approve=False, reason=data.reason)
    await _notify(session, background, user, req)
    await session.commit()
    return _out(req)


# ---------- только администратор: статусы вручную ----------
@router.get("/admin/staff")
async def staff(_: User = Depends(require_moderator), session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(User).where(
        (User.role == GlobalRole.admin) | User.is_moderator.is_(True)).order_by(User.nickname))).scalars().all()
    return [{"id": u.id, "nickname": u.nickname, "player_no": u.player_no, "admin": u.role == GlobalRole.admin,
             "moderator": u.is_moderator} for u in rows]


@router.put("/admin/users/{player_no}/roles")
async def set_roles(player_no: int, data: RolesIn, _: User = Depends(require_admin),
                    session: AsyncSession = Depends(get_session)):
    """Администратор назначает модераторов и при необходимости снимает или выдаёт статус «Создатель Клуба»."""
    user = (await session.execute(select(User).where(User.player_no == player_no))).scalar_one_or_none()
    if not user:
        raise HTTPException(404, f"Игрока с номером {player_no} нет")
    if data.is_club_creator is not None:
        user.is_club_creator = data.is_club_creator
    if data.is_moderator is not None:
        user.is_moderator = data.is_moderator
    await session.commit()
    return {"id": user.id, "nickname": user.nickname, "player_no": user.player_no,
            "is_club_creator": user.is_club_creator, "is_moderator": user.is_moderator}
