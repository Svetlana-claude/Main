"""База SQLite: одна на сайт, файл вне папки проекта, права 600."""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from . import config

SCHEMA = """
-- Члены семьи: у каждого своя страничка
CREATE TABLE IF NOT EXISTS members (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    birth_date  TEXT NOT NULL DEFAULT '',     -- ГГГГ-ММ-ДД
    sex         TEXT NOT NULL DEFAULT '',     -- ж | м | ''
    blood       TEXT NOT NULL DEFAULT '',
    chronic     TEXT NOT NULL DEFAULT '',
    allergies   TEXT NOT NULL DEFAULT '',
    medicines   TEXT NOT NULL DEFAULT '',
    vitamins    TEXT NOT NULL DEFAULT '',
    notes       TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);
-- Входы. role: owner (Светлана, видит всех) | member (только свою страничку
-- и те, к которым Светлана открыла доступ)
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY,
    login         TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL,
    member_id     INTEGER REFERENCES members(id) ON DELETE CASCADE,
    totp_secret   TEXT,
    totp_last     INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    id         TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    csrf       TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS login_fails (
    ip TEXT NOT NULL,
    at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS login_fails_ip ON login_fails (ip, at);
-- Первая настройка: секрет кода с телефона и разовая ссылка
CREATE TABLE IF NOT EXISTS setup (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
-- Приглашения: разовая ссылка на страничку; в базе — только хеш
CREATE TABLE IF NOT EXISTS invites (
    id          INTEGER PRIMARY KEY,
    token_hash  TEXT NOT NULL UNIQUE,
    member_id   INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL,
    used_at     TEXT
);
-- Доступ к чужой страничке. state: asked (ждёт решения) | granted | declined | ended
CREATE TABLE IF NOT EXISTS access (
    id         INTEGER PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    member_id  INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    state      TEXT NOT NULL,
    asked_at   TEXT NOT NULL,
    decided_at TEXT
);
CREATE INDEX IF NOT EXISTS access_user ON access (user_id, member_id);
-- Дневник болезней
CREATE TABLE IF NOT EXISTS illnesses (
    id         INTEGER PRIMARY KEY,
    member_id  INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    started    TEXT NOT NULL,
    ended      TEXT NOT NULL DEFAULT '',
    title      TEXT NOT NULL,
    treatment  TEXT NOT NULL DEFAULT '',
    notes      TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
-- Прививки
CREATE TABLE IF NOT EXISTS vaccines (
    id         INTEGER PRIMARY KEY,
    member_id  INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    done_on    TEXT NOT NULL DEFAULT '',
    next_due   TEXT NOT NULL DEFAULT '',
    notes      TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
-- Бланки анализов. state: parsing (Claude читает) | review (ждёт проверки) |
-- ready (сохранён) | error (не разобрался — можно ещё раз или вручную)
CREATE TABLE IF NOT EXISTS docs (
    id         INTEGER PRIMARY KEY,
    member_id  INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    file       TEXT NOT NULL,                -- имя файла в FILES_DIR
    orig_name  TEXT NOT NULL DEFAULT '',
    mime       TEXT NOT NULL,
    taken_on   TEXT NOT NULL DEFAULT '',     -- дата сдачи
    lab        TEXT NOT NULL DEFAULT '',
    state      TEXT NOT NULL,
    draft      TEXT NOT NULL DEFAULT '',     -- разбор Claude (JSON) до проверки
    error      TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS docs_member ON docs (member_id, taken_on);
-- Показатели. key — имя для графика: строчными, «ё» как «е»
CREATE TABLE IF NOT EXISTS results (
    id         INTEGER PRIMARY KEY,
    doc_id     INTEGER REFERENCES docs(id) ON DELETE CASCADE,
    member_id  INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    taken_on   TEXT NOT NULL,
    name       TEXT NOT NULL,
    key        TEXT NOT NULL,
    value      REAL,
    value_text TEXT NOT NULL DEFAULT '',
    unit       TEXT NOT NULL DEFAULT '',
    low        REAL,
    high       REAL,
    ref_text   TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS results_member ON results (member_id, key, taken_on);
-- Оценка Claude по органам: одна на человека. state: running | ready | error.
-- print — отпечаток данных на момент оценки: не совпал — оценка устарела
CREATE TABLE IF NOT EXISTS assessments (
    member_id  INTEGER PRIMARY KEY REFERENCES members(id) ON DELETE CASCADE,
    state      TEXT NOT NULL,
    data       TEXT NOT NULL DEFAULT '',
    print      TEXT NOT NULL DEFAULT '',
    error      TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(config.DB_PATH, timeout=15)
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
    config.DATA_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    config.FILES_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tx() as con:
        con.executescript(SCHEMA)
        con.execute("PRAGMA journal_mode = WAL")
        # Разбор, прерванный перезапуском сайта, не продолжится сам
        con.execute("UPDATE docs SET state = 'error', error = 'Разбор прервался — нажми «Разобрать ещё раз»' "
                    "WHERE state = 'parsing'")
        con.execute("UPDATE assessments SET state = CASE WHEN data = '' THEN 'error' ELSE 'ready' END, "
                    "error = 'Оценка прервалась — нажми «Оценить» ещё раз' WHERE state = 'running'")
    config.DB_PATH.chmod(0o600)


def key_of(name: str) -> str:
    """Имя показателя для графика: без регистра, «ё» как «е», лишних пробелов."""
    return " ".join(name.lower().replace("ё", "е").split())


def rows(sql: str, args: tuple = ()) -> list[dict]:
    with tx() as con:
        return [dict(row) for row in con.execute(sql, args).fetchall()]


def one(sql: str, args: tuple = ()) -> dict | None:
    with tx() as con:
        row = con.execute(sql, args).fetchone()
        return dict(row) if row else None


def insert(sql: str, args: tuple = ()) -> int:
    with tx() as con:
        return con.execute(sql, args).lastrowid


def run(sql: str, args: tuple = ()) -> int:
    with tx() as con:
        return con.execute(sql, args).rowcount
