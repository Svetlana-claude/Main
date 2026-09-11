"""Настройки приложения. Читаются из файла окружения вне каталога проекта.

Файл держится **снаружи** `webui/` намеренно. Каталог проекта — рабочий каталог
темы в разделе «Проекты», а инструмент `Read` там доступен всегда, независимо от
флага запуска команд. Лежи `.env` внутри, `SECRET_KEY` и пароль базы попали бы
в ответ по первой же просьбе показать настройки проекта, а оттуда — в таблицу
сообщений, в поиск и в резервные копии.

Путь переопределяется переменной `WEBUI_ENV`; по умолчанию —
`~/.config/webui/webui.env` с правами 600.
"""
from pathlib import Path
import os

from dotenv import dotenv_values, load_dotenv

BASE_DIR = Path(__file__).resolve().parent          # .../webui/app
PROJECT_DIR = BASE_DIR.parent                        # .../webui

ENV_FILE = Path(os.environ.get("WEBUI_ENV") or Path.home() / ".config/webui/webui.env")
load_dotenv(ENV_FILE)

if "DATABASE_URL" not in os.environ:
    # Иначе падение выглядело бы как KeyError без единой подсказки, где искать
    raise RuntimeError(
        f"Не найдены настройки: файл {ENV_FILE} отсутствует или неполон. "
        "Образец состава — webui/.env.example, путь задаётся переменной WEBUI_ENV."
    )

# Имена ключей из файла настроек. По ним драйвер вычищает окружение перед
# запуском `claude`: иначе SECRET_KEY и пароль базы уезжают в дочерний процесс
# и видны там простым `env`, безо всякого доступа к файлу.
ENV_FILE_KEYS = frozenset(dotenv_values(ENV_FILE))

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
