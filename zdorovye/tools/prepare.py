"""Подготовка «Здоровья» на сервере: файл настроек с ключом, база и разовая
ссылка первой настройки (новый секрет кода с телефона).

    .venv/bin/python tools/prepare.py

Повторный запуск ключ сайта не меняет. Пока Светлана не прошла настройку,
каждый запуск выдаёт новую ссылку и новый секрет (старая ссылка гаснет).
Печатает ссылку — её отдать Светлане.
"""
import os
import secrets
import sys
from pathlib import Path

ENV_FILE = Path(os.environ.get("ZD_ENV", Path.home() / ".config/zdorovye/zdorovye.env"))


def ensure_env() -> None:
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if ENV_FILE.exists() and "SECRET_KEY=" in ENV_FILE.read_text(encoding="utf-8"):
        return
    fd = os.open(ENV_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(f"SECRET_KEY={secrets.token_urlsafe(48)}\nLOGIN=Svetlana\nSITE_URL=https://mokeevasky.ru\n")


def main() -> None:
    ensure_env()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app import auth, config, db, security
    db.init()
    if auth.owner_exists():
        print("настройка уже пройдена — ссылка не нужна")
        return
    token = secrets.token_urlsafe(24)
    with db.tx() as con:
        con.execute("DELETE FROM setup")
        con.execute("INSERT INTO setup (key, value) VALUES ('totp_secret', ?)", (security.new_totp_secret(),))
        con.execute("INSERT INTO setup (key, value) VALUES ('token_hash', ?)", (security.token_hash(token),))
    print(f"{config.SITE_URL}{config.ROOT_PATH}/setup/{token}")


if __name__ == "__main__":
    main()
