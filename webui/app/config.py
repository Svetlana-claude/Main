"""Настройки приложения. Читаются из .env рядом с проектом."""
from pathlib import Path
import os

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent          # .../webui/app
PROJECT_DIR = BASE_DIR.parent                        # .../webui

load_dotenv(PROJECT_DIR / ".env")

DATABASE_URL = os.environ["DATABASE_URL"]
SECRET_KEY = os.environ["SECRET_KEY"]
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
REPO_ROOT = Path(os.environ.get("REPO_ROOT", "/home/mokeeva/main"))

# Куда монтируется приложение — по ТЗ вход по адресу вида http://<ip>/Claude
ROOT_PATH = os.environ.get("ROOT_PATH", "/Claude")

TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
UPLOADS_DIR = PROJECT_DIR / "uploads"

COOKIE_NAME = "webui_session"
SESSION_DAYS = 30

# Защита от перебора пароля: сколько неудач за окно и на сколько потом блокировать
LOGIN_MAX_FAILS = 10
LOGIN_WINDOW_MIN = 15

# Пароль при первом входе — по ТЗ. Смена обязательна.
INITIAL_LOGIN = "Svetlana"
INITIAL_PASSWORD = "admin"
MIN_PASSWORD_LEN = 8

# Значения настроек по умолчанию. Правятся в разделе «Настройки».
DEFAULT_SETTINGS = {
    "refresh_seconds": "10",        # автообновление дашборда, по ТЗ 10 секунд
    "model": "opus",                # алиас модели для CLI
    "monthly_limit_usd": "50",      # предупреждение о расходе, идея 1
    "theme": "light",               # светлая тема 1С по умолчанию, идея 5
    "metrics_keep_hours": "48",     # сколько держать историю метрик, идея 6
}

# Файлы сопровождения, которые правятся из раздела «Настройки»
SUPPORT_FILES = [
    "CLAUDE.md",
    "architect.md",
    "result.md",
    "current_questions.md",
    "tech_debt.md",
    "log.md",
]
