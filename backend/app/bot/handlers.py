from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

router = Router()


async def _chatid(message: Message):
    await message.answer(
        f"ID этого чата: <code>{message.chat.id}</code>\n"
        "Вставьте его в поле telegram_chat_id в настройках клуба на сайте, "
        "а затем нажмите «Проверить подключение».", parse_mode="HTML")


async def _link_message(message: Message, code: str) -> bool:
    """/start link_<код>: игрок нажал «Записаться», но Telegram не привязан - даём ссылку на подтверждение."""
    from sqlalchemy import select

    from ..config import settings
    from ..db import SessionLocal
    from ..models import LinkCode, Tournament
    async with SessionLocal() as s:
        lc = (await s.execute(select(LinkCode).where(LinkCode.code == code))).scalar_one_or_none()
        t = await s.get(Tournament, lc.tournament_id) if lc and lc.tournament_id else None
    if not lc or lc.used_at or not settings.public_base_url:
        return False
    url = settings.public_base_url.rstrip("/") + f"/link/{code}"
    what = f" и сразу запишем на «{t.name}»" if t else ""
    await message.answer(
        "Ваш Telegram ещё не связан с номером игрока на сайте.\n\n"
        f"Откройте ссылку и войдите в свой аккаунт — мы привяжем Telegram{what}. "
        "Если аккаунта нет, там же можно создать его в один клик.\n\n"
        "Дальше кнопки «Записаться» будут работать сразу.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Подтвердить на сайте", url=url)]]))
    return True


@router.message(Command("start", "help"))
async def start(message: Message, command: CommandObject):
    if command.args and command.args.startswith("link_") and await _link_message(message, command.args[5:]):
        return
    await message.answer(
        "Привет! Я бот платформы для клубов настольных игр и ККИ.\n\n"
        "Как подключить клуб:\n"
        "1. Добавьте меня в чат или канал клуба (в канале — как администратора с правом публикации).\n"
        "2. Отправьте там команду /chatid и скопируйте ID.\n"
        "3. Укажите ID в настройках клуба на сайте.\n\n"
        "После этого сюда будут приходить анонсы турниров, новости и итоги ивентов.\n\n"
        "Аукцион карт:\n"
        "/sell — выставить карту на торги\n"
        "/mylots — мои активные лоты\n"
        "/id — мой номер игрока и репутация\n"
        "/rating 1001 — репутация игрока по номеру\n"
        "/cancel — отменить текущее действие\n\n"
        "Ставки делаются кнопками под постом лота в торговом канале. "
        "Уведомления о перебитых ставках и итогах торгов приходят сюда, поэтому не блокируйте бота.")


@router.message(Command("chatid"))
async def chatid_message(message: Message):
    await _chatid(message)


@router.channel_post(Command("chatid"))
async def chatid_channel(message: Message):
    await _chatid(message)
