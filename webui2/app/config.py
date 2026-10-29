"""Настройки сайта. Секреты и база — вне папки проекта, права 600."""
import os
from pathlib import Path

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

# Время хранится в UTC, показывается в её поясе. Пояс по умолчанию — из файла
# настроек; выбранный в «Настройках» хранится в базе (web.zone)
ZONES = {
    "Europe/Kaliningrad": ("Калининград (МСК−1)", "по Калининграду"),
    "Europe/Moscow": ("Москва (МСК)", "по Москве"),
    "Europe/Samara": ("Самара (МСК+1)", "по Самаре"),
    "Asia/Yekaterinburg": ("Екатеринбург (МСК+2)", "по Екатеринбургу"),
    "Asia/Omsk": ("Омск (МСК+3)", "по Омску"),
    "Asia/Novosibirsk": ("Новосибирск (МСК+4)", "по Новосибирску"),
    "Asia/Krasnoyarsk": ("Красноярск (МСК+4)", "по Красноярску"),
    "Asia/Irkutsk": ("Иркутск (МСК+5)", "по Иркутску"),
    "Asia/Yakutsk": ("Якутск (МСК+6)", "по Якутску"),
    "Asia/Vladivostok": ("Владивосток (МСК+7)", "по Владивостоку"),
    "Asia/Magadan": ("Магадан (МСК+8)", "по Магадану"),
    "Asia/Kamchatka": ("Камчатка (МСК+9)", "по Камчатке"),
    "UTC": ("Всемирное время (UTC)", "UTC"),
}
TIMEZONE_NAME = _env.get("TIMEZONE", "Europe/Moscow")
if TIMEZONE_NAME not in ZONES:
    TIMEZONE_NAME = "Europe/Moscow"

COOKIE_NAME = "v2_session"
PRE_COOKIE = "v2_pre"                 # защита формы входа до появления сессии
SESSION_HOURS = 12
PASS_MINUTES = 5                      # сколько живёт пропуск между паролем и кодом
FAIL_LIMIT = 5                        # неудачных попыток с одного адреса…
FAIL_WINDOW_MIN = 15                  # …за столько минут
# Без https кука Secure не уходит — для проверок на 127.0.0.1 отключается
COOKIE_SECURE = os.environ.get("WEBUI2_INSECURE_COOKIE") != "1"

# Чат: Claude без инструментов, в пустой папке вне проекта
CLAUDE_BIN = _env.get("CLAUDE_BIN", str(Path.home() / ".local/bin/claude"))
CHAT_DIR = Path(_env.get("CHAT_DIR", DB_PATH.parent / "chat-room"))
MODELS = {"opus": "Opus", "sonnet": "Sonnet", "haiku": "Haiku"}
DEFAULT_MODEL = "sonnet"
PAGE_MESSAGES = 40                    # сообщений на странице разговора
BIG_CONTEXT = 150_000                 # с какого веса беседа считается большой…
QUIET_HOURS = 6                       # …и через сколько часов молчания советовать новую

# Проекты: папки с темами. Claude в теме работает полноценно, в папке проекта
PROJECTS_DIR = Path(_env.get("PROJECTS_DIR", Path.home() / "projects"))
TOPIC_MODEL = "opus"
# Подпись сохранений в новых проектах; не задана — берётся из git самого сайта
GIT_NAME = _env.get("GIT_NAME", "")
GIT_EMAIL = _env.get("GIT_EMAIL", "")
# Папка сайта и хранилище, где она лежит: удаление проекта их не тронет
SITE_DIRS = (PROJECT_DIR, PROJECT_DIR.parent)

# Перезапуск сайта и сервера — через обёртку с закрытым списком команд (sudo -n)
POWER_CMD = _env.get("POWER_CMD", "sudo -n /usr/local/sbin/webui2-power").split()
POWER_WAIT_MIN = 60                   # дольше ответы не ждём — перезапуск отменяется
LOAD_EVERY_SEC = 60                   # замер нагрузки для графика
LOAD_KEEP_HOURS = 24

# VPN: устройства того же WireGuard, что завёл старый сайт; root — только через обёртку
VPN_CMD = _env.get("VPN_CMD", "sudo -n /usr/local/sbin/webui2-vpn").split()
QR_BIN = _env.get("QR_BIN", "/usr/bin/qrencode")
# Ночная проверка безопасности: её ставил старый сайт, отчёты — в SEC_STATE
SEC_STATE = Path(_env.get("SEC_STATE", "/var/lib/secaudit"))
SEC_AUDIT = _env.get("SEC_AUDIT", "/bin/bash /opt/secaudit/audit.sh").split()
SEC_APPROVE = _env.get("SEC_APPROVE", "sudo -n /usr/local/sbin/webui-sec baseline-approve").split()
SEC_STALE_HOURS = 36                  # отчёта нет дольше — ночная проверка, видимо, не идёт
SEC_RUN_MIN = 15                      # дольше проверку не ждём

TEMPLATES_DIR = APP_DIR / "templates"
STATIC_DIR = APP_DIR / "static"
