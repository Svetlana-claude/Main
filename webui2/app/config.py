"""Настройки сайта. Секреты и база — вне папки проекта, права 600."""
import os
from pathlib import Path
from zoneinfo import ZoneInfo

APP_DIR = Path(__file__).resolve().parent
PROJECT_DIR = APP_DIR.parent

# Файл настроек: строки КЛЮЧ=значение. Путь можно подменить для проверок.
ENV_FILE = Path(os.environ.get("WEBUI2_ENV", Path.home() / ".config/webui2/webui2.env"))


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
DB_PATH = Path(_env.get("DB_PATH", Path.home() / ".local/share/webui2/site.db"))
LOGIN = _env.get("LOGIN", "Svetlana")
ROOT_PATH = os.environ.get("ROOT_PATH", "/Claude/v2")

# Время хранится в UTC, показывается в её поясе
TIMEZONE = ZoneInfo(_env.get("TIMEZONE", "Europe/Moscow"))
TIMEZONE_LABEL = "по Москве" if str(TIMEZONE) == "Europe/Moscow" else str(TIMEZONE)

COOKIE_NAME = "v2_session"
PRE_COOKIE = "v2_pre"                 # защита формы входа до появления сессии
SESSION_HOURS = 12
PASS_MINUTES = 5                      # сколько живёт пропуск между паролем и кодом
FAIL_LIMIT = 5                        # неудачных попыток с одного адреса…
FAIL_WINDOW_MIN = 15                  # …за столько минут
# Без https кука Secure не уходит — для проверок на 127.0.0.1 отключается
COOKIE_SECURE = os.environ.get("WEBUI2_INSECURE_COOKIE") != "1"

TEMPLATES_DIR = APP_DIR / "templates"
STATIC_DIR = APP_DIR / "static"
