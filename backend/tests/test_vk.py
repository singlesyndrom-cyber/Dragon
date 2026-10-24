"""VK клуба: настройки, беседа по коду, анонс в беседу и на стену, кнопка записи, личные напоминания, вход VK ID,
обновление токена стены, ошибки доставки. VK API подменён (httpx.MockTransport). RUN_INTEGRATION=1."""
import json
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs

import httpx
import pytest

from app import vk

pytestmark_db = pytest.mark.skipif(not os.getenv("RUN_INTEGRATION"), reason="нужен PostgreSQL (RUN_INTEGRATION=1)")


def test_html_to_text_and_keyboard():
    assert vk.html_to_text('🏆 <b>Итоги</b> &amp; <a href="https://x/t/1">таблица</a><br>ok') == "🏆 Итоги & таблица: https://x/t/1\nok"
    assert vk.html_to_text('<a href="https://x">https://x</a>') == "https://x"
    kb = vk.keyboard([[{"text": "✅ Записаться", "callback_data": "reg:5"}], [{"text": "Сайт", "url": "https://x"}]])
    assert kb["inline"] is True
    assert kb["buttons"][0][0]["action"] == {"type": "callback", "label": "✅ Записаться", "payload": '{"cmd": "reg:5"}'}
    assert kb["buttons"][1][0]["action"]["type"] == "open_link"
    assert vk.keyboard(None) is None


if os.getenv("RUN_INTEGRATION"):
    from sqlalchemy import select, update

    from app import tg_actions, vkclub
    from app.bot import vk as vk_bot
    from app.config import settings
    from app.db import Base, SessionLocal, engine
    from app.main import app
    from app.models import AuthAccount, ClubVk, OutboxMessage, OutboxStatus, Provider, TournamentPlayer
    from tests.helpers import make_creator


