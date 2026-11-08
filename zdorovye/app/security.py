"""Пароли, сессии, защита форм и от подбора, код с телефона. Устроено как на
основном сайте (webui2/app/security.py)."""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from . import config, db

_hasher = PasswordHasher()
# Сверка с этим хешем, когда логина нет: ответ по времени тот же, что и при неверном пароле
_DUMMY = _hasher.hash(secrets.token_urlsafe(16))


def hash_secret(value: str) -> str:
    return _hasher.hash(value)


def check_secret(stored: str | None, value: str) -> bool:
    try:
        return _hasher.verify(stored or _DUMMY, value) and stored is not None
    except (VerifyMismatchError, InvalidHashError):
        return False


def token_hash(token: str) -> str:
    """Хеш разовых ссылок: в базе их не прочитать."""
    return hashlib.sha256(f"{config.SECRET_KEY}:{token}".encode()).hexdigest()


def password_problem(password: str) -> str | None:
    if len(password) < 10:
        return "Пароль — не короче 10 знаков"
    if len(set(password)) < 4 or password.lower() in {"1234567890", "qwertyuiop", "password12"}:
        return "Слишком простой пароль"
    return None


def same(a: str, b: str) -> bool:
    """Сравнение без утечки по времени. Пустое не совпадает ни с чем."""
    return bool(a) and bool(b) and hmac.compare_digest(a.encode(), b.encode())


# ── Подписи ──────────────────────────────────────────────────────────────

def _sig(value: str, salt: str) -> str:
    mac = hmac.new(config.SECRET_KEY.encode(), f"{salt}:{value}".encode(), hashlib.sha256)
    return base64.urlsafe_b64encode(mac.digest()[:24]).decode().rstrip("=")


def sign(value: str, salt: str) -> str:
    return f"{value}.{_sig(value, salt)}"


def unsign(token: str, salt: str) -> str | None:
    value, _, sig = (token or "").rpartition(".")
    if value and same(sig, _sig(value, salt)):
        return value
    return None


# ── Сессии ───────────────────────────────────────────────────────────────

def new_session(user_id: int) -> str:
    sid = secrets.token_urlsafe(32)
    created = datetime.now(timezone.utc)
    db.run("INSERT INTO sessions (id, user_id, csrf, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
           (sid, user_id, secrets.token_urlsafe(24), created.isoformat(),
            (created + timedelta(hours=config.SESSION_HOURS)).isoformat()))
    return sign(sid, "session")


def session_of(token: str | None) -> dict | None:
    sid = unsign(token or "", "session")
    if not sid:
        return None
    row = db.one(
        "SELECT s.id, s.csrf, s.expires_at, u.id AS user_id, u.login, u.role, u.member_id "
        "FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.id = ?", (sid,))
    if not row:
        return None
    if datetime.fromisoformat(row["expires_at"]) <= datetime.now(timezone.utc):
        db.run("DELETE FROM sessions WHERE id = ?", (sid,))
        return None
    return row


def end_session(sid: str) -> None:
    db.run("DELETE FROM sessions WHERE id = ?", (sid,))


# ── Пропуск между паролем и кодом ────────────────────────────────────────

def make_pass(user_id: int, password_hash: str) -> str:
    expires = int(time.time()) + config.PASS_MINUTES * 60
    return sign(f"{user_id}:{expires}:{password_hash[-12:]}", "pass")


def read_pass(token: str) -> int | None:
    value = unsign(token or "", "pass")
    if not value:
        return None
    user_id, expires, tail = value.split(":", 2)
    if int(expires) < time.time():
        return None
    user = db.one("SELECT password_hash FROM users WHERE id = ?", (int(user_id),))
    if not user or not same(user["password_hash"][-12:], tail):
        return None
    return int(user_id)


# ── Подбор ───────────────────────────────────────────────────────────────

def _window_start() -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=config.FAIL_WINDOW_MIN)).isoformat()


def blocked(ip: str) -> bool:
    row = db.one("SELECT count(*) AS n FROM login_fails WHERE ip = ? AND at > ?", (ip, _window_start()))
    return row["n"] >= config.FAIL_LIMIT


def note_fail(ip: str) -> None:
    db.run("INSERT INTO login_fails (ip, at) VALUES (?, ?)", (ip, db.now()))
    db.run("DELETE FROM login_fails WHERE at < ?",
           ((datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),))


# ── Код с телефона (TOTP, RFC 6238) ──────────────────────────────────────

def new_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def totp_at(secret: str, step: int) -> str:
    key = base64.b32decode(secret.upper() + "=" * (-len(secret) % 8))
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % 1_000_000
    return f"{code:06d}"


def totp_step(secret: str, code: str, last_step: int) -> int | None:
    """Шаг, на котором код верен (окно ±1 по 30 с), если он новее последнего
    принятого. Повтор того же кода не проходит."""
    code = (code or "").strip().replace(" ", "")
    if not (len(code) == 6 and code.isascii() and code.isdigit()):
        return None
    now_step = int(time.time()) // 30
    for step in (now_step - 1, now_step, now_step + 1):
        if step > last_step and same(totp_at(secret, step), code):
            return step
    return None
