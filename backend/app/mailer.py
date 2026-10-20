"""Отправка писем через SMTP (Яндекс, Mail.ru, любой другой ящик или сервис рассылок).

Если SMTP не настроен, письмо не отправляется, а пишется в лог бэкенда: так сброс пароля можно
проверить локально командой `docker compose logs backend`.
"""
import asyncio
import logging
import smtplib
import ssl
from email.message import EmailMessage

from .config import settings

log = logging.getLogger("mailer")


def configured() -> bool:
    return bool(settings.smtp_host and settings.smtp_from)


def _send_sync(to: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"] = settings.smtp_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    ctx = ssl.create_default_context()
    mode = settings.smtp_security.lower()
    if mode == "ssl":
        server = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, context=ctx, timeout=20)
    else:
        server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20)
    with server:
        if mode == "starttls":
            server.starttls(context=ctx)
        if settings.smtp_user:
            server.login(settings.smtp_user, settings.smtp_password)
        server.send_message(msg)


async def send_mail(to: str, subject: str, body: str) -> bool:
    if not configured():
        log.warning("SMTP не настроен, письмо не отправлено. Кому: %s. Тема: %s\n%s", to, subject, body)
        return False
    try:
        await asyncio.to_thread(_send_sync, to, subject, body)
        return True
    except Exception:  # noqa: BLE001 - ошибка почты не должна ронять запрос
        log.exception("Не удалось отправить письмо на %s", to)
        return False
