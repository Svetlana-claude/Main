"""Подготовка сайта на сервере: файл настроек с ключом и секрет кода с телефона
для первой настройки.

Секрет берётся у старого сайта — тот же, что уже стоит в приложении на телефоне,
поэтому заново сканировать QR не нужно. Запускать питоном старого сайта (там есть
драйвер его базы):

    webui/.venv/bin/python webui2/tools/prepare.py

Ничего секретного не печатает. Повторный запуск ключ не меняет.
"""
import os
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ENV_FILE = Path(os.environ.get("WEBUI2_ENV", Path.home() / ".config/webui2/webui2.env"))
OLD_ENV = Path.home() / ".config/webui/webui.env"


def ensure_env() -> None:
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if ENV_FILE.exists() and "SECRET_KEY=" in ENV_FILE.read_text(encoding="utf-8"):
        print("файл настроек уже есть")
    else:
        fd = os.open(ENV_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(f"SECRET_KEY={secrets.token_urlsafe(48)}\nLOGIN=Svetlana\nTIMEZONE=Europe/Moscow\n")
        print("файл настроек создан")
    ENV_FILE.chmod(0o600)


def old_secret(login: str) -> str | None:
    import psycopg
    from dotenv import dotenv_values

    url = dotenv_values(OLD_ENV)["DATABASE_URL"]
    with psycopg.connect(url) as con:
        row = con.execute("SELECT totp_secret FROM users WHERE login = %s AND totp_enabled",
                          (login,)).fetchone()
    return row[0] if row and row[0] else None


def main() -> None:
    ensure_env()
    from app import config, db
    db.init()
    if db.one("SELECT id FROM users LIMIT 1"):
        print("хозяйка уже заведена — первая настройка не нужна")
        return
    secret = old_secret(config.LOGIN)
    if not secret:
        sys.exit("у старого сайта нет включённого кода с телефона")
    db.run("INSERT OR REPLACE INTO setup (key, value) VALUES ('totp_secret', ?)", (secret,))
    print("секрет кода с телефона перенесён, первая настройка готова")


if __name__ == "__main__":
    main()
