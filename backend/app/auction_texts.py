"""Тексты аукциона для Telegram (HTML)."""
from datetime import datetime

from .auction import CONDITIONS, money
from .reports import esc, fmt_dt

CAPTION_LIMIT = 1024


def post_url(chat_id: str | None, message_id: int | None) -> str | None:
    if not chat_id or not message_id:
        return None
    if chat_id.startswith("@"):
        return f"https://t.me/{chat_id[1:]}/{message_id}"
    if chat_id.startswith("-100"):
        return f"https://t.me/c/{chat_id[4:]}/{message_id}"
    return None


def user_link(nickname: str, tg_id: int | str | None, username: str | None) -> str:
    if username:
        return f"@{esc(username)}"
    if tg_id:
        return f'<a href="tg://user?id={tg_id}">{esc(nickname)}</a>'
    return esc(nickname)


def rating_line(avg: float | None, count: int) -> str:
    return f"⭐ {avg:.1f} ({count})" if count else "новый продавец"


def lot_caption(*, lot_id: int, title: str, condition: str, seller: str, seller_avg: float | None,
                seller_count: int, start_price: int, current_price: int | None, leader: str | None,
                bids: int, ends_at: datetime, status: str, next_bid: int, tz: str,
                seller_no: int | None = None) -> str:
    who = esc(seller) + (f" (№{seller_no})" if seller_no else "")
    lines = [f"🃏 <b>{esc(title[:100])}</b>  #лот{lot_id}",
             f"Состояние: {condition} — {CONDITIONS.get(condition, '')}",
             f"Продавец: {who} · {rating_line(seller_avg, seller_count)}", ""]
    if status == "active":
        if current_price is None:
            lines.append(f"💰 Старт: <b>{money(start_price)}</b>, ставок пока нет")
        else:
            lines += [f"💰 Текущая ставка: <b>{money(current_price)}</b>",
                      f"👤 Лидер: {esc(leader or '?')} · ставок: {bids}"]
        lines += [f"➕ Следующая ставка от {money(next_bid)}",
                  f"⏳ Окончание: {fmt_dt(ends_at, tz)}",
                  "<i>Ставка в последние 5 минут продлевает торги на 5 минут</i>"]
    elif status == "sold":
        lines.append(f"✅ Продано за <b>{money(current_price or 0)}</b> · ставок: {bids}")
    elif status == "unsold":
        lines.append("⌛ Торги завершены без ставок")
    else:
        lines.append("❌ Лот снят с торгов")
    text = "\n".join(lines)
    return text[:CAPTION_LIMIT]


def outbid_text(title: str, amount: int, url: str | None) -> str:
    link = f'\n<a href="{esc(url)}">Перейти к лоту</a>' if url else ""
    return f"⚠️ Вашу ставку на «{esc(title)}» перебили: теперь {money(amount)}.{link}"


def won_text(title: str, price: int, seller_contact: str) -> str:
    return (f"🎉 Вы выиграли лот «{esc(title)}» за <b>{money(price)}</b>!\n\n"
            f"Продавец: {seller_contact}. Напишите ему, чтобы договориться об оплате и передаче карты. "
            "Платежи проходят напрямую между вами, платформа в них не участвует.\n\n"
            "Когда всё будет готово, отметьте результат сделки кнопкой ниже.")


def sold_text(title: str, price: int, buyer_contact: str) -> str:
    return (f"💰 Ваш лот «{esc(title)}» продан за <b>{money(price)}</b>.\n\n"
            f"Покупатель: {buyer_contact}. Свяжитесь, чтобы договориться об оплате и передаче.\n\n"
            "Когда всё будет готово, отметьте результат сделки кнопкой ниже.")


def unsold_text(title: str) -> str:
    return f"⌛ Торги по лоту «{esc(title)}» завершились без ставок. Можно выставить его заново командой /sell."


def rate_text(title: str, role_of_other: str) -> str:
    who = "продавца" if role_of_other == "seller" else "покупателя"
    return f"🤝 Сделка по лоту «{esc(title)}» подтверждена обеими сторонами. Оцените {who} от 1 до 5:"


def deal_closed_text(title: str, status: str) -> str:
    if status == "failed":
        return f"Сделка по лоту «{esc(title)}» отмечена как несостоявшаяся обеими сторонами."
    return (f"По лоту «{esc(title)}» ответы сторон расходятся. Администратор рассмотрит ситуацию; "
            "при необходимости оставьте жалобу на сайте.")


def deal_buttons(deal_id: int) -> list[list[dict]]:
    return [[{"text": "✅ Сделка состоялась", "callback_data": f"deal:{deal_id}:ok"},
             {"text": "❌ Не состоялась", "callback_data": f"deal:{deal_id}:fail"}]]


def rate_buttons(deal_id: int) -> list[list[dict]]:
    return [[{"text": "⭐" * n if n <= 3 else f"{n}⭐", "callback_data": f"rate:{deal_id}:{n}"} for n in range(1, 6)]]


def rating_card(nickname: str, player_no: int | None, r: dict) -> str:
    """Ответ бота на /rating и /id: репутация игрока на аукционе."""
    def part(avg, n):
        return f"⭐ {avg:.1f} из 5, оценок: {n}" if n else "оценок пока нет"
    head = f"<b>{esc(nickname)}</b>" + (f", номер игрока <b>{player_no}</b>" if player_no else "")
    return "\n".join([head,
                      f"Как продавец: {part(r['seller_avg'], r['seller_count'])}",
                      f"Как покупатель: {part(r['buyer_avg'], r['buyer_count'])}",
                      f"Состоявшихся сделок: {r['deals_completed']}"])
