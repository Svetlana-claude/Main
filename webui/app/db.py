"""Работа с базой: пул соединений, применение схемы, начальные данные."""
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from . import config
from .security import hash_password

_pool: ConnectionPool | None = None


def init_pool() -> None:
    """Создаёт пул. Вызывается один раз при старте приложения."""
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            config.DATABASE_URL,
            min_size=1,
            max_size=8,          # 2.9 ГБ RAM — держим пул скромным
            kwargs={"row_factory": dict_row},
            open=True,
        )


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def conn():
    """Соединение из пула. Транзакция фиксируется при выходе без ошибки."""
    if _pool is None:
        raise RuntimeError("пул соединений не инициализирован")
    with _pool.connection() as c:
        yield c


def query(sql: str, params: tuple = ()) -> list[dict]:
    with conn() as c:
        return c.execute(sql, params).fetchall()


def query_one(sql: str, params: tuple = ()) -> dict | None:
    with conn() as c:
        return c.execute(sql, params).fetchone()


def execute(sql: str, params: tuple = ()) -> None:
    with conn() as c:
        c.execute(sql, params)


def apply_schema() -> None:
    """Применяет schema.sql. Все операторы идемпотентны, можно гонять при каждом старте."""
    sql = (config.BASE_DIR / "schema.sql").read_text(encoding="utf-8")
    with conn() as c:
        c.execute(sql)


def seed() -> None:
    """Начальные данные: пользователь из ТЗ и настройки по умолчанию."""
    with conn() as c:
        exists = c.execute(
            "SELECT 1 FROM users WHERE login = %s", (config.INITIAL_LOGIN,)
        ).fetchone()
        if not exists:
            c.execute(
                "INSERT INTO users (login, password_hash, must_change) VALUES (%s, %s, true)",
                (config.INITIAL_LOGIN, hash_password(config.INITIAL_PASSWORD)),
            )
        for key, value in config.DEFAULT_SETTINGS.items():
            c.execute(
                "INSERT INTO settings (key, value) VALUES (%s, %s) "
                "ON CONFLICT (key) DO NOTHING",
                (key, value),
            )


def get_settings() -> dict[str, str]:
    rows = query("SELECT key, value FROM settings")
    values = dict(config.DEFAULT_SETTINGS)
    values.update({r["key"]: r["value"] for r in rows})
    return values


def set_setting(key: str, value: str) -> None:
    execute(
        "INSERT INTO settings (key, value, updated_at) VALUES (%s, %s, now()) "
        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()",
        (key, value),
    )
