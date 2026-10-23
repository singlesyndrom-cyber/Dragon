"""ВКонтакте в процессе бота: рассылка очереди outbox (беседы, личные сообщения, стена) и Bots Long Poll
сообществ клубов - нажатия кнопок «Записаться» / «Отменить» и привязка беседы по коду."""
import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from .. import noticeimages, tg_actions, vk, vkclub
from ..botutil import MAX_ATTEMPTS, backoff_seconds
from ..db import SessionLocal
from ..models import Club, ClubVk, ClubVkChat, OutboxMessage, OutboxStatus, Provider

log = logging.getLogger("vk")


# ---------- рассылка ----------
async def deliver(session, m: OutboxMessage) -> None:
    if m.channel == "vk":
        club_id, peer = m.chat_id.split(":", 1)
        cfg = await session.get(ClubVk, int(club_id))
        token = vkclub.group_token(cfg)
        if not token:
            raise vk.VkError(5, "у клуба не настроен токен сообщества VK")
        attachment = None
        if m.photo_url:   # картинка оповещения: загружаем в VK один раз; не вышло - сообщение уходит без неё
            try:
                attachment = await noticeimages.vk_attachment(session, int(club_id), cfg.group_id, token, int(peer),
                                                              m.photo_url)
            except Exception as e:  # noqa: BLE001
                log.warning("vk картинка %s: %r", m.photo_url, e)
                cfg.last_error = f"картинка не загрузилась в VK: {e or repr(e)}"[:500]
        # random_id = номер сообщения в очереди: VK не отправит дубль, если повторим после сбоя
        await vk.send_message(token, int(peer), vk.html_to_text(m.text), m.buttons, random_id=m.id,
                              attachment=attachment)
        if attachment and cfg.last_error and cfg.last_error.startswith("картинка"):
            cfg.last_error = None              # картинки снова доходят - старая ошибка больше не актуальна
    elif m.channel == "vkwall":
        cfg = await session.get(ClubVk, int(m.chat_id))
        if not cfg or not cfg.group_id:
            raise vk.VkError(5, "VK клуба не настроен")
        token = await vkclub.wall_token(session, cfg)
        if not token:
            raise vk.VkError(5, "стена не подключена: нет токена администратора")
        await vk.wall_post(token, cfg.group_id, vk.html_to_text(m.text), link=m.photo_url)
    else:
        raise ValueError(f"не VK-канал: {m.channel}")


async def process_batch() -> int:
    now = datetime.now(timezone.utc)
    async with SessionLocal() as s:
        msgs = (await s.execute(select(OutboxMessage).where(
            OutboxMessage.status == OutboxStatus.pending, OutboxMessage.next_attempt_at <= now,
            OutboxMessage.channel.in_(["vk", "vkwall"])).order_by(OutboxMessage.id).limit(20))).scalars().all()
        for m in msgs:
            try:
                await deliver(s, m)
                m.status, m.sent_at, m.last_error = OutboxStatus.sent, datetime.now(timezone.utc), None
            except vk.VkError as e:
                m.attempts += 1
                m.last_error = str(e)[:500]
                if e.permanent or m.attempts >= MAX_ATTEMPTS:
                    m.status = OutboxStatus.failed
                    log.warning("vk outbox %s failed: %s", m.id, e)
                    await _remember_error(s, m, str(e))
                else:            # 6/9 - слишком часто, 10 - сбой VK: повтор позже
                    m.next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=backoff_seconds(m.attempts))
            except Exception as e:  # noqa: BLE001  сеть
                m.attempts += 1
                m.last_error = repr(e)[:500]
                if m.attempts >= MAX_ATTEMPTS:
                    m.status = OutboxStatus.failed
                else:
                    m.next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=backoff_seconds(m.attempts))
            await s.commit()
            await asyncio.sleep(0.1)   # VK: не больше ~20 запросов в секунду на сообщество
        return len(msgs)


async def _remember_error(s, m: OutboxMessage, err: str) -> None:
    """Последняя ошибка беседы или стены видна владельцу в настройках VK клуба (личные сообщения - нет:
    игрок мог просто не разрешить сообщения от сообщества)."""
    club_id = int(m.chat_id.split(":")[0])
    if m.channel == "vk" and int(m.chat_id.split(":")[1]) < vkclub.PEER_CHAT_BASE:
        return
    cfg = await s.get(ClubVk, club_id)
    if cfg:
        cfg.last_error = f"{datetime.now(timezone.utc):%d.%m %H:%M} UTC · {'стена' if m.channel == 'vkwall' else 'беседа'}: {err}"[:500]


async def outbox_loop() -> None:
    while True:
        try:
            n = await process_batch()
        except Exception:  # noqa: BLE001
            log.exception("vk outbox batch")
            n = 0
        await asyncio.sleep(0.5 if n else 3)


# ---------- Long Poll: кнопки и привязка беседы ----------
ACTIONS = {"reg": tg_actions.register, "unreg": tg_actions.unregister, "bcancel": tg_actions.cancel_booking}


