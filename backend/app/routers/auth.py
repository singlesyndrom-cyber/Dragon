import hashlib
import hmac
import secrets
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .. import mailer
from .. import ratelimit as rl
from .. import vk
from ..config import settings
from ..db import get_session
from ..deps import current_user
from ..models import AuthAccount, GlobalRole, PasswordReset, Provider, Publisher, User
from ..notify import enqueue
from ..security import create_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    nickname: str = Field(min_length=2, max_length=64)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    access_token: str


async def _find_account(session: AsyncSession, provider: Provider, external_id: str):
    res = await session.execute(
        select(AuthAccount).where(AuthAccount.provider == provider, AuthAccount.external_id == external_id)
    )
    return res.scalar_one_or_none()


@router.post("/register", response_model=TokenOut)
async def register(data: RegisterIn, request: Request, session: AsyncSession = Depends(get_session)):
    ip = rl.client_ip(request)
    await rl.check(session, rl.REGISTER_IP, ip)
    email = data.email.lower()
    if await _find_account(session, Provider.email, email):
        raise HTTPException(409, "Email уже зарегистрирован")
    user = User(nickname=data.nickname)
    user.accounts.append(AuthAccount(provider=Provider.email, external_id=email,
                                     password_hash=hash_password(data.password)))
    session.add(user)
    await rl.hit(session, rl.REGISTER_IP, ip)
    await session.commit()
    return TokenOut(access_token=create_token(user.id, user.token_version or 0))


@router.post("/login", response_model=TokenOut)
async def login(data: LoginIn, request: Request, session: AsyncSession = Depends(get_session)):
    email, ip = data.email.lower(), rl.client_ip(request)
    # лимит считается по неудачам: и на email (подбор пароля к одному аккаунту), и на адрес (перебор аккаунтов)
    await rl.check(session, rl.LOGIN_EMAIL, email)
    await rl.check(session, rl.LOGIN_IP, ip)
    acc = await _find_account(session, Provider.email, email)
    if not acc or not acc.password_hash or not verify_password(data.password, acc.password_hash):
        await rl.hit(session, rl.LOGIN_EMAIL, email)
        await rl.hit(session, rl.LOGIN_IP, ip)
        await session.commit()
        raise HTTPException(401, "Неверный email или пароль")
    await rl.clear(session, rl.LOGIN_EMAIL, email)
    await session.commit()
    user = await session.get(User, acc.user_id)
    return TokenOut(access_token=create_token(user.id, user.token_version or 0))


# ---------- Восстановление и смена пароля ----------
class ForgotIn(BaseModel):
    email: EmailStr


