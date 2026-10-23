"""ВКонтакте: VK API (сообщения сообщества, стена, Long Poll) и VK ID (вход на сайт, токен для стены).

Сервер ходит в VK напрямую (из России VK доступен без прокси). Тесты подменяют транспорт: vk.transport = MockTransport.
"""
import html
import json
import re
from typing import Any

import httpx

from .config import settings

API = "https://api.vk.com/method/"
API_VERSION = "5.199"
VKID = "https://id.vk.ru"
transport: httpx.AsyncBaseTransport | None = None     # подмена в тестах

# ошибки, после которых повтор бессмысленен: нет прав, неверный токен, пользователь не разрешил сообщения и т.п.
PERMANENT = {5, 7, 15, 27, 100, 113, 900, 901, 902, 917, 925, 945, 946}


class VkError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(f"VK {code}: {message}")
        self.code, self.message = code, message

    @property
    def permanent(self) -> bool:
        return self.code in PERMANENT


def client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=transport, timeout=40)


async def call(method: str, token: str, **params: Any) -> Any:
    data = {k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v)
            for k, v in params.items() if v is not None}
    data.update(access_token=token, v=API_VERSION)
    async with client() as c:
        r = await c.post(API + method, data=data)
    r.raise_for_status()
    body = r.json()
    if "error" in body:
        e = body["error"]
        raise VkError(int(e.get("error_code", 0)), str(e.get("error_msg", "")))
    return body.get("response")


# ---------- текст и кнопки ----------
_A = re.compile(r'<a\s+href="([^"]+)"[^>]*>(.*?)</a>', re.S | re.I)


def html_to_text(s: str) -> str:
    """Сообщения платформы свёрстаны для Telegram (HTML). В VK - простой текст; ссылки - «текст: адрес»."""
    s = _A.sub(lambda m: m.group(2) if m.group(2).strip() == m.group(1) else f"{m.group(2)}: {m.group(1)}", s)
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    return html.unescape(s).strip()


def keyboard(buttons: list | None) -> dict | None:
    """Кнопки Telegram ([[{"text", "callback_data"|"url"}]]) -> inline-клавиатура VK (callback / open_link)."""
    if not buttons:
        return None
    rows = []
    for row in buttons[:6]:
        out = []
        for b in row[:4]:
            label = b["text"][:40]
            if b.get("url"):
                out.append({"action": {"type": "open_link", "link": b["url"], "label": label}})
            elif b.get("callback_data"):
                out.append({"action": {"type": "callback", "label": label, "payload": json.dumps({"cmd": b["callback_data"]})},
                            "color": "positive" if label.startswith("✅") else "secondary"})
        if out:
            rows.append(out)
    return {"inline": True, "buttons": rows} if rows else None


# ---------- сообщество ----------
async def group_info(token: str) -> dict:
    """Токен сообщества -> само сообщество (id, название)."""
    resp = await call("groups.getById", token)
    groups = resp.get("groups", resp) if isinstance(resp, dict) else resp
    g = groups[0]
    return {"id": int(g["id"]), "name": g.get("name") or f"club{g['id']}"}


async def enable_longpoll(token: str, group_id: int) -> None:
    """Включить Bots Long Poll с событиями «новое сообщение» и «нажатие кнопки»."""
    await call("groups.setLongPollSettings", token, group_id=group_id, enabled=1, api_version=API_VERSION,
               message_new=1, message_event=1)


async def send_message(token: str, peer_id: int, text: str, buttons: list | None = None, random_id: int = 0) -> None:
    await call("messages.send", token, peer_id=peer_id, random_id=random_id, message=text[:4000],
               keyboard=keyboard(buttons), dont_parse_links=1)


async def answer_event(token: str, event_id: str, user_id: int, peer_id: int, text: str) -> None:
    """Ответ на нажатие callback-кнопки: всплывающее уведомление у нажавшего."""
    await call("messages.sendMessageEventAnswer", token, event_id=event_id, user_id=user_id, peer_id=peer_id,
               event_data={"type": "show_snackbar", "text": text[:90]})


async def users_names(token: str, ids: list[int]) -> dict[int, str]:
    if not ids:
        return {}
    resp = await call("users.get", token, user_ids=",".join(map(str, ids)))
    return {int(u["id"]): f"{u.get('first_name', '')} {u.get('last_name', '')}".strip() for u in resp}


async def longpoll_server(token: str, group_id: int) -> dict:
    return await call("groups.getLongPollServer", token, group_id=group_id)


async def longpoll_check(server: str, key: str, ts: str, wait: int = 25) -> dict:
    async with client() as c:
        r = await c.get(server, params={"act": "a_check", "key": key, "ts": ts, "wait": wait}, timeout=wait + 15)
    r.raise_for_status()
    return r.json()


async def wall_post(token: str, group_id: int, text: str, link: str | None = None) -> int:
    resp = await call("wall.post", token, owner_id=-group_id, from_group=1, message=text[:15000], attachments=link)
    return int(resp.get("post_id", 0)) if isinstance(resp, dict) else 0


# ---------- VK ID ----------
def vkid_enabled() -> bool:
    return bool(settings.vk_app_id)


async def _vkid(path: str, data: dict) -> dict:
    async with client() as c:
        r = await c.post(VKID + path, data={k: v for k, v in data.items() if v is not None})
    body = r.json() if r.content else {}
    if r.status_code >= 400 or "error" in body:
        raise VkError(r.status_code, str(body.get("error_description") or body.get("error") or r.text)[:300])
    return body


async def exchange_code(code: str, code_verifier: str, device_id: str, redirect_uri: str, state: str | None = None) -> dict:
    """Код из редиректа VK ID -> access_token, refresh_token, user_id, expires_in, scope."""
    return await _vkid("/oauth2/auth", {"grant_type": "authorization_code", "code": code, "code_verifier": code_verifier,
                                        "device_id": device_id, "client_id": settings.vk_app_id,
                                        "redirect_uri": redirect_uri, "state": state})


async def refresh_token(refresh: str, device_id: str) -> dict:
    return await _vkid("/oauth2/auth", {"grant_type": "refresh_token", "refresh_token": refresh, "device_id": device_id,
                                        "client_id": settings.vk_app_id})


async def user_info(access_token: str) -> dict:
    """{user_id, first_name, last_name, avatar, ...}"""
    body = await _vkid("/oauth2/user_info", {"access_token": access_token, "client_id": settings.vk_app_id})
    return body.get("user") or {}
