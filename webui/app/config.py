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

# Ключи приложения. По ним драйвер вычищает окружение перед запуском `claude`:
# иначе SECRET_KEY и пароль базы уезжают в дочерний процесс и видны там простым
# `env`, безо всякого доступа к файлу.
#
# Перечислены явно, а не только собираются из файла. Если ключи однажды переедут
# в EnvironmentFile юнита, файла у пользователя не будет вовсе — набор из файла
# оказался бы пустым, и вычистка отказала бы ровно тогда, когда она главное, что
# защищает ключи. Имена из файла добавляются сверх списка: там могут появиться
# свои переменные.
APP_ENV_KEYS = frozenset({
    "DATABASE_URL", "SECRET_KEY", "CLAUDE_BIN", "REPO_ROOT", "ROOT_PATH", "WEBUI_ENV",
})
SCRUB_ENV_KEYS = APP_ENV_KEYS | frozenset(dotenv_values(ENV_FILE))

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
    "theme": "light",               # светлая тема 1С по умолчанию, идея 5
    "metrics_keep_hours": "48",     # сколько держать историю метрик, идея 6
    "timezone": "Europe/Moscow",    # пояс вывода времени; хранится всё в UTC
    # Пределы окон тарифного плана, в токенах (вход + выход). По умолчанию ноль —
    # «не задан»: сколько токенов укладывается в окно плана, Anthropic числом
    # не публикует, счёт ведётся на его стороне и зависит от модели и размера
    # контекста. Поэтому число подбирается наблюдением — см. подсказку в
    # «Настройках» — а не прописывается по памяти: выдуманный предел показывал бы
    # уверенный остаток, которого никто не обещал.
    "limit_5h_tokens": "0",
    "limit_week_tokens": "0",
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
