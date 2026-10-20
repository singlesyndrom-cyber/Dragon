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
from ..config import settings
from ..db import get_session
from ..deps import current_user
from ..models import AuthAccount, PasswordReset, Provider, User
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


# ---------- VK ----------
class VkIn(BaseModel):
    code: str
    device_id: str
    code_verifier: str


@router.post("/vk", response_model=TokenOut)
async def vk_login(data: VkIn, session: AsyncSession = Depends(get_session)):
    # TODO: обмен code на токен через VK ID (https://id.vk.com/oauth2/auth),
    # получение user_id и имени. Нужны VK_APP_ID/VK_APP_SECRET и redirect_uri.
    # После получения vk_user_id вызвать _login_or_create(session, Provider.vk, vk_user_id, nickname).
    raise HTTPException(501, "VK-вход: нужна настройка приложения VK ID")


@router.get("/me")
async def me(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    providers = (await session.execute(select(AuthAccount.provider).where(AuthAccount.user_id == user.id))).scalars()
    return {"id": user.id, "player_no": user.player_no, "nickname": user.nickname, "role": user.role,
            "providers": list(providers)}
