from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router()


async def _chatid(message: Message):
    await message.answer(
        f"ID этого чата: <code>{message.chat.id}</code>\n"
        "Вставьте его в поле telegram_chat_id в настройках клуба на сайте, "
        "а затем нажмите «Проверить подключение».", parse_mode="HTML")


@router.message(Command("start", "help"))
async def start(message: Message):
    await message.answer(
        "Привет! Я бот платформы для клубов настольных игр и ККИ.\n\n"
        "Как подключить клуб:\n"
        "1. Добавьте меня в чат или канал клуба (в канале — как администратора с правом публикации).\n"
        "2. Отправьте там команду /chatid и скопируйте ID.\n"
        "3. Укажите ID в настройках клуба на сайте.\n\n"
        "После этого сюда будут приходить анонсы турниров, новости и итоги ивентов.")


@router.message(Command("chatid"))
async def chatid_message(message: Message):
    await _chatid(message)


@router.channel_post(Command("chatid"))
async def chatid_channel(message: Message):
    await _chatid(message)
