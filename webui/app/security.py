"""Пароли и сессии.

Пароли хранятся хешами argon2id — не в открытом виде и не MD5.
Сессии серверные: идентификатор в подписанной cookie, сама запись в базе,
поэтому выход действительно завершает сессию.
"""
import uuid
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError
from itsdangerous import BadSignature, URLSafeSerializer

from . import config

# Параметры подобраны под 2.9 ГБ RAM: 64 МБ на проверку — с запасом по стойкости,
# но не съедает память сервера при входе.
_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)
_serializer = URLSafeSerializer(config.SECRET_KEY, salt="session")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        _hasher.verify(password_hash, password)
        return True
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def password_problem(password: str) -> str | None:
    """Возвращает текст проблемы или None, если пароль годится."""
    if len(password) < config.MIN_PASSWORD_LEN:
        return f"Пароль короче {config.MIN_PASSWORD_LEN} символов"
    if password == config.INITIAL_PASSWORD:
        return "Нельзя оставить первоначальный пароль"
    if password.isdigit():
        return "Пароль из одних цифр слишком легко подобрать"
    if password.lower() in {"password", "пароль", "12345678", "qwertyui"}:
        return "Этот пароль слишком распространён"
    return None


def sign_session_id(session_id: str) -> str:
    return _serializer.dumps(session_id)


def unsign_session_id(token: str) -> str | None:
    try:
        value = _serializer.loads(token)
    except BadSignature:
        return None
    return value if isinstance(value, str) else None


def new_session_id() -> str:
    return str(uuid.uuid4())


def session_expiry() -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=config.SESSION_DAYS)
