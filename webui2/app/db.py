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
-- Проекты: папка на сервере и галочки. Темы — разговоры с project_id
-- (колонка добавляется в init, чтобы старые базы тоже получили её).
-- delete_state: '' | checking (Claude смотрит, что убрать) | ready (список
-- готов, ждёт «да») | removing (удаляется) | unclear (не вышло — в
-- delete_report почему; можно проверить снова или отменить)
CREATE TABLE IF NOT EXISTS projects (
    id             INTEGER PRIMARY KEY,
    name           TEXT NOT NULL,
    slug           TEXT NOT NULL UNIQUE,
    path           TEXT NOT NULL,
    allow_commands INTEGER NOT NULL DEFAULT 0,
    full_access    INTEGER NOT NULL DEFAULT 0,
    delete_state   TEXT NOT NULL DEFAULT '',
    delete_report  TEXT NOT NULL DEFAULT '',
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);
-- Разрешения: о чём Claude в теме просит хозяйку. state: wait (ждёт) | yes |
-- no | late (нет ответа за 25 минут — отказ) | gone (вопрос снят: ответ
-- оборвался или Claude передумал). place — проект и тема словами, на память
CREATE TABLE IF NOT EXISTS permissions (
    id         INTEGER PRIMARY KEY,
    conv_id    INTEGER,
    project_id INTEGER,
    request_id TEXT NOT NULL,
    place      TEXT NOT NULL DEFAULT '',
    tool       TEXT NOT NULL,
    what       TEXT NOT NULL,
    detail     TEXT NOT NULL DEFAULT '',
    state      TEXT NOT NULL DEFAULT 'wait',
    created_at TEXT NOT NULL,
    decided_at TEXT
);
CREATE INDEX IF NOT EXISTS permissions_state ON permissions (state, id);
-- Выбор хозяйки в «Настройках» (пока — часовой пояс)
CREATE TABLE IF NOT EXISTS prefs (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
-- Нагрузка сервера раз в минуту, за последние сутки: проценты
CREATE TABLE IF NOT EXISTS load_samples (
    at   TEXT NOT NULL,
    cpu  REAL NOT NULL,
    mem  REAL NOT NULL,
    disk REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS load_samples_at ON load_samples (at);
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
        columns = {row["name"] for row in con.execute("PRAGMA table_info(conversations)")}
        if "project_id" not in columns:
            con.execute("ALTER TABLE conversations ADD COLUMN project_id INTEGER "
                        "REFERENCES projects(id) ON DELETE CASCADE")
        con.execute("CREATE INDEX IF NOT EXISTS conversations_project ON conversations (project_id, updated_at)")
        # Проверка или удаление проекта, прерванные перезапуском сайта
        con.execute("UPDATE projects SET delete_state = '' WHERE delete_state = 'checking'")
        con.execute("UPDATE projects SET delete_state = 'unclear', delete_report = "
                    "'Удаление прервал перезапуск сайта. Папка могла остаться.' WHERE delete_state = 'removing'")
        # Запуски Claude не переживают перезапуск сайта — их вопросы сняты
        con.execute("UPDATE permissions SET state = 'gone', decided_at = ? WHERE state = 'wait'", (now(),))
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
