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


def one(sql: str, args: tuple = ()) -> dict | None:
    with tx() as con:
        row = con.execute(sql, args).fetchone()
        return dict(row) if row else None


def run(sql: str, args: tuple = ()) -> None:
    with tx() as con:
        con.execute(sql, args)
