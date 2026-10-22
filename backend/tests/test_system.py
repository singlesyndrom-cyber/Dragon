"""Состояние системы: пульс бота, зависшая очередь, резервные копии, письма администраторам.
Запуск: RUN_INTEGRATION=1 и DATABASE_URL."""
import json
import os
from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.skipif(not os.getenv("RUN_INTEGRATION"), reason="нужен PostgreSQL (RUN_INTEGRATION=1)")

if os.getenv("RUN_INTEGRATION"):
    import httpx
    from sqlalchemy import update

    from app import mailer, system
    from app.db import Base, SessionLocal, engine
    from app.main import app
    from app.models import GlobalRole, OutboxMessage, OutboxStatus, ServiceStatus, User


@pytest.fixture
async def client():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await engine.dispose()


@pytest.fixture
def mails(monkeypatch):
    sent = []

    async def fake(to, subject, body):
        sent.append((to, subject, body))
        return True
    monkeypatch.setattr(mailer, "send_mail", fake)
    return sent


async def admin(c):
    r = await c.post("/auth/register", json={"email": "boss@example.com", "password": "password1", "nickname": "Босс"})
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    me = (await c.get("/auth/me", headers=h)).json()
    async with SessionLocal() as s:
        await s.execute(update(User).where(User.id == me["id"]).values(role=GlobalRole.admin))
        await s.commit()
    return h


async def test_backups_info_reads_status_and_files(tmp_path):
    (tmp_path / "status.json").write_text(json.dumps({"at": datetime.now(timezone.utc).isoformat(), "ok": True,
                                                      "file": "kki-2026-10-23.sql.gz", "size": 2048,
                                                      "light": "kki-light-2026-10-23.sql.gz", "light_size": 512}))
    (tmp_path / "kki-2026-10-23.sql.gz").write_bytes(b"x" * 2048)
    (tmp_path / "kki-light-2026-10-23.sql.gz").write_bytes(b"x" * 512)
    (tmp_path / "other.txt").write_text("-")
    info = system.backups_info(str(tmp_path))
    assert info["available"] and info["last"]["ok"] is True
    assert {f["name"] for f in info["files"]} == {"kki-2026-10-23.sql.gz", "kki-light-2026-10-23.sql.gz"}
    assert system.backups_info(str(tmp_path / "missing"))["available"] is False


async def test_health_and_alerts(client, mails, monkeypatch, tmp_path):
    h = await admin(client)
    monkeypatch.setattr(system.settings, "backups_dir", str(tmp_path / "none"))   # копии не подключены - не проблема
    assert (await client.get("/admin/system")).status_code == 401

    # бот ни разу не выходил на связь
    r = (await client.get("/admin/system", headers=h)).json()
    assert r["ok"] is False and "Бот не работает" in r["problems"][0]
    async with SessionLocal() as s:
        assert await system.check_and_alert(s) == "Dragon: требуется внимание"
        assert await system.check_and_alert(s) is None                    # повтор не раньше чем через 6 часов
    assert [m[0] for m in mails] == ["boss@example.com"] and "Бот не работает" in mails[0][2]

    # бот жив, но сообщение висит 15 минут - значит, Telegram недоступен
    async with SessionLocal() as s:
        await system.set_status(s, system.HEARTBEAT)
        s.add(OutboxMessage(kind="test", chat_id="1", text="x", status=OutboxStatus.pending,
                            created_at=datetime.now(timezone.utc) - timedelta(minutes=15)))
        await s.commit()
    r = (await client.get("/admin/system", headers=h)).json()
    assert r["problems"] == [r["problems"][0]] and "не уходят" in r["problems"][0] and r["outbox"]["pending"] == 1

    # всё отправлено - письмо «снова работает», один раз
    async with SessionLocal() as s:
        await s.execute(update(OutboxMessage).values(status=OutboxStatus.sent, sent_at=datetime.now(timezone.utc)))
        await s.commit()
        assert await system.check_and_alert(s) == "Dragon: всё снова работает"
        assert await system.check_and_alert(s) is None
    assert (await client.get("/admin/system", headers=h)).json()["ok"] is True

    # бот замолчал 10 минут назад
    async with SessionLocal() as s:
        await s.execute(update(ServiceStatus).where(ServiceStatus.key == system.HEARTBEAT)
                        .values(updated_at=datetime.now(timezone.utc) - timedelta(minutes=10)))
        await s.commit()
    assert "нет сигнала 10 мин" in (await client.get("/admin/system", headers=h)).json()["problems"][0]


async def test_failed_or_old_backup_is_a_problem(client, monkeypatch, tmp_path):
    h = await admin(client)
    monkeypatch.setattr(system.settings, "backups_dir", str(tmp_path))
    async with SessionLocal() as s:
        await system.set_status(s, system.HEARTBEAT)
        await s.commit()
    assert "копий ещё нет" in (await client.get("/admin/system", headers=h)).json()["problems"][0]
    (tmp_path / "status.json").write_text(json.dumps({"at": datetime.now(timezone.utc).isoformat(), "ok": False,
                                                      "error": "pg_dump завершился с ошибкой"}))
    assert "не создалась" in (await client.get("/admin/system", headers=h)).json()["problems"][0]
    old = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
    (tmp_path / "status.json").write_text(json.dumps({"at": old, "ok": True, "size": 1, "light_size": 1}))
    assert "больше суток" in (await client.get("/admin/system", headers=h)).json()["problems"][0]
