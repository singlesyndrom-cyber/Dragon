"""Лимиты попыток входа, восстановление и смена пароля. Запуск: RUN_INTEGRATION=1 и DATABASE_URL."""
import os
import re
from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.skipif(not os.getenv("RUN_INTEGRATION"), reason="нужен PostgreSQL (RUN_INTEGRATION=1)")

if os.getenv("RUN_INTEGRATION"):
    import httpx
    from sqlalchemy import select, update

    from app import mailer
    from app.db import Base, SessionLocal, engine
    from app.main import app
    from app.models import AuthAccount, AuthAttempt, OutboxMessage, PasswordReset, Provider

PUBLIC_IP = "93.184.216.34"


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
        sent.append({"to": to, "subject": subject, "body": body})
        return True
    monkeypatch.setattr(mailer, "send_mail", fake)
    return sent


async def reg(c, email="anna@example.com", password="password1", nick="Анна"):
    r = await c.post("/auth/register", json={"email": email, "password": password, "nickname": nick})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def token_from(mail) -> str:
    m = re.search(r"/reset\?token=([A-Za-z0-9_\-]+)", mail["body"])
    assert m, mail["body"]
    return m.group(1)


async def test_login_locks_after_five_failures(client):
    await reg(client)
    for _ in range(5):
        r = await client.post("/auth/login", json={"email": "anna@example.com", "password": "wrong-pass"})
        assert r.status_code == 401
    r = await client.post("/auth/login", json={"email": "Anna@Example.com", "password": "password1"})
    assert r.status_code == 429
    assert "восстановите пароль" in r.json()["detail"] and int(r.headers["Retry-After"]) > 0
    # другой аккаунт не задет
    await reg(client, "boris@example.com", nick="Борис")
    assert (await client.post("/auth/login", json={"email": "boris@example.com", "password": "password1"})).status_code == 200
    # окно прошло - снова можно
    async with SessionLocal() as s:
        await s.execute(update(AuthAttempt).values(created_at=datetime.now(timezone.utc) - timedelta(minutes=16)))
        await s.commit()
    assert (await client.post("/auth/login", json={"email": "anna@example.com", "password": "password1"})).status_code == 200


async def test_success_resets_failure_counter(client):
    await reg(client)
    for _ in range(4):
        await client.post("/auth/login", json={"email": "anna@example.com", "password": "wrong-pass"})
    assert (await client.post("/auth/login", json={"email": "anna@example.com", "password": "password1"})).status_code == 200
    for _ in range(4):
        await client.post("/auth/login", json={"email": "anna@example.com", "password": "wrong-pass"})
    assert (await client.post("/auth/login", json={"email": "anna@example.com", "password": "password1"})).status_code == 200


async def test_ip_limit_uses_rightmost_public_address(client):
    """Перебор разных аккаунтов с одного адреса; подделанный левый X-Forwarded-For не помогает."""
    for i in range(30):
        h = {"X-Forwarded-For": f"10.0.0.{i}, {PUBLIC_IP}, 172.18.0.5"}
        r = await client.post("/auth/login", json={"email": f"x{i}@example.com", "password": "wrong-pass"}, headers=h)
        assert r.status_code == 401
    h = {"X-Forwarded-For": f"8.8.8.8, {PUBLIC_IP}"}
    r = await client.post("/auth/login", json={"email": "new@example.com", "password": "wrong-pass"}, headers=h)
    assert r.status_code == 429
    # другой адрес работает; без публичного адреса (локальная сеть) лимит по адресу не применяется
    other = {"X-Forwarded-For": "93.184.216.35"}
    assert (await client.post("/auth/login", json={"email": "new@example.com", "password": "wrong-pass"},
                              headers=other)).status_code == 401
    assert (await client.post("/auth/login", json={"email": "new2@example.com", "password": "wrong-pass"})).status_code == 401
    # адреса и email в базе только хешами
    async with SessionLocal() as s:
        keys = (await s.execute(select(AuthAttempt.key))).scalars().all()
    assert keys and not any("@" in k or "." in k for k in keys)


async def test_register_limit_per_address(client):
    h = {"X-Forwarded-For": PUBLIC_IP}
    for i in range(10):
        r = await client.post("/auth/register", json={"email": f"r{i}@example.com", "password": "password1",
                                                      "nickname": f"Игрок{i}"}, headers=h)
        assert r.status_code == 200, r.text
    r = await client.post("/auth/register", json={"email": "r10@example.com", "password": "password1",
                                                  "nickname": "Игрок10"}, headers=h)
    assert r.status_code == 429


