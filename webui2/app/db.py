"""База SQLite: одна на сайт, файл вне папки проекта."""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY,
    login         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    lock_hash     TEXT NOT NULL,          -- код замка, тоже только хешем
    totp_secret   TEXT,                   -- второй шаг входа (base32)
    totp_last     INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    id         TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    csrf       TEXT NOT NULL,
    locked     INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS login_fails (
    ip TEXT NOT NULL,
    at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS login_fails_ip ON login_fails (ip, at);
-- Чат: разговоры и сообщения. norm — текст для поиска: строчные, «ё» как «е»
CREATE TABLE IF NOT EXISTS conversations (
    id             INTEGER PRIMARY KEY,
    title          TEXT NOT NULL DEFAULT '',
    model          TEXT NOT NULL DEFAULT 'sonnet',
    session_id     TEXT,                  -- беседа Claude, продолжается через --resume
    context_tokens INTEGER NOT NULL DEFAULT 0,  -- «вес» беседы
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY,
    conv_id    INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role       TEXT NOT NULL,             -- user, assistant, error
    text       TEXT NOT NULL,
    norm       TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_conv ON messages (conv_id, id);
-- Секрет второго шага, который ждёт первой настройки (до заведения хозяйки)
CREATE TABLE IF NOT EXISTS setup (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(config.DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


@contextmanager
def tx():
    con = connect()
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init() -> None:
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tx() as con:
        con.executescript(SCHEMA)
        con.execute("PRAGMA journal_mode = WAL")
    config.DB_PATH.chmod(0o600)
    config.CHAT_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)


def norm(text: str) -> str:
    """Вид текста для поиска: без учёта регистра и разницы «е»/«ё»."""
    return text.lower().replace("ё", "е")


def rows(sql: str, args: tuple = ()) -> list[dict]:
    with tx() as con:
        return [dict(row) for row in con.execute(sql, args).fetchall()]


def insert(sql: str, args: tuple = ()) -> int:
    with tx() as con:
        return con.execute(sql, args).lastrowid


def one(sql: str, args: tuple = ()) -> dict | None:
    with tx() as con:
        row = con.execute(sql, args).fetchone()
        return dict(row) if row else None


def run(sql: str, args: tuple = ()) -> None:
    with tx() as con:
        con.execute(sql, args)
