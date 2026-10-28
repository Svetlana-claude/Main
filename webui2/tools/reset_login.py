"""Забыт пароль: вернуть сайт к первой настройке.

Хозяйка удаляется из базы вместе со всеми её входами, секрет кода с телефона
переносится обратно в таблицу setup. На /setup она задаёт новый пароль и код
замка; без шести цифр с телефона форму не заполнить. Разговоры и проекты
остаются. Ничего секретного не печатает.

    webui2/.venv/bin/python webui2/tools/reset_login.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import db  # noqa: E402

user = db.one("SELECT id, totp_secret FROM users LIMIT 1")
if not user or not user["totp_secret"]:
    sys.exit("хозяйки с кодом с телефона в базе нет — сбрасывать нечего")
with db.tx() as con:
    con.execute("INSERT OR REPLACE INTO setup (key, value) VALUES ('totp_secret', ?)", (user["totp_secret"],))
    con.execute("DELETE FROM sessions")
    con.execute("DELETE FROM users")
    con.execute("DELETE FROM login_fails")
print("готово: сайт ждёт первой настройки")