class FakeVk:
    """Подменённые VK API и VK ID: запоминает вызовы, ответы - по методу."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.errors: dict[str, tuple[int, str]] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        if url.startswith(vk.VKID):
            path = url[len(vk.VKID):]
            self.calls.append((path, form))
            if path == "/oauth2/auth" and form["grant_type"] == "authorization_code":
                if form["code"] == "bad":
                    return httpx.Response(400, json={"error": "invalid_grant", "error_description": "code expired"})
                return httpx.Response(200, json={"access_token": "at-" + form["code"], "refresh_token": "rt-1",
                                                 "expires_in": 3600, "user_id": 777,
                                                 "scope": "vkid.personal_info,wall,groups" if form["code"] == "wall" else "vkid.personal_info"})
            if path == "/oauth2/auth":
                return httpx.Response(200, json={"access_token": "at-new", "refresh_token": "rt-2", "expires_in": 3600})
            if path == "/oauth2/user_info":
                return httpx.Response(200, json={"user": {"user_id": "777", "first_name": "Иван", "last_name": "Вк"}})
        method = url.rsplit("/", 1)[-1]
        self.calls.append((method, form))
        if method in self.errors:
            code, msg = self.errors[method]
            return httpx.Response(200, json={"error": {"error_code": code, "error_msg": msg}})
        resp = {"groups.getById": {"groups": [{"id": 4242, "name": "Клуб Дракон"}], "profiles": []},
                "groups.setLongPollSettings": 1, "messages.send": 1, "messages.sendMessageEventAnswer": 1,
                "wall.post": {"post_id": 99},
                "messages.getConversationsById": {"items": [{"chat_settings": {"title": "Клуб Дракон MTG"}}]},
                "users.get": [{"id": 555, "first_name": "Пётр", "last_name": "Вконтактов"}]}.get(method, 1)
        return httpx.Response(200, json={"response": resp})

    def of(self, method):
        return [f for m, f in self.calls if m == method]


@pytest.fixture
async def ctx(monkeypatch):
    fake = FakeVk()
    monkeypatch.setattr(vk, "transport", httpx.MockTransport(fake))
    monkeypatch.setattr(settings, "vk_app_id", "51234")
    monkeypatch.setattr(settings, "public_base_url", "https://dragon.test")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/auth/register", json={"email": "o@example.com", "password": "password1", "nickname": "Орг"})
        org = {"Authorization": f"Bearer {r.json()['access_token']}"}
        await make_creator(c, org)
        cid = (await c.post("/clubs", json={"name": "Дракон"}, headers=org)).json()["id"]
        yield c, fake, org, cid
    await engine.dispose()


async def outbox(channel=None):
    async with SessionLocal() as s:
        q = select(OutboxMessage).order_by(OutboxMessage.id)
        if channel:
            q = q.where(OutboxMessage.channel == channel)
        return (await s.execute(q)).scalars().all()


@pytestmark_db
async def test_club_vk_setup_bind_announce_and_button(ctx):
    c, fake, org, cid = ctx
    base = f"/clubs/{cid}/vk"
    r = await c.put(base, json={"group_token": "vk1.a.group-secret"}, headers=org)
    assert r.status_code == 200, r.text
    v = r.json()
    assert (v["group_id"], v["group_name"], v["has_group_token"], v["warnings"]) == (4242, "Клуб Дракон", True, [])
    assert "group-secret" not in json.dumps((await c.get(base, headers=org)).json())        # токен наружу не отдаётся
    async with SessionLocal() as s:
        raw = (await s.get(ClubVk, cid)).group_token
    assert raw and "group-secret" not in raw                                                 # в базе - зашифрован
    assert fake.of("groups.setLongPollSettings")[0]["message_event"] == "1"
    assert (await c.get(base)).status_code == 401

    # беседы по коду: MTG - 2000000003, «все игры» - 2000000004
    async def bind(game, peer):
        code = (await c.post(f"{base}/bind", json={"game": game}, headers=org)).json()["bind_code"]
        await vk_bot.handle_update(cid, {"type": "message_new", "object": {"message": {
            "text": f"@club4242 {code}", "peer_id": peer, "from_id": 1}}})
    await bind("mtg", 2000000003)
    v = (await c.get(base, headers=org)).json()
    assert v["chats"] == [{"id": v["chats"][0]["id"], "game": "mtg", "peer_id": 2000000003, "title": "Клуб Дракон MTG"}]
    assert v["bind_code"] is None
    assert "«Magic: The Gathering»" in fake.of("messages.send")[-1]["message"]
    await bind("all", 2000000004)
    assert (await c.post(f"{base}/bind", json={"game": "chess"}, headers=org)).status_code == 422

    # стена: токен администратора вручную
    r = await c.put(f"{base}/wall/token", json={"token": "vk1.a.admin-user-token"}, headers=org)
    assert r.json()["wall_connected"] and r.json()["wall_enabled"] and r.json()["wall_user_name"] == "Пётр Вконтактов"

    # турнир на завтра: анонс уходит в беседу (с кнопкой) и на стену (ссылкой); Telegram-чата у клуба нет
    when = (datetime.now(timezone.utc) + timedelta(hours=20)).replace(tzinfo=None, microsecond=0).isoformat()
    tid = (await c.post("/tournaments", json={"club_id": cid, "name": "Командир", "format": "edh", "starts_at": when,
                                              "max_players": 8}, headers=org)).json()["id"]
    assert [m.chat_id for m in await outbox("vk")] == [f"{cid}:2000000003"]          # MTG - только в беседу MTG
    assert [m.chat_id for m in await outbox("vkwall")] == [str(cid)] and await outbox("tg") == []
    assert await vk_bot.process_batch() == 2
    sent = fake.of("messages.send")[-1]
    assert sent["peer_id"] == "2000000003" and "<b>" not in sent["message"] and "Командир" in sent["message"]
    assert json.loads(sent["keyboard"])["buttons"][0][0]["action"]["payload"] == json.dumps({"cmd": f"reg:{tid}"})
    post = fake.of("wall.post")[-1]
    assert (post["owner_id"], post["from_group"], post["attachments"]) == ("-4242", "1", f"https://dragon.test/tournaments/{tid}")
    assert {m.status for m in await outbox()} == {OutboxStatus.sent}

    # кнопка «Записаться» в беседе: VK 555 не привязан к номеру игрока - открывается ссылка на подтверждение
    await vk_bot.handle_update(cid, {"type": "message_event", "object": {
        "user_id": 555, "peer_id": 2000000003, "event_id": "ev1", "payload": {"cmd": f"reg:{tid}"}}})
    ans = json.loads(fake.of("messages.sendMessageEventAnswer")[-1]["event_data"])
    assert ans["type"] == "open_link" and ans["link"].startswith("https://dragon.test/link/")
    code = ans["link"].rsplit("/", 1)[1]
    assert (await c.get(f"/auth/link-code/{code}")).json()["who"] == "Пётр Вконтактов"
    r = (await c.post(f"/auth/link-code/{code}/new")).json()          # аккаунта на сайте не было - создан
    assert "записаны" in r["message"]
    # повторное нажатие: VK уже привязан - всплывающий ответ
    await vk_bot.handle_update(cid, {"type": "message_event", "object": {
        "user_id": 555, "peer_id": 2000000003, "event_id": "ev2", "payload": {"cmd": f"reg:{tid}"}}})
    ans = fake.of("messages.sendMessageEventAnswer")[-1]
    assert ans["user_id"] == "555" and "уже записаны" in json.loads(ans["event_data"])["text"]
    async with SessionLocal() as s:
        uid = (await s.execute(select(AuthAccount.user_id).where(AuthAccount.provider == Provider.vk,
                                                                AuthAccount.external_id == "555"))).scalar_one()
        assert (await s.execute(select(TournamentPlayer.user_id).where(TournamentPlayer.tournament_id == tid))).scalars().all() == [uid]
    card = (await c.get(f"/tournaments/{tid}")).json()
    assert [p["nickname"] for p in card["participants"]] == ["Пётр Вконтактов"]

    # напоминание за сутки - в личку от сообщества клуба
    async with SessionLocal() as s:
        assert await tg_actions.tournament_reminders(s) == 1
    dm = [m for m in await outbox("vk") if m.kind == "tournament_reminder"]
    assert [m.chat_id for m in dm] == [f"{cid}:555"]

    # игрок не разрешил сообщения (901): ошибка постоянная, но в настройки клуба не пишется
    fake.errors["messages.send"] = (901, "Can't send messages for users without permission")
    await vk_bot.process_batch()
    assert [m.status for m in await outbox("vk") if m.kind == "tournament_reminder"] == [OutboxStatus.failed]
    assert (await c.get(base, headers=org)).json()["last_error"] is None
    # бота выгнали из беседы (917) - владелец видит ошибку в настройках
    await c.post(f"{base}/test", json={"target": "chat"}, headers=org)
    fake.errors["messages.send"] = (917, "You don't have access to this chat")
    await vk_bot.process_batch()
    assert "беседа" in (await c.get(base, headers=org)).json()["last_error"]

    # Берсерк: своей беседы нет - анонс в беседу «все игры»; назначили беседе игру - уходит туда
    when2 = (datetime.now(timezone.utc) + timedelta(days=2)).replace(tzinfo=None, microsecond=0).isoformat()
    bid = (await c.post("/tournaments", json={"club_id": cid, "name": "Берсерк-кубок", "game": "berserk",
                                              "starts_at": when2}, headers=org)).json()["id"]
    assert [m.chat_id for m in await outbox("vk") if (m.dedup_key or "").startswith(f"t-announce:{bid}")] == [f"{cid}:2000000004"]
    chats = (await c.get(base, headers=org)).json()["chats"]
    allchat = next(x for x in chats if x["game"] == "all")
    v = (await c.patch(f"{base}/chats/{allchat['id']}", json={"game": "berserk"}, headers=org)).json()
    assert sorted(x["game"] for x in v["chats"]) == ["berserk", "mtg"]
    v = (await c.delete(f"{base}/chats/{allchat['id']}", headers=org)).json()
    assert [x["game"] for x in v["chats"]] == ["mtg"]

    # отключение VK клуба
    assert (await c.delete(base, headers=org)).status_code == 204
    assert (await c.get(base, headers=org)).json()["has_group_token"] is False


@pytestmark_db
async def test_vkid_login_link_and_wall_refresh(ctx):
    c, fake, org, cid = ctx
    cfg = (await c.get("/auth/vk/config")).json()
    assert cfg == {"enabled": True, "app_id": "51234", "redirect_uri": "https://dragon.test/auth/vk"}
    body = {"code": "c1", "device_id": "dev1", "code_verifier": "v" * 50, "state": "s" * 32}
    r = await c.post("/auth/vk", json=body)
    assert r.status_code == 200, r.text
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    me = (await c.get("/auth/me", headers=h)).json()
    assert me["nickname"] == "Иван Вк" and me["providers"] == ["vk"]
    ex = fake.of("/oauth2/auth")[0]
    assert (ex["code_verifier"], ex["device_id"], ex["redirect_uri"], ex["client_id"]) == ("v" * 50, "dev1", "https://dragon.test/auth/vk", "51234")
    assert (await c.post("/auth/vk", json=body)).json()["access_token"]                   # тот же VK - тот же аккаунт
    assert (await c.post("/auth/vk/link", json=body, headers=org)).status_code == 409     # уже чужой
    assert (await c.post("/auth/vk", json={**body, "code": "bad"})).status_code == 401

    # стена через VK ID: без права wall - отказ; с правом - токены с обновлением
    await c.put(f"/clubs/{cid}/vk", json={"group_token": "vk1.a.group"}, headers=org)
    r = await c.post(f"/clubs/{cid}/vk/wall/vkid", json=body, headers=org)
    assert r.status_code == 400 and "выданы: vkid.personal_info" in r.json()["detail"]
    r = await c.post(f"/clubs/{cid}/vk/wall/vkid", json={**body, "code": "wall"}, headers=org)
    assert r.status_code == 200 and r.json()["wall_mode"] == "vkid" and r.json()["wall_user_name"] == "Иван Вк"
    async with SessionLocal() as s:
        cfg = await s.get(ClubVk, cid)
        assert await vkclub.wall_token(s, cfg) == "at-wall"                                  # ещё свежий
        await s.execute(update(ClubVk).values(wall_expires_at=datetime.now(timezone.utc)))
        await s.commit()
    async with SessionLocal() as s:
        cfg = await s.get(ClubVk, cid)
        assert await vkclub.wall_token(s, cfg) == "at-new"
    assert fake.of("/oauth2/auth")[-1] == {"grant_type": "refresh_token", "refresh_token": "rt-1", "device_id": "dev1",
                                           "client_id": "51234"}
    async with SessionLocal() as s:
        assert await vkclub.wall_token(s, await s.get(ClubVk, cid)) == "at-new"           # обновлённый сохранён
    assert (await c.delete(f"/clubs/{cid}/vk/wall", headers=org)).json()["wall_connected"] is False