async def handle_update(club_id: int, upd: dict) -> None:
    kind, obj = upd.get("type"), upd.get("object") or {}
    async with SessionLocal() as s:
        cfg = await s.get(ClubVk, club_id)
        token = vkclub.group_token(cfg)
        if not token:
            return
        if kind == "message_event":
            await _button(s, cfg, token, obj)
        elif kind == "message_new":
            await _message(s, cfg, token, obj.get("message") or obj)


async def _button(s, cfg: ClubVk, token: str, obj: dict) -> None:
    payload = obj.get("payload") or {}
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            payload = {}
    cmd, _, arg = str(payload.get("cmd", "")).partition(":")
    action = ACTIONS.get(cmd)
    user_id, peer_id = int(obj.get("user_id", 0)), int(obj.get("peer_id", 0))
    if not action or not arg.isdigit() or not user_id:
        return
    try:
        names = await vk.users_names(token, [user_id])
        text = await action(s, user_id, None, names.get(user_id), int(arg), provider=Provider.vk)
    except Exception:  # noqa: BLE001
        log.exception("vk кнопка %s", payload)
        text = "Не получилось, попробуйте ещё раз или запишитесь на сайте."
    await vk.answer_event(token, obj.get("event_id", ""), user_id, peer_id, vk.html_to_text(text))


async def _message(s, cfg: ClubVk, token: str, msg: dict) -> None:
    text, peer_id = (msg.get("text") or "").strip(), int(msg.get("peer_id", 0))
    if cfg.bind_code and cfg.bind_code in text and peer_id >= vkclub.PEER_CHAT_BASE:
        game = cfg.bind_game if cfg.bind_game in vkclub.GAMES else "all"
        chat = (await s.execute(select(ClubVkChat).where(ClubVkChat.club_id == cfg.club_id,
                                                         ClubVkChat.game == game))).scalar_one_or_none()
        if not chat:
            chat = ClubVkChat(club_id=cfg.club_id, game=game, peer_id=peer_id)
            s.add(chat)
        chat.peer_id, chat.title = peer_id, await vk.chat_title(token, peer_id)
        cfg.bind_code, cfg.bind_game, cfg.last_error = None, None, None
        club = await s.get(Club, cfg.club_id)
        await s.commit()
        what = ("новости клуба и турниры игр без своей беседы" if game == "all"
                else f"анонсы турниров «{vkclub.GAMES[game]}» с записью и итоги")
        await vk.send_message(token, peer_id, f"Беседа подключена к клубу «{club.name if club else ''}». "
                                              f"Сюда будут приходить {what}.", random_id=0)
    elif peer_id < vkclub.PEER_CHAT_BASE and text.lower() in ("начать", "start", "старт", "привет"):
        club = await s.get(Club, cfg.club_id)
        await vk.send_message(token, peer_id, f"Здравствуйте! Это сообщество клуба «{club.name if club else ''}». "
                              "Здесь будут напоминания о турнирах и бронях — для этого войдите на сайт через VK "
                              "или привяжите VK в личном кабинете.", random_id=0)


async def poll_club(club_id: int, group_id: int, token: str) -> None:
    """Long Poll одного сообщества; при ошибках - пауза и новое подключение."""
    while True:
        try:
            srv = await vk.longpoll_server(token, group_id)
            server, key, ts = srv["server"], srv["key"], str(srv["ts"])
            while True:
                r = await vk.longpoll_check(server, key, ts)
                if "failed" in r:
                    if r["failed"] == 1:
                        ts = str(r.get("ts", ts))
                        continue
                    break                                   # 2, 3 - ключ устарел: заново getLongPollServer
                ts = str(r.get("ts", ts))
                for upd in r.get("updates", []):
                    try:
                        await handle_update(club_id, upd)
                    except Exception:  # noqa: BLE001
                        log.exception("vk update клуба %s", club_id)
        except asyncio.CancelledError:
            raise
        except vk.VkError as e:
            log.warning("vk long poll клуба %s: %s", club_id, e)
            await asyncio.sleep(60 if e.permanent else 10)
        except Exception as e:  # noqa: BLE001
            log.warning("vk long poll клуба %s: %r", club_id, e)
            await asyncio.sleep(10)


async def longpoll_manager() -> None:
    """Раз в 30 с сверяет настроенные клубы и держит по одному Long Poll на сообщество."""
    running: dict[int, tuple[asyncio.Task, tuple]] = {}
    while True:
        try:
            async with SessionLocal() as s:
                cfgs = (await s.execute(select(ClubVk).where(ClubVk.group_id.is_not(None),
                                                             ClubVk.group_token.is_not(None)))).scalars().all()
                want = {c.club_id: (c.group_id, vkclub.group_token(c)) for c in cfgs}
            want = {k: v for k, v in want.items() if v[1]}
            for club_id, (task, key) in list(running.items()):
                if want.get(club_id) != key or task.done():
                    task.cancel()
                    del running[club_id]
            for club_id, key in want.items():
                if club_id not in running:
                    running[club_id] = (asyncio.create_task(poll_club(club_id, *key)), key)
        except Exception:  # noqa: BLE001
            log.exception("vk long poll manager")
        await asyncio.sleep(30)