async def test_password_reset_flow(client, mails):
    old = await reg(client)
    # неизвестный email - тот же ответ, письма нет
    assert (await client.post("/auth/password/forgot", json={"email": "nobody@example.com"})).status_code == 204
    assert mails == []

    assert (await client.post("/auth/password/forgot", json={"email": "ANNA@example.com"})).status_code == 204
    assert len(mails) == 1 and mails[0]["to"] == "anna@example.com" and "Анна" in mails[0]["body"]
    token = token_from(mails[0])
    async with SessionLocal() as s:
        stored = (await s.execute(select(PasswordReset.token_hash))).scalars().all()
    assert stored and token not in stored        # в базе только хеш

    assert (await client.post("/auth/password/reset", json={"token": token, "password": "short"})).status_code == 422
    r = await client.post("/auth/password/reset", json={"token": token, "password": "new-password1"})
    assert r.status_code == 200, r.text
    fresh = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert (await client.get("/auth/me", headers=fresh)).status_code == 200
    # старый токен входа больше не действует, ссылка одноразовая
    assert (await client.get("/auth/me", headers=old)).status_code == 401
    r = await client.post("/auth/password/reset", json={"token": token, "password": "another-pass1"})
    assert r.status_code == 400 and "Запросите новую" in r.json()["detail"]
    # новый пароль работает, старый - нет
    assert (await client.post("/auth/login", json={"email": "anna@example.com", "password": "password1"})).status_code == 401
    assert (await client.post("/auth/login", json={"email": "anna@example.com", "password": "new-password1"})).status_code == 200


async def test_reset_link_expires_and_older_links_die(client, mails):
    await reg(client)
    await client.post("/auth/password/forgot", json={"email": "anna@example.com"})
    await client.post("/auth/password/forgot", json={"email": "anna@example.com"})
    first, second = token_from(mails[0]), token_from(mails[1])
    async with SessionLocal() as s:
        await s.execute(update(PasswordReset).values(expires_at=datetime.now(timezone.utc) - timedelta(minutes=1)))
        await s.commit()
    assert (await client.post("/auth/password/reset", json={"token": second, "password": "new-password1"})).status_code == 400
    await client.post("/auth/password/forgot", json={"email": "anna@example.com"})
    third = token_from(mails[2])
    assert (await client.post("/auth/password/reset", json={"token": third, "password": "new-password1"})).status_code == 200
    assert (await client.post("/auth/password/reset", json={"token": first, "password": "new-password2"})).status_code == 400
    # четвёртый запрос за час - лимит
    r = await client.post("/auth/password/forgot", json={"email": "anna@example.com"})
    assert r.status_code == 429 and "Спам" in r.json()["detail"]


async def test_reset_also_sent_via_telegram(client, mails):
    await reg(client)
    async with SessionLocal() as s:
        uid = (await s.execute(select(AuthAccount.user_id))).scalar_one()
        s.add(AuthAccount(user_id=uid, provider=Provider.telegram, external_id="555111"))
        await s.commit()
    await client.post("/auth/password/forgot", json={"email": "anna@example.com"})
    async with SessionLocal() as s:
        msg = (await s.execute(select(OutboxMessage).where(OutboxMessage.kind == "password_reset"))).scalar_one()
    assert msg.chat_id == "555111" and "/reset?token=" in msg.buttons[0][0]["url"]


async def test_reset_clears_login_lock(client, mails):
    await reg(client)
    for _ in range(5):
        await client.post("/auth/login", json={"email": "anna@example.com", "password": "wrong-pass"})
    assert (await client.post("/auth/login", json={"email": "anna@example.com", "password": "password1"})).status_code == 429
    await client.post("/auth/password/forgot", json={"email": "anna@example.com"})
    assert (await client.post("/auth/password/reset", json={"token": token_from(mails[0]),
                                                            "password": "new-password1"})).status_code == 200
    assert (await client.post("/auth/login", json={"email": "anna@example.com", "password": "new-password1"})).status_code == 200


async def test_change_password(client):
    h = await reg(client)
    r = await client.post("/auth/password/change", json={"old_password": "nope-nope", "new_password": "new-password1"},
                          headers=h)
    assert r.status_code == 400
    r = await client.post("/auth/password/change", json={"old_password": "password1", "new_password": "new-password1"},
                          headers=h)
    assert r.status_code == 200
    assert (await client.get("/auth/me", headers=h)).status_code == 401
    assert (await client.get("/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"})).status_code == 200
    assert (await client.post("/auth/login", json={"email": "anna@example.com", "password": "new-password1"})).status_code == 200


async def test_mailer_without_smtp_logs_message(caplog):
    import logging
    caplog.set_level(logging.WARNING, logger="mailer")
    assert await mailer.send_mail("a@example.com", "Тема", "ссылка http://x/reset?token=abc") is False
    assert "reset?token=abc" in caplog.text
