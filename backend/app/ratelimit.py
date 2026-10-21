"""Ограничение частоты для входа, регистрации и сброса пароля.

Попытки пишутся в таблицу auth_attempts (а не в память процесса), поэтому лимит общий для всех
воркеров API и переживает перезапуск. Email и IP хранятся только в виде хеша.
"""
import hashlib
import ipaddress
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .models import AuthAttempt


@dataclass(frozen=True)
class Rule:
    kind: str
    limit: int
    window: timedelta
    message: str


LOGIN_EMAIL = Rule("login_email", 5, timedelta(minutes=15),
                   "Слишком много неудачных попыток входа. Попробуйте через {wait} или восстановите пароль.")
LOGIN_IP = Rule("login_ip", 30, timedelta(minutes=15),
                "Слишком много неудачных попыток входа с этого адреса. Попробуйте через {wait}.")
REGISTER_IP = Rule("register_ip", 10, timedelta(hours=1),
                   "Слишком много регистраций с этого адреса. Попробуйте через {wait}.")
FORGOT_EMAIL = Rule("forgot_email", 3, timedelta(hours=1),
                    "Письмо уже отправлено несколько раз. Проверьте папку «Спам» или попробуйте через {wait}.")
FORGOT_IP = Rule("forgot_ip", 10, timedelta(hours=1),
                 "Слишком много запросов на сброс пароля. Попробуйте через {wait}.")
RESET_IP = Rule("reset_ip", 10, timedelta(minutes=15),
                "Слишком много попыток со ссылками сброса. Попробуйте через {wait}.")

CREATOR_REQUEST = Rule("creator_request", 5, timedelta(days=1),
                       "Слишком много заявок за сутки. Попробуйте через {wait}.")

KEEP = timedelta(days=1)   # старше - удаляются


def _hash(value: str) -> str:
    return hashlib.sha256(f"{settings.jwt_secret}:{value}".encode()).hexdigest()


def _public(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip.strip())
    except ValueError:
        return False
    return not (a.is_private or a.is_loopback or a.is_link_local or a.is_reserved)


def client_ip(request: Request) -> str | None:
    """Публичный адрес игрока или None. Запрос идёт браузер -> Caddy -> Next.js -> API, поэтому берём
    из X-Forwarded-For самый правый публичный адрес: его дописал наш прокси, а не браузер (левые значения
    можно подделать). Локально и внутри Docker адреса частные - тогда лимиты по адресу не применяются,
    а лимиты по email работают всегда."""
    chain = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
    if request.client:
        chain.append(request.client.host)
    for ip in reversed(chain):
        if _public(ip):
            return ip
    return None


def _wait_text(seconds: float) -> str:
    minutes = max(1, int(-(-seconds // 60)))
    return f"{minutes} мин."


async def check(session: AsyncSession, rule: Rule, value: str | None) -> None:
    """429, если за окно уже набрано limit попыток."""
    if not value:
        return
    since = datetime.now(timezone.utc) - rule.window
    count, oldest = (await session.execute(
        select(func.count(), func.min(AuthAttempt.created_at)).where(
            AuthAttempt.kind == rule.kind, AuthAttempt.key == _hash(value), AuthAttempt.created_at > since))).one()
    if count >= rule.limit:
        retry = max(1.0, (oldest + rule.window - datetime.now(timezone.utc)).total_seconds())
        raise HTTPException(429, rule.message.format(wait=_wait_text(retry)),
                            headers={"Retry-After": str(int(retry))})


async def hit(session: AsyncSession, rule: Rule, value: str | None) -> None:
    """Записать попытку (коммит - на вызывающем)."""
    if not value:
        return
    session.add(AuthAttempt(kind=rule.kind, key=_hash(value), created_at=datetime.now(timezone.utc)))
    await session.execute(delete(AuthAttempt).where(AuthAttempt.created_at < datetime.now(timezone.utc) - KEEP))


async def clear(session: AsyncSession, rule: Rule, value: str | None) -> None:
    if not value:
        return
    await session.execute(delete(AuthAttempt).where(AuthAttempt.kind == rule.kind, AuthAttempt.key == _hash(value)))
