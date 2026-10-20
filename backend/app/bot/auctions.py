"""Аукционы в боте: /sell (пошаговое создание лота), ставки из канала и в личке, сделки и оценки."""
import asyncio
import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select

from .. import auction_service as svc
from ..auction import CONDITIONS, DURATIONS_H, MIN_START, AuctionError, money, parse_price
from ..auction_texts import lot_caption, post_url, rating_card
from ..botutil import parse_chat_id
from ..config import settings
from ..db import SessionLocal
from ..models import Lot, LotStatus, User

log = logging.getLogger("auctions")
router = Router()
router.message.filter(F.chat.type == "private")       # личные команды - только в личке с ботом
BOT = {"username": ""}                                  # заполняется при старте (getMe)


class Sell(StatesGroup):
    photo = State()
    title = State()
    condition = State()
    price = State()
    duration = State()
    confirm = State()


class CustomBid(StatesGroup):
    amount = State()


def kb(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t, callback_data=d) for t, d in row]
                                                 for row in rows])


async def tg_user(session, u):
    return await svc.get_or_create_tg_user(session, u.id, u.username, u.full_name)


# ---------- пост лота в канале ----------
def post_markup(view: dict) -> InlineKeyboardMarkup | None:
    if view["status"] != "active":
        return None
    rows = [[InlineKeyboardButton(text=f"Ставка {money(view['next_bid'])}",
                                  callback_data=f"qbid:{view['id']}:{view['next_bid']}")]]
    if BOT["username"]:
        rows.append([InlineKeyboardButton(text="✍️ Своя ставка",
                                          url=f"https://t.me/{BOT['username']}?start=bid_{view['id']}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def caption(view: dict) -> str:
    return lot_caption(lot_id=view["id"], title=view["title"], condition=view["condition"], seller=view["seller"],
                       seller_avg=view["seller_avg"], seller_count=view["seller_count"],
                       start_price=view["start_price"], current_price=view["current_price"], leader=view["leader"],
                       bids=view["bids"], ends_at=view["ends_at"], status=view["status"], next_bid=view["next_bid"],
                       tz=settings.app_timezone, seller_no=view.get("seller_no"))


async def refresh_post(bot: Bot, lot_id: int) -> None:
    async with SessionLocal() as s:
        view = await svc.lot_view(s, lot_id)
    if not view or not view["message_id"]:
        return
    try:
        await bot.edit_message_caption(chat_id=parse_chat_id(view["chat_id"]), message_id=view["message_id"],
                                       caption=caption(view), parse_mode="HTML", reply_markup=post_markup(view))
    except TelegramBadRequest as e:
        if "not modified" not in str(e):
            log.warning("cannot edit lot %s post: %s", lot_id, e)


async def finish_loop(bot: Bot) -> None:
    """Каждые 15 секунд закрывает истёкшие лоты и обновляет их посты."""
    while True:
        try:
            async with SessionLocal() as s:
                ids = await svc.finish_due(s)
            for i in ids:
                await refresh_post(bot, i)
        except Exception:  # noqa: BLE001
            log.exception("finish loop error")
        await asyncio.sleep(15)


# ---------- создание лота ----------
@router.message(Command("cancel"), StateFilter("*"))
async def cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Действие отменено.")


@router.message(Command("sell"))
async def sell_start(message: Message, state: FSMContext):
    if not settings.telegram_trade_chat_id:
        await message.answer("Торговый канал пока не настроен администратором.")
        return
    async with SessionLocal() as s:
        user = await tg_user(s, message.from_user)
    if user.is_banned:
        await message.answer("Ваш аккаунт заблокирован администратором.")
        return
    await state.clear()
    await state.set_state(Sell.photo)
    await message.answer("Создаём лот. Шаг 1 из 5: пришлите фото карты.\nОтменить в любой момент: /cancel")


@router.message(Sell.photo, F.photo)
async def sell_photo(message: Message, state: FSMContext):
    await state.update_data(photo=message.photo[-1].file_id)
    await state.set_state(Sell.title)
    await message.answer("Шаг 2 из 5: напишите название карты (и сет, если важно).")


@router.message(Sell.photo)
async def sell_photo_wrong(message: Message):
    await message.answer("Нужна фотография карты. Пришлите фото или /cancel.")


@router.message(Sell.title, F.text)
async def sell_title(message: Message, state: FSMContext):
    title = " ".join(message.text.split())
    if not 2 <= len(title) <= 100:
        await message.answer("Название должно быть от 2 до 100 символов.")
        return
    await state.update_data(title=title)
    await state.set_state(Sell.condition)
    await message.answer("Шаг 3 из 5: состояние карты?",
                         reply_markup=kb([[(code, f"cond:{code}") for code in CONDITIONS]]))


@router.callback_query(Sell.condition, F.data.startswith("cond:"))
async def sell_condition(cb: CallbackQuery, state: FSMContext):
    code = cb.data.split(":", 1)[1]
    if code not in CONDITIONS:
        await cb.answer()
        return
    await state.update_data(condition=code)
    await state.set_state(Sell.price)
    await cb.message.edit_text(f"Состояние: {code} — {CONDITIONS[code]}")
    await cb.message.answer(f"Шаг 4 из 5: стартовая цена в рублях (от {MIN_START}), например 500.")
    await cb.answer()


@router.message(Sell.price, F.text)
async def sell_price(message: Message, state: FSMContext):
    price = parse_price(message.text)
    if price is None or price < MIN_START:
        await message.answer(f"Укажите цену числом, не меньше {MIN_START}.")
        return
    await state.update_data(price=price)
    await state.set_state(Sell.duration)
    await message.answer("Шаг 5 из 5: сколько длятся торги?",
                         reply_markup=kb([[(f"{h} ч", f"dur:{h}") for h in DURATIONS_H[:3]],
                                          [(f"{h} ч", f"dur:{h}") for h in DURATIONS_H[3:]]]))


@router.callback_query(Sell.duration, F.data.startswith("dur:"))
async def sell_duration(cb: CallbackQuery, state: FSMContext):
    hours = int(cb.data.split(":", 1)[1])
    await state.update_data(hours=hours)
    d = await state.get_data()
    await state.set_state(Sell.confirm)
    await cb.message.edit_text(
        f"Проверьте лот:\n\n🃏 {d['title']}\nСостояние: {d['condition']}\nСтарт: {money(d['price'])}\n"
        f"Торги: {hours} ч\n\nПубликуем в торговый канал?",
        reply_markup=kb([[("✅ Опубликовать", "sell:yes"), ("❌ Отмена", "sell:no")]]))
    await cb.answer()


@router.callback_query(Sell.confirm, F.data.in_({"sell:yes", "sell:no"}))
async def sell_confirm(cb: CallbackQuery, state: FSMContext, bot: Bot):
    d = await state.get_data()
    await state.clear()
    if cb.data == "sell:no":
        await cb.message.edit_text("Лот не создан.")
        await cb.answer()
        return
    async with SessionLocal() as s:
        user = await tg_user(s, cb.from_user)
        try:
            lot = await svc.create_lot(s, user, d["title"], d["condition"], d["price"], d["hours"], d["photo"])
        except AuctionError as e:
            await cb.message.edit_text(f"Не получилось: {e}")
            await cb.answer()
            return
        view = await svc.lot_view(s, lot.id)
        chat = settings.telegram_trade_chat_id
        try:
            msg = await bot.send_photo(parse_chat_id(chat), d["photo"], caption=caption(view), parse_mode="HTML",
                                       reply_markup=post_markup(view))
        except Exception as e:  # noqa: BLE001  канал недоступен - лот не должен висеть без поста
            log.warning("cannot publish lot %s: %r", lot.id, e)
            await svc.cancel_lot(s, lot.id, user)
            await cb.message.edit_text("Не удалось опубликовать лот в канале. Сообщите администратору.")
            await cb.answer()
            return
        await svc.attach_post(s, lot.id, chat, msg.message_id)
    url = post_url(chat, msg.message_id)
    await cb.message.edit_text(f"✅ Лот #{lot.id} опубликован." + (f"\n{url}" if url else ""))
    await cb.answer()


@router.message(Command("mylots"))
async def my_lots(message: Message):
    async with SessionLocal() as s:
        user = await tg_user(s, message.from_user)
        lots = (await s.execute(select(Lot).where(Lot.seller_id == user.id, Lot.status == LotStatus.active)
                                .order_by(Lot.ends_at))).scalars().all()
    if not lots:
        await message.answer("Активных лотов нет. Выставить карту: /sell")
        return
    lines = [f"#{x.id} {x.title} — " + (money(x.current_price) if x.current_price else f"старт {money(x.start_price)}")
             + (f" · {post_url(x.chat_id, x.message_id)}" if post_url(x.chat_id, x.message_id) else "") for x in lots]
    await message.answer("Ваши активные лоты:\n" + "\n".join(lines), disable_web_page_preview=True)


@router.message(Command("id"))
async def my_number(message: Message):
    """Свой номер игрока: его называют организатору при записи на турнир."""
    async with SessionLocal() as s:
        user = await tg_user(s, message.from_user)
        r = await svc.user_rating(s, user.id)
    await message.answer(rating_card(user.nickname, user.player_no, r) +
                         "\n\nНазовите номер организатору, чтобы он записал вас на турнир. "
                         "Проверить другого игрока: /rating и номер, например /rating 1001", parse_mode="HTML")


@router.message(Command("rating"))
async def rating_by_number(message: Message, command: CommandObject):
    arg = (command.args or "").strip().lstrip("№#")
    if not arg.isdigit():
        await message.answer("Укажите номер игрока: /rating 1001")
        return
    async with SessionLocal() as s:
        user = (await s.execute(select(User).where(User.player_no == int(arg)))).scalar_one_or_none()
        if not user:
            await message.answer(f"Игрока с номером {arg} нет.")
            return
        r = await svc.user_rating(s, user.id)
    text = rating_card(user.nickname, user.player_no, r)
    if settings.public_base_url:
        text += f"\n{settings.public_base_url.rstrip('/')}/players/{user.player_no}"
    await message.answer(text, parse_mode="HTML", disable_web_page_preview=True)


# ---------- ставки ----------
async def _bid(bot: Bot, tg_from, lot_id: int, amount: int | None) -> str:
    async with SessionLocal() as s:
        user = await tg_user(s, tg_from)
        out = await svc.place_bid(s, lot_id, user, amount)
    await refresh_post(bot, lot_id)
    text = f"Ставка {money(amount)} принята, вы лидируете!"
    return text + (" Торги продлены на 5 минут." if out.extended else "")


@router.callback_query(F.data.startswith("qbid:"))
async def quick_bid(cb: CallbackQuery, bot: Bot):
    try:
        _, lot_id, amount = cb.data.split(":")
        text = await _bid(bot, cb.from_user, int(lot_id), int(amount))
    except AuctionError as e:
        await cb.answer(str(e), show_alert=True)
        await refresh_post(bot, int(cb.data.split(":")[1]))   # если цена устарела - кнопка обновится
        return
    except ValueError:
        await cb.answer()
        return
    await cb.answer(text, show_alert=True)


@router.message(CommandStart(deep_link=True))
async def start_bid(message: Message, command: CommandObject, state: FSMContext):
    arg = command.args or ""
    if not arg.startswith("bid_") or not arg[4:].isdigit():
        await message.answer("Ссылка устарела. Команды: /sell, /mylots, /help")
        return
    lot_id = int(arg[4:])
    async with SessionLocal() as s:
        await tg_user(s, message.from_user)
        view = await svc.lot_view(s, lot_id)
    if not view or view["status"] != "active":
        await message.answer("Торги по этому лоту уже завершены.")
        return
    await state.set_state(CustomBid.amount)
    await state.update_data(lot_id=lot_id)
    await message.answer(f"Лот #{lot_id}: {view['title']}\nМинимальная ставка: {money(view['next_bid'])}.\n"
                         "Напишите сумму ставки (или /cancel).")


@router.message(CustomBid.amount, F.text)
async def custom_bid(message: Message, state: FSMContext, bot: Bot):
    lot_id = (await state.get_data())["lot_id"]
    try:
        text = await _bid(bot, message.from_user, lot_id, parse_price(message.text))
    except AuctionError as e:
        await message.answer(f"{e}. Попробуйте ещё раз или /cancel.")
        return
    await state.clear()
    await message.answer(text)


# ---------- сделки и оценки (кнопки в личных сообщениях) ----------
@router.callback_query(F.data.startswith("deal:"))
async def deal_answer(cb: CallbackQuery):
    try:
        _, deal_id, ans = cb.data.split(":")
        async with SessionLocal() as s:
            user = await tg_user(s, cb.from_user)
            deal = await svc.confirm_deal(s, int(deal_id), user, ans == "ok")
    except AuctionError as e:
        await cb.answer(str(e), show_alert=True)
        return
    await cb.message.edit_reply_markup(reply_markup=None)
    msg = {"pending": "Ответ записан. Ждём подтверждения второй стороны.",
           "completed": "Сделка подтверждена обеими сторонами. Сейчас придёт форма оценки.",
           "failed": "Сделка отмечена как несостоявшаяся.",
           "disputed": "Ответы сторон расходятся — ситуацию рассмотрит администратор."}[deal.status]
    await cb.message.answer(msg)
    await cb.answer()


@router.callback_query(F.data.startswith("rate:"))
async def rate(cb: CallbackQuery):
    try:
        _, deal_id, score = cb.data.split(":")
        async with SessionLocal() as s:
            user = await tg_user(s, cb.from_user)
            await svc.rate_deal(s, int(deal_id), user, int(score))
    except AuctionError as e:
        await cb.answer(str(e), show_alert=True)
        return
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.answer(f"Спасибо! Ваша оценка: {score} из 5.")
    await cb.answer()