class ResetIn(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    password: str = Field(min_length=8)


class ChangeIn(BaseModel):
    old_password: str
    new_password: str = Field(min_length=8)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _reset_link(token: str) -> str:
    base = (settings.public_base_url or "http://localhost:3000").rstrip("/")
    return f"{base}/reset?token={token}"


async def _set_password(session: AsyncSession, acc: AuthAccount, password: str) -> User:
    """Новый пароль: старые токены входа и неиспользованные ссылки сброса перестают действовать."""
    now = datetime.now(timezone.utc)
    acc.password_hash = hash_password(password)
    user = await session.get(User, acc.user_id)
    user.token_version = (user.token_version or 0) + 1
    await session.execute(update(PasswordReset).where(PasswordReset.user_id == acc.user_id,
                                                      PasswordReset.used_at.is_(None)).values(used_at=now))
    await rl.clear(session, rl.LOGIN_EMAIL, acc.external_id)
    return user


@router.post("/password/forgot", status_code=204)
async def forgot_password(data: ForgotIn, request: Request, background: BackgroundTasks,
                          session: AsyncSession = Depends(get_session)):
    """Ответ всегда одинаковый, есть такой email или нет: по нему нельзя узнать, кто зарегистрирован."""
    email, ip = data.email.lower(), rl.client_ip(request)
    await rl.check(session, rl.FORGOT_EMAIL, email)
    await rl.check(session, rl.FORGOT_IP, ip)
    await rl.hit(session, rl.FORGOT_EMAIL, email)
    await rl.hit(session, rl.FORGOT_IP, ip)
    acc = await _find_account(session, Provider.email, email)
    user = await session.get(User, acc.user_id) if acc else None
    if not user or user.is_banned:
        await session.commit()
        return
    token = secrets.token_urlsafe(32)
    minutes = settings.password_reset_minutes
    session.add(PasswordReset(user_id=user.id, token_hash=_token_hash(token),
                              expires_at=datetime.now(timezone.utc) + timedelta(minutes=minutes)))
    link = _reset_link(token)
    # если к аккаунту привязан Telegram - ссылка придёт и от бота: почта в России доходит не всегда
    tg = (await session.execute(select(AuthAccount.external_id).where(
        AuthAccount.user_id == user.id, AuthAccount.provider == Provider.telegram))).scalar_one_or_none()
    if tg:
        await enqueue(session, "password_reset", tg,
                      f"Сброс пароля на сайте. Ссылка действует {minutes} мин. "
                      "Если вы не запрашивали сброс, просто проигнорируйте сообщение.",
                      buttons=[[{"text": "Задать новый пароль", "url": link}]])
    await session.commit()
    body = (f"Здравствуйте, {user.nickname}!\n\n"
            f"Кто-то (надеемся, вы) запросил сброс пароля на сайте. Чтобы задать новый пароль, откройте ссылку:\n\n"
            f"{link}\n\n"
            f"Ссылка действует {minutes} мин. и сработает один раз. "
            f"Если вы не запрашивали сброс, просто проигнорируйте письмо: пароль останется прежним.")
    background.add_task(mailer.send_mail, email, "Восстановление пароля", body)


@router.post("/password/reset", response_model=TokenOut)
async def reset_password(data: ResetIn, request: Request, session: AsyncSession = Depends(get_session)):
    ip = rl.client_ip(request)
    await rl.check(session, rl.RESET_IP, ip)
    pr = (await session.execute(select(PasswordReset).where(
        PasswordReset.token_hash == _token_hash(data.token)).with_for_update())).scalar_one_or_none()
    if not pr or pr.used_at or pr.expires_at < datetime.now(timezone.utc):
        await rl.hit(session, rl.RESET_IP, ip)
        await session.commit()
        raise HTTPException(400, "Ссылка устарела или уже использована. Запросите новую.")
    acc = (await session.execute(select(AuthAccount).where(
        AuthAccount.user_id == pr.user_id, AuthAccount.provider == Provider.email))).scalar_one_or_none()
    if not acc:
        raise HTTPException(400, "У аккаунта нет входа по email")
    if (await session.get(User, pr.user_id)).is_banned:
        raise HTTPException(403, "Аккаунт заблокирован")
    user = await _set_password(session, acc, data.password)
    await session.commit()
    return TokenOut(access_token=create_token(user.id, user.token_version or 0))


@router.post("/password/change", response_model=TokenOut)
async def change_password(data: ChangeIn, user: User = Depends(current_user),
                          session: AsyncSession = Depends(get_session)):
    """Смена пароля из профиля. Другие устройства выйдут из аккаунта, это устройство получит новый токен."""
    acc = (await session.execute(select(AuthAccount).where(
        AuthAccount.user_id == user.id, AuthAccount.provider == Provider.email))).scalar_one_or_none()
    if not acc or not acc.password_hash:
        raise HTTPException(400, "У аккаунта нет пароля: вы входите через Telegram")
    await rl.check(session, rl.LOGIN_EMAIL, acc.external_id)
    if not verify_password(data.old_password, acc.password_hash):
        await rl.hit(session, rl.LOGIN_EMAIL, acc.external_id)
        await session.commit()
        raise HTTPException(400, "Текущий пароль указан неверно")
    await _set_password(session, acc, data.new_password)
    await session.commit()
    return TokenOut(access_token=create_token(user.id, user.token_version or 0))


# ---------- Telegram Login Widget ----------
class TelegramIn(BaseModel):
    id: int
    auth_date: int
    hash: str
    first_name: str | None = None
    last_name: str | None = None
    username: str | None = None
    photo_url: str | None = None


def verify_telegram(data: TelegramIn) -> bool:
    payload = data.model_dump(exclude={"hash"}, exclude_none=True)
    check = "\n".join(f"{k}={payload[k]}" for k in sorted(payload))
    secret = hashlib.sha256(settings.telegram_bot_token.encode()).digest()
    expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    fresh = time.time() - data.auth_date < 86400
    return hmac.compare_digest(expected, data.hash) and fresh


async def _login_or_create(session: AsyncSession, provider: Provider, ext_id: str,
                           nickname: str, link_to: User | None = None) -> User:
    acc = await _find_account(session, provider, ext_id)
    if acc:
        return await session.get(User, acc.user_id)
    user = link_to or User(nickname=nickname)
    user.accounts.append(AuthAccount(provider=provider, external_id=ext_id))
    session.add(user)
    await session.commit()
    return user


@router.post("/telegram", response_model=TokenOut)
async def telegram_login(data: TelegramIn, session: AsyncSession = Depends(get_session)):
    if not settings.telegram_bot_token or not verify_telegram(data):
        raise HTTPException(401, "Неверная подпись Telegram")
    nick = data.username or data.first_name or f"tg{data.id}"
    user = await _login_or_create(session, Provider.telegram, str(data.id), nick)
    return TokenOut(access_token=create_token(user.id, user.token_version or 0))


@router.post("/telegram/link", status_code=204)
async def telegram_link(data: TelegramIn, user: User = Depends(current_user),
                        session: AsyncSession = Depends(get_session)):
    """Привязать Telegram к уже существующему аккаунту."""
    if not verify_telegram(data):
        raise HTTPException(401, "Неверная подпись Telegram")
    if await _find_account(session, Provider.telegram, str(data.id)):
        raise HTTPException(409, "Этот Telegram уже привязан")
    session.add(AuthAccount(user_id=user.id, provider=Provider.telegram, external_id=str(data.id)))
    await session.commit()


# ---------- VK ID ----------
class VkIn(BaseModel):
    code: str = Field(min_length=1, max_length=2048)
    device_id: str = Field(min_length=1, max_length=512)
    code_verifier: str = Field(min_length=43, max_length=128)
    state: str | None = Field(default=None, max_length=256)


def vk_redirect_uri() -> str:
    """Адрес возврата VK ID - должен совпадать с «Доверенным redirect URL» в настройках приложения VK ID."""
    return settings.public_base_url.rstrip("/") + "/auth/vk"


@router.get("/vk/config")
async def vk_config():
    return {"enabled": vk.vkid_enabled() and bool(settings.public_base_url), "app_id": settings.vk_app_id or None,
            "redirect_uri": vk_redirect_uri() if settings.public_base_url else None}


async def vk_identity(data: VkIn) -> tuple[str, str, dict]:
    """Код VK ID -> (vk user id, имя, ответ с токенами)."""
    if not vk.vkid_enabled():
        raise HTTPException(501, "Вход через VK не настроен: нужен VK_APP_ID")
    try:
        got = await vk.exchange_code(data.code, data.code_verifier, data.device_id, vk_redirect_uri(), data.state)
    except vk.VkError as e:
        raise HTTPException(401, f"VK ID не подтвердил вход: {e.message}")
    uid = str(got.get("user_id") or "")
    name = ""
    try:
        info = await vk.user_info(got["access_token"])
        uid = uid or str(info.get("user_id") or "")
        name = f"{info.get('first_name', '')} {info.get('last_name', '')}".strip()
    except (vk.VkError, KeyError):
        pass
    if not uid:
        raise HTTPException(401, "VK ID не вернул пользователя")
    return uid, name or f"vk{uid}", got


@router.post("/vk", response_model=TokenOut)
async def vk_login(data: VkIn, session: AsyncSession = Depends(get_session)):
    uid, name, _ = await vk_identity(data)
    user = await _login_or_create(session, Provider.vk, uid, name[:64])
    return TokenOut(access_token=create_token(user.id, user.token_version or 0))


@router.post("/vk/link", status_code=204)
async def vk_link(data: VkIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    """Привязать VK к уже существующему аккаунту - для входа и сообщений от сообществ клубов."""
    uid, _, _ = await vk_identity(data)
    acc = await _find_account(session, Provider.vk, uid)
    if acc and acc.user_id != user.id:
        raise HTTPException(409, "Этот VK уже привязан к другому аккаунту")
    if not acc:
        session.add(AuthAccount(user_id=user.id, provider=Provider.vk, external_id=uid))
        await session.commit()


@router.get("/me")
async def me(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    providers = (await session.execute(select(AuthAccount.provider).where(AuthAccount.user_id == user.id))).scalars()
    return {"id": user.id, "player_no": user.player_no, "nickname": user.nickname, "role": user.role,
            "is_club_creator": user.is_club_creator or user.role == GlobalRole.admin,
            "is_moderator": user.is_moderator or user.role == GlobalRole.admin,
            "is_publisher": user.role == GlobalRole.admin or (await session.execute(
                select(Publisher.id).where(Publisher.user_id == user.id))).first() is not None,
            "publisher_consent": bool(user.publisher_consent),
            "providers": list(providers)}


# ---------- привязка Telegram / VK по одноразовой ссылке из кнопки «Записаться» ----------
PROVIDER_NAME = {Provider.telegram: "Telegram", Provider.vk: "ВКонтакте"}


async def _link(session: AsyncSession, code: str):
    from ..models import LinkCode
    from ..tg_actions import LINK_TTL
    lc = (await session.execute(select(LinkCode).where(LinkCode.code == code))).scalar_one_or_none()
    if not lc:
        raise HTTPException(404, "Ссылка не найдена. Нажмите «Записаться» под анонсом ещё раз")
    if lc.used_at:
        raise HTTPException(410, "Ссылка уже использована")
    created = lc.created_at if lc.created_at.tzinfo else lc.created_at.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) - created > LINK_TTL:
        raise HTTPException(410, "Ссылка устарела. Нажмите «Записаться» под анонсом ещё раз")
    return lc


async def _link_done(session: AsyncSession, lc, user: User) -> str | None:
    """Ссылка использована; если она пришла из анонса - записать на турнир."""
    from ..models import Tournament
    from ..tg_actions import register_user
    lc.used_at = datetime.now(timezone.utc)
    await session.commit()
    t = await session.get(Tournament, lc.tournament_id) if lc.tournament_id else None
    return await register_user(session, user, t) if t else None


@router.get("/link-code/{code}")
async def link_code_info(code: str, session: AsyncSession = Depends(get_session)):
    from ..models import Club, Tournament
    lc = await _link(session, code)
    t = await session.get(Tournament, lc.tournament_id) if lc.tournament_id else None
    club = await session.get(Club, t.club_id) if t else None
    linked = await _find_account(session, lc.provider, lc.external_id)
    return {"provider": lc.provider.value, "provider_name": PROVIDER_NAME[lc.provider],
            "who": f"@{lc.username}" if lc.username else (lc.display_name or ""), "already_linked": bool(linked),
            "tournament": {"id": t.id, "name": t.name, "starts_at": t.starts_at, "club": club.name if club else None} if t else None}


@router.post("/link-code/{code}/claim")
async def link_code_claim(code: str, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    """Привязать Telegram/VK из ссылки к своему аккаунту (вошли на сайт) и записаться на турнир."""
    lc = await _link(session, code)
    acc = await _find_account(session, lc.provider, lc.external_id)
    name = PROVIDER_NAME[lc.provider]
    if acc and acc.user_id != user.id:
        raise HTTPException(409, f"Этот {name} уже привязан к другому номеру игрока")
    if not acc:
        other = (await session.execute(select(AuthAccount).where(AuthAccount.user_id == user.id,
                                                                AuthAccount.provider == lc.provider))).scalar_one_or_none()
        if other:
            raise HTTPException(409, f"К вашему аккаунту уже привязан другой {name}")
        session.add(AuthAccount(user_id=user.id, provider=lc.provider, external_id=lc.external_id))
        if lc.provider == Provider.telegram and lc.username:
            user.tg_username = lc.username
    msg = await _link_done(session, lc, user)
    return {"linked": True, "player_no": user.player_no, "message": msg}


@router.post("/link-code/{code}/new")
async def link_code_new(code: str, session: AsyncSession = Depends(get_session)):
    """Аккаунта на сайте нет: создать его по Telegram/VK из ссылки, войти и записаться на турнир."""
    lc = await _link(session, code)
    if await _find_account(session, lc.provider, lc.external_id):
        raise HTTPException(409, f"Этот {PROVIDER_NAME[lc.provider]} уже привязан к аккаунту — войдите в него")
    user = User(nickname=((lc.username if lc.provider == Provider.telegram else None) or lc.display_name
                          or f"{lc.provider.value}{lc.external_id}")[:64],
                tg_username=lc.username if lc.provider == Provider.telegram else None)
    session.add(user)
    await session.flush()
    session.add(AuthAccount(user_id=user.id, provider=lc.provider, external_id=lc.external_id))
    await session.commit()
    await session.refresh(user)          # номер игрока выдаёт база
    msg = await _link_done(session, lc, user)
    return {"access_token": create_token(user.id, user.token_version or 0), "token_type": "bearer",
            "player_no": user.player_no, "message": msg}
