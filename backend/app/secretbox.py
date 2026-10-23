"""Шифрование секретов в базе (токены VK): ключ выводится из JWT_SECRET.
Сменили JWT_SECRET - сохранённые токены не расшифруются, их нужно ввести заново (decrypt вернёт None)."""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from .config import settings


def _fernet() -> Fernet:
    key = hashlib.sha256(("dragon-secretbox:" + settings.jwt_secret).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt(value: str | None) -> str | None:
    return _fernet().encrypt(value.encode()).decode() if value else None


def decrypt(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken:
        return None
