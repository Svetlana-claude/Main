"""Настройки бота.

Файл настроек держится **вне каталога проекта** по той же причине, что и у
`webui`: каталог проекта — рабочая область темы, и инструмент `Read` там доступен
всегда. Путь по умолчанию — `~/.config/tgbot/tgbot.env` с правами 600,
переопределяется переменной `TGBOT_ENV`.

⚠️ **Токен бота не попадает в `os.environ`.** Значения читаются `dotenv_values`,
а не `load_dotenv`: последний положил бы токен в окружение процесса, а оттуда его
унаследовал бы запущенный нами `claude` — и в теме с разрешённым `Bash` токен
читался бы простой командой `env`, безо всякого доступа к файлу. Так же, как это
уже разобрано в `webui/app/config.py` про `SECRET_KEY`.

Одного этого мало, поэтому ниже имена наших ключей ещё и дописываются в список
вычистки драйвера: настройки могут прийти не из файла, а от systemd
(`Environment=`), и тогда они окажутся в окружении до нас.
"""
import os
from pathlib import Path

from dotenv import dotenv_values

from . import REPO_ROOT, WEBUI_DIR     # noqa: F401 — импорт пакета правит sys.path

PROJECT_DIR = Path(__file__).resolve().parents[1]     # .../telegram-bot
BASE_DIR = Path(__file__).resolve().parent            # .../telegram-bot/bot

ENV_FILE = Path(os.environ.get("TGBOT_ENV") or Path.home() / ".config/tgbot/tgbot.env")
_values = dict(dotenv_values(ENV_FILE))

# Имена наших ключей. Перечислены явно, а не только собраны из файла: при
# переносе настроек в юнит systemd файла у пользователя не будет вовсе, набор из
# файла оказался бы пустым — и вычистка отказала бы ровно тогда, когда она
# единственное, что защищает токен.
BOT_ENV_KEYS = frozenset({
    "TELEGRAM_TOKEN", "TELEGRAM_ALLOWED", "TELEGRAM_ADMIN", "TGBOT_ENV",
}) | frozenset(_values)


def _nastroyka(key: str, default: str = "") -> str:
    """Значение из файла, а если его там нет — из окружения."""
    value = _values.get(key)
    if value is None:
        value = os.environ.get(key)
    return (value or default).strip()


TOKEN = _nastroyka("TELEGRAM_TOKEN")
if not TOKEN:
    raise RuntimeError(
        f"Не найден TELEGRAM_TOKEN: файл {ENV_FILE} отсутствует или неполон. "
        "Образец состава — telegram-bot/.env.example, путь задаётся переменной TGBOT_ENV."
    )


def _spisok_id(raw: str) -> frozenset[int]:
    out = set()
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if part.lstrip("-").isdigit():
            out.add(int(part))
    return frozenset(out)


# Кому можно писать боту. Пустой список — нельзя никому: бот с открытым доступом
# это чужие руки в рабочих каталогах и расход по нашей подписке. Свой числовой id
# бот показывает командой /id — она отвечает и тем, кого в списке нет.
ALLOWED_IDS = _spisok_id(_nastroyka("TELEGRAM_ALLOWED"))

# Кому уходят служебные сообщения (чужой стук в бота, сбой при старте).
# По умолчанию — первый из разрешённых.
_admin = _spisok_id(_nastroyka("TELEGRAM_ADMIN"))
ADMIN_ID = next(iter(_admin), None) or (min(ALLOWED_IDS) if ALLOWED_IDS else None)

# Как часто правится сообщение «Ход работы». Телеграм считает правки за
# сообщения и при частых отвечает 429: раз в 2,5 с — живо и без отбоя.
EDIT_INTERVAL_SEC = 2.5

# Предел на сообщение у Телеграма — 4096 знаков. Режем с запасом: разметка
# добавляет теги, а служебная строка в конце куска прибавляет свою длину.
CHUNK_LIMIT = 3500

# Сколько хвоста ответа показывать в живом «Ходе работы»
TAIL_CHARS = 1200

# Предел на входящий файл. Телеграм боту сам не отдаёт больше 20 МБ, но число
# нужно и для своей проверки: getFile на большем отвечает ошибкой, и сказать об
# этом надо словами.
MAX_FILE_BYTES = 20 * 1024 * 1024

# Каталог для присланных файлов — тот же, что у веб-интерфейса, чтобы
# присланное в Телеграм было видно в «Файлах проекта».
UPLOADS_DIR = WEBUI_DIR / "uploads"

# Общий распознаватель изображений, правило 17 CLAUDE.md. Системный python —
# Pillow стоит в нём, а не в окружении проекта.
OCR_PYTHON = "/usr/bin/python3"
OCR_SCRIPT = REPO_ROOT / "tools" / "ocr.py"

# ---------------------------------------------------------------------------
# Настройки webui: база, путь к `claude`, список вычистки окружения.
# Импорт здесь, а не в начале файла, — он требует готового sys.path из пакета.
from app import config as webui_config     # noqa: E402

# Дописываем наши ключи в список вычистки: драйвер читает его в момент запуска
# `claude`, поэтому правки достаточно заранее.
webui_config.SCRUB_ENV_KEYS = webui_config.SCRUB_ENV_KEYS | BOT_ENV_KEYS

DATABASE_URL = webui_config.DATABASE_URL
