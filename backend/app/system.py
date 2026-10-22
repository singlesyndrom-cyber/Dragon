"""Состояние системы: пульс бота, очередь Telegram, резервные копии, оповещение администраторов.

Бот раз в минуту пишет пульс в service_status. Бэкенд раз в 5 минут проверяет:
- бот молчит дольше BOT_SILENT_MIN минут — процесс бота не работает;
- сообщения ждут в очереди дольше STALE_MIN минут — бот работает, но не достаёт до Telegram (прокси, блокировка);
- последней резервной копии больше 26 часов или последняя завершилась ошибкой.
При проблеме администраторам уходит письмо (не чаще раза в ALERT_EVERY), при восстановлении — письмо «всё в порядке».
"""
import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from . import mailer
from .config import settings
from .db import SessionLocal
from .models import AuthAccount, GlobalRole, OutboxMessage, OutboxStatus, Provider, ServiceStatus, User

log = logging.getLogger("system")

BOT_SILENT_MIN = 5
STALE_MIN = 10
BACKUP_MAX_AGE_H = 26
ALERT_EVERY = timedelta(hours=6)
HEARTBEAT = "bot_heartbeat"


def now() -> datetime:
    return datetime.now(timezone.utc)


async def get_status(session: AsyncSession, key: str) -> ServiceStatus | None:
    return await session.get(ServiceStatus, key)


async def set_status(session: AsyncSession, key: str, value: str = "") -> None:
    stmt = pg_insert(ServiceStatus).values(key=key, value=value, updated_at=now())
    await session.execute(stmt.on_conflict_do_update(index_elements=[ServiceStatus.key],
                                                     set_={"value": value, "updated_at": now()}))


def backups_info(directory: str | None = None) -> dict:
    """Что лежит в папке копий: status.json от контейнера backup и список файлов (новые сверху)."""
    d = directory or settings.backups_dir
    out: dict = {"available": os.path.isdir(d), "last": None, "files": []}
    if not out["available"]:
        return out
    try:
        with open(os.path.join(d, "status.json"), encoding="utf-8") as f:
            out["last"] = json.load(f)
    except (OSError, ValueError):
        pass
    files = []
    for name in os.listdir(d):
        if name.startswith("kki-") and name.endswith(".sql.gz"):
            st = os.stat(os.path.join(d, name))
            files.append({"name": name, "size": st.st_size,
                          "at": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat()})
    out["files"] = sorted(files, key=lambda x: x["at"], reverse=True)
    return out


async def health(session: AsyncSession) -> dict:
    """Сводка для админки и для проверки: что работает, что нет."""
    hb = await get_status(session, HEARTBEAT)
    bot_age = (now() - hb.updated_at).total_seconds() / 60 if hb else None
    pending = (await session.execute(select(func.count(), func.min(OutboxMessage.created_at)).where(
        OutboxMessage.status == OutboxStatus.pending))).one()
    oldest_min = (now() - pending[1]).total_seconds() / 60 if pending[1] else None
    failed = (await session.execute(select(func.count()).select_from(OutboxMessage).where(
        OutboxMessage.status == OutboxStatus.failed))).scalar_one()
    last_sent = (await session.execute(select(func.max(OutboxMessage.sent_at)))).scalar_one()
    b = backups_info()
    last = b["last"]
    backup_age_h = None
    if last and last.get("at"):
        try:
            backup_age_h = (now() - datetime.fromisoformat(last["at"])).total_seconds() / 3600
        except ValueError:
            pass
    problems = []
    if bot_age is None or bot_age > BOT_SILENT_MIN:
        problems.append("Бот не работает: нет сигнала " + (f"{int(bot_age)} мин" if bot_age is not None else "ни разу"))
    elif oldest_min is not None and oldest_min > STALE_MIN:
        problems.append(f"Сообщения Telegram не уходят: {pending[0]} в очереди, самое старое ждёт {int(oldest_min)} мин "
                        "(проверьте прокси и токен бота)")
    if b["available"]:
        if last and last.get("ok") is False:
            problems.append(f"Резервная копия не создалась: {last.get('error') or 'ошибка pg_dump'}")
        elif backup_age_h is None or backup_age_h > BACKUP_MAX_AGE_H:
            problems.append("Резервных копий нет больше суток" if backup_age_h else "Резервных копий ещё нет")
    return {"ok": not problems, "problems": problems,
            "bot": {"last_seen": hb.updated_at if hb else None,
                    "minutes_ago": None if bot_age is None else round(bot_age, 1)},
            "outbox": {"pending": pending[0], "oldest_minutes": None if oldest_min is None else round(oldest_min, 1),
                       "failed": failed, "last_sent_at": last_sent},
            "backups": {**b, "age_hours": None if backup_age_h is None else round(backup_age_h, 1)}}


async def _admin_emails(session: AsyncSession) -> list[str]:
    return list((await session.execute(select(AuthAccount.external_id).join(User, User.id == AuthAccount.user_id).where(
        User.role == GlobalRole.admin, AuthAccount.provider == Provider.email))).scalars())


async def check_and_alert(session: AsyncSession) -> str | None:
    """Одна проверка. Возвращает тему отправленного письма (или None) - удобно для тестов."""
    h = await health(session)
    last = await get_status(session, "alert_state")          # value = "problem" | "ok"
    was_problem = bool(last and last.value == "problem")
    subject = None
    if h["problems"]:
        if not was_problem or now() - last.updated_at > ALERT_EVERY:
            subject = "Dragon: требуется внимание"
            body = "Проверка сервера dragonclub.games нашла проблемы:\n\n" + "\n".join(f"- {p}" for p in h["problems"]) + \
                   "\n\nПодробности — в админке, блок «Состояние системы»."
            await set_status(session, "alert_state", "problem")
    elif was_problem:
        subject = "Dragon: всё снова работает"
        body = "Бот, очередь сообщений и резервные копии снова в порядке."
        await set_status(session, "alert_state", "ok")
    await session.commit()
    if subject:
        emails = await _admin_emails(session)
        for e in emails:
            await mailer.send_mail(e, subject, body)
        log.warning("%s: %s (письмо: %s)", subject, h["problems"], ", ".join(emails) or "некому")
    return subject


async def monitor_loop() -> None:
    await asyncio.sleep(120)   # дать боту и копиям подняться после перезапуска
    while True:
        try:
            async with SessionLocal() as s:
                await check_and_alert(s)
        except Exception:  # noqa: BLE001
            log.exception("проверка состояния не удалась")
        await asyncio.sleep(300)
