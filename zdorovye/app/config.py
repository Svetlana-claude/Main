"""Настройки сайта «Здоровье». Ключ, база и бланки — вне папки проекта, права 600/700."""
import os
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
PROJECT_DIR = APP_DIR.parent

# Файл настроек: строки КЛЮЧ=значение. Путь можно подменить для проверок.
ENV_FILE = Path(os.environ.get("ZD_ENV", Path.home() / ".config/zdorovye/zdorovye.env"))


def _read_env(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                data[key.strip()] = value.strip()
    return data


_env = _read_env(ENV_FILE)

SECRET_KEY = _env.get("SECRET_KEY", "")
DATA_DIR = Path(_env.get("DATA_DIR", Path.home() / ".local/share/zdorovye"))
DB_PATH = DATA_DIR / "zdorovye.db"
FILES_DIR = DATA_DIR / "files"            # бланки анализов
KEY_FILE = DATA_DIR / "klyuch-kopiy.asc"  # ключ от копий — лежит, пока Светлана его не скачает
OWNER_LOGIN = _env.get("LOGIN", "Svetlana")
ROOT_PATH = os.environ.get("ROOT_PATH", "/zdorovye")
SITE_URL = _env.get("SITE_URL", "https://mokeevasky.ru")

ZONE = "Europe/Moscow"                    # всё время на сайте — по Москве
ZONE_LABEL = "по Москве"

COOKIE_NAME = "zd_session"
PRE_COOKIE = "zd_pre"                     # защита форм до появления сессии
SESSION_HOURS = 24 * 7                    # телефон-приложение: входить каждый день неудобно
PASS_MINUTES = 5                          # пропуск между паролем и кодом
FAIL_LIMIT = 5                            # неудачных попыток с одного адреса…
FAIL_WINDOW_MIN = 15                      # …за столько минут
INVITE_DAYS = 7                           # сколько живёт приглашение
ADD_LIMIT = 5                             # сколько близких может добавить каждый, кого завела Светлана
COOKIE_SECURE = os.environ.get("ZD_INSECURE_COOKIE") != "1"

# Разбор бланков: Claude только читает файл, в пустой временной папке
CLAUDE_BIN = _env.get("CLAUDE_BIN", str(Path.home() / ".local/bin/claude"))
PARSE_MODEL = _env.get("PARSE_MODEL", "sonnet")
PARSE_TIMEOUT_SEC = 600
MAX_UPLOAD_MB = 25
IMAGE_MAX_SIDE = 2400                     # фото бланка ужимается, цифры остаются читаемыми

SOON_DAYS = 30                            # прививка «скоро» — за столько дней

TEMPLATES_DIR = APP_DIR / "templates"
STATIC_DIR = APP_DIR / "static"
