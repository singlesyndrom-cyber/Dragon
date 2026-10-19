import hashlib
import hmac
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import get_session
from ..deps import current_user
from ..models import AuthAccount, Provider, User
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
async def register(data: RegisterIn, session: AsyncSession = Depends(get_session)):
    email = data.email.lower()
    if await _find_account(session, Provider.email, email):
        raise HTTPException(409, "Email уже зарегистрирован")
    user = User(nickname=data.nickname)
    user.accounts.append(AuthAccount(provider=Provider.email, external_id=email,
                                     password_hash=hash_password(data.password)))
    session.add(user)
    await session.commit()
    return TokenOut(access_token=create_token(user.id))


@router.post("/login", response_model=TokenOut)
async def login(data: LoginIn, session: AsyncSession = Depends(get_session)):
    acc = await _find_account(session, Provider.email, data.email.lower())
    if not acc or not acc.password_hash or not verify_password(data.password, acc.password_hash):
        raise HTTPException(401, "Неверный email или пароль")
    return TokenOut(access_token=create_token(acc.user_id))


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
    return TokenOut(access_token=create_token(user.id))


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
    return {"id": user.id, "nickname": user.nickname, "role": user.role, "providers": list(providers)}
