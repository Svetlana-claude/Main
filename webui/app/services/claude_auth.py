"""Вход Claude Code: состояние и повторный вход из браузера.

Движок диалога — тот же `claude`, что в терминале, и входит он по подписке.
Рабочий ключ живёт часы и продлевается сам, ключ продления — около месяца.
Когда продлить не выходит, каждое сообщение кончается ошибкой «Failed to
authenticate», а чинился вход до сих пор только `/login` по SSH.

Повторный вход повторяет то, что `claude auth login` делает на сервере без
браузера: печатает ссылку на claude.com и ждёт код, который claude.com покажет
после входа. Команда запускается в псевдотерминале (без него она не спрашивает
код), ссылка вынимается из вывода и показывается на странице, код из поля
формы пишется в тот же терминал. Новые данные входа команда сохраняет сама —
приложение ключей не видит и не хранит.

Идёт не больше одного входа сразу; ссылка, код и вывод команды держатся только
в памяти процесса. Незавершённый вход через LOGIN_TTL_SEC снимается.
"""
import asyncio
import contextlib
import fcntl
import json
import os
import pty
import re
import struct
import termios
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .. import config

LOGIN_TTL_SEC = 600          # сколько ждать код, прежде чем снять вход
URL_WAIT_SEC = 30            # сколько ждать ссылку после запуска команды
FINISH_WAIT_SEC = 60         # сколько ждать завершения после ввода кода
CHECK_TIMEOUT_SEC = 120      # проверочный вызов `claude -p`
CHECK_PROMPT = "Ответь одним словом: работает"

CREDENTIALS = Path.home() / ".claude" / ".credentials.json"

# Строки, которыми Claude Code сообщает, что войти не может. Сверены с тем, что
# пришло 21.09.2026: «Failed to authenticate: OAuth session expired and could
# not be refreshed». Остальные — его же сообщения о неверном или отозванном ключе.
_AUTH_ERROR = re.compile(
    r"Failed to authenticate|OAuth session expired|OAuth token (?:has )?expired"
    r"|authentication_error|Invalid API key|Please run /login|run /login",
    re.IGNORECASE,
)

EXPLAIN = (
    "Вход Claude истёк: Claude Code не смог продлить вход в аккаунт, поэтому "
    "ответа нет. Войдите заново: «Настройки» → «Вход Claude»."
)

# Ссылка приходит гиперссылкой терминала (OSC 8): ESC ] 8 ; ; адрес ESC \ —
# адрес берётся оттуда. Видимый текст той же ссылки терминал мог бы перенести
# по ширине, поэтому он — только запасной путь.
_OSC8_URL = re.compile(r"\x1b\]8;[^;\x07\x1b]*;(https://[^\x07\x1b]+)(?:\x07|\x1b\\)")
_ESCAPES = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[@-Z\\-_]")
_PLAIN_URL = re.compile(r"https://\S+")
_CODE_PROMPT = re.compile(r"Paste code", re.IGNORECASE)


def is_auth_error(text: str | None) -> bool:
    return bool(text) and bool(_AUTH_ERROR.search(text))


def explain(text: str) -> str:
    """Сообщение об ошибке для показа: ошибка входа — словами, прочее как есть."""
    return EXPLAIN if is_auth_error(text) else text


# ── Признак «вход не работает» ───────────────────────────────────────
#
# Ставится драйвером, когда движок ответил ошибкой входа, снимается любым
# успешным ответом и удачным повторным входом. Живёт в памяти: после перезапуска
# службы его заново поставит первая же неудача.

_failed_at: float | None = None


def mark_failed() -> None:
    global _failed_at
    _failed_at = time.time()


def mark_ok() -> None:
    global _failed_at
    _failed_at = None


def _refresh_expires() -> datetime | None:
    """Срок ключа продления из файла входа. Сами ключи не читаются."""
    try:
        data = json.loads(CREDENTIALS.read_text(encoding="utf-8"))
        ms = (data.get("claudeAiOauth") or {}).get("refreshTokenExpiresAt")
        return datetime.fromtimestamp(int(ms) / 1000, timezone.utc) if ms else None
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def _env_token() -> str:
    """Имя переменной с ключом, если движку он задан окружением.

    Такой ключ Claude Code берёт вместо файла входа, и повторный вход через
    страницу тогда ничего не меняет — об этом надо сказать.
    """
    from . import claude_driver            # драйвер сам импортирует этот модуль
    env = claude_driver._child_env()
    for name in ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        if env.get(name):
            return name
    return ""


def problem() -> str:
    """Короткая причина для плашки в шапке; пусто, если всё в порядке."""
    if _failed_at is not None:
        return "Вход Claude истёк — ответов не будет, пока не войти заново."
    expires = _refresh_expires()
    if expires and expires <= datetime.now(timezone.utc):
        return "Срок входа Claude закончился — войдите заново."
    return ""


async def status() -> dict:
    """Состояние входа для страницы настроек."""
    info: dict = {}
    try:
        proc = await asyncio.create_subprocess_exec(
            config.CLAUDE_BIN, "auth", "status", "--json",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            env=_env(),
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=20)
        info = json.loads(out.decode("utf-8", "replace") or "{}")
    except (OSError, ValueError, asyncio.TimeoutError):
        info = {}
    return {
        "logged_in": bool(info.get("loggedIn")),
        "email": info.get("email") or "",
        "method": info.get("authMethod") or "",
        "subscription": info.get("subscriptionType") or "",
        "refresh_expires": _refresh_expires(),
        "env_token": _env_token(),
        "failed": _failed_at is not None,
    }


def _env() -> dict[str, str]:
    from . import claude_driver
    env = claude_driver._child_env()
    env["NO_COLOR"] = "1"
    env["BROWSER"] = "true"      # открыть браузер на сервере всё равно нечем
    return env


async def check() -> tuple[bool, str]:
    """Настоящая проверка: короткий вызов движка. `auth status` говорит
    «вошли», даже когда ключ продления уже не принимают."""
    try:
        proc = await asyncio.create_subprocess_exec(
            config.CLAUDE_BIN, "-p", CHECK_PROMPT, "--output-format", "text",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            stdin=asyncio.subprocess.DEVNULL, env=_env(), cwd=str(Path.home()),
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=CHECK_TIMEOUT_SEC)
    except asyncio.TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        return False, "Claude не ответил за отведённое время."
    except OSError as exc:
        return False, f"Не запустился {config.CLAUDE_BIN}: {exc}"
    text = out.decode("utf-8", "replace").strip()
    if proc.returncode == 0 and text and not is_auth_error(text):
        mark_ok()
        return True, text[:200]
    if is_auth_error(text):
        mark_failed()
        return False, EXPLAIN
    return False, (text[-300:] or f"код возврата {proc.returncode}")


# ── Повторный вход ───────────────────────────────────────────────────

@dataclass
class LoginFlow:
    """Один запуск `claude auth login`.

    state: starting → waiting_code → finishing → done | failed.
    """
    state: str = "starting"
    url: str = ""
    message: str = ""
    started: float = field(default_factory=time.time)
    output: str = ""
    proc: asyncio.subprocess.Process | None = None
    master: int = -1
    reader: asyncio.Task | None = None
    url_seen: asyncio.Event = field(default_factory=asyncio.Event)

    @property
    def alive(self) -> bool:
        return self.proc is not None and self.proc.returncode is None

    def as_dict(self) -> dict:
        left = max(0, int(self.started + LOGIN_TTL_SEC - time.time()))
        return {"state": self.state, "url": self.url, "message": self.message,
                "minutes_left": (left + 59) // 60}


_flow: LoginFlow | None = None
_lock = asyncio.Lock()


def current() -> dict | None:
    _expire()
    return _flow.as_dict() if _flow else None


def _expire() -> None:
    """Снять вход, код к которому так и не пришёл."""
    if _flow and _flow.state == "waiting_code" and time.time() > _flow.started + LOGIN_TTL_SEC:
        _stop(_flow)
        _flow.state = "failed"
        _flow.message = "Код не введён за 10 минут — вход снят. Начните заново."


def _stop(flow: LoginFlow) -> None:
    if flow.alive:
        with contextlib.suppress(ProcessLookupError):
            flow.proc.kill()
    if flow.reader:
        flow.reader.cancel()
    if flow.master >= 0:
        # Сперва снять слежение, потом закрыть: следующий openpty получит тот же
        # номер дескриптора, и оставшаяся запись в цикле событий досталась бы ему.
        with contextlib.suppress(Exception):
            asyncio.get_running_loop().remove_reader(flow.master)
        with contextlib.suppress(OSError):
            os.close(flow.master)
        flow.master = -1


def _clean(raw: str) -> str:
    return _ESCAPES.sub("", raw).replace("\r", "")


def _find_url(raw: str) -> str:
    found = _OSC8_URL.search(raw)
    if found:
        return found.group(1)
    if "\x1b]8;" in raw:
        return ""             # гиперссылка есть, но не дописана — кусок не годится
    found = _PLAIN_URL.search(_clean(raw))
    return found.group(0) if found else ""


async def _read(flow: LoginFlow) -> None:
    """Вывод команды — в память; ссылка — как только появится."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[bytes] = asyncio.Queue()
    fd = flow.master          # свой номер: flow.master обнуляется при снятии входа

    def on_ready() -> None:
        try:
            chunk = os.read(fd, 4096)
        except OSError:
            chunk = b""
        queue.put_nowait(chunk)
        if not chunk:
            loop.remove_reader(fd)

    loop.add_reader(fd, on_ready)
    try:
        while True:
            chunk = await queue.get()
            if not chunk:
                break
            flow.output = (flow.output + chunk.decode("utf-8", "replace"))[-20000:]
            # Ссылка печатается раньше приглашения, так что к приглашению
            # она уже целиком в выводе — раньше вынимать её нельзя, кусок
            # адреса мог прийти без хвоста.
            if _CODE_PROMPT.search(_clean(flow.output)):
                flow.url_seen.set()
    finally:
        if flow.master == fd:
            with contextlib.suppress(Exception):
                loop.remove_reader(fd)
        flow.url_seen.set()


def _tail(flow: LoginFlow, lines: int = 6) -> str:
    """Последние строки вывода — без ссылки: в ней одноразовые параметры входа."""
    text = _PLAIN_URL.sub("‹ссылка›", _clean(flow.output))
    rows = [r.strip() for r in text.splitlines() if r.strip()]
    return "\n".join(rows[-lines:])


async def start() -> dict:
    """Запустить `claude auth login` и дождаться ссылки."""
    global _flow
    async with _lock:
        _expire()
        if _flow and _flow.state in ("starting", "waiting_code", "finishing") and _flow.alive:
            return _flow.as_dict()
        if _flow:
            _stop(_flow)

        flow = LoginFlow()
        _flow = flow
        master, slave = pty.openpty()
        # Широкий терминал: длинная ссылка не переносится по строкам
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 50, 4000, 0, 0))
        try:
            flow.proc = await asyncio.create_subprocess_exec(
                config.CLAUDE_BIN, "auth", "login", "--claudeai",
                stdin=slave, stdout=slave, stderr=slave,
                env={**_env(), "TERM": "xterm-256color", "COLUMNS": "4000"},
                cwd=str(Path.home()), start_new_session=True,
            )
        except OSError as exc:
            os.close(master)
            os.close(slave)
            flow.state = "failed"
            flow.message = f"Не запустился {config.CLAUDE_BIN}: {exc}"
            return flow.as_dict()
        os.close(slave)
        flow.master = master
        flow.reader = asyncio.create_task(_read(flow))

        try:
            await asyncio.wait_for(flow.url_seen.wait(), timeout=URL_WAIT_SEC)
        except asyncio.TimeoutError:
            pass

        flow.url = _find_url(flow.output)
        if flow.url and flow.alive:
            flow.state = "waiting_code"
            flow.started = time.time()
        else:
            _stop(flow)
            flow.state = "failed"
            flow.message = ("Claude Code не выдал ссылку для входа. Возможно, изменился "
                            "его вывод — тогда войдите через SSH: claude, затем /login.")
            tail = _tail(flow)
            if tail:
                flow.message += "\n\nВывод команды:\n" + tail
        return flow.as_dict()


_CODE_OK = re.compile(r"^[A-Za-z0-9#_\-.~]{10,2000}$")


async def submit(code: str) -> dict:
    """Передать код с claude.com, дождаться завершения и проверить вход."""
    async with _lock:
        _expire()
        flow = _flow
        if not flow or flow.state != "waiting_code" or not flow.alive:
            return {"state": "failed", "url": "", "minutes_left": 0,
                    "message": "Вход не начат или уже снят. Нажмите «Войти заново»."}
        code = "".join(code.split())      # при копировании прилипают пробелы и переводы строк
        if not _CODE_OK.match(code):
            return {**flow.as_dict(), "message": "Это не похоже на код с claude.com — "
                                                 "скопируйте его целиком кнопкой «Copy Code»."}

        flow.state = "finishing"
        flow.message = ""
        os.write(flow.master, code.encode() + b"\r")
        try:
            await asyncio.wait_for(flow.proc.wait(), timeout=FINISH_WAIT_SEC)
        except asyncio.TimeoutError:
            pass

        if flow.alive:
            # Команда не вышла: код не приняли, и она ждёт следующего. Ждать
            # второй попытки на том же запуске ненадёжно — начинаем заново.
            _stop(flow)
            flow.state = "failed"
            flow.message = "Код не приняли. Начните вход заново и вставьте свежий код."
            tail = _tail(flow, 3)
            if tail:
                flow.message += "\n\nВывод команды:\n" + tail
            return flow.as_dict()

        if flow.reader:
            with contextlib.suppress(asyncio.TimeoutError, asyncio.CancelledError):
                await asyncio.wait_for(flow.reader, timeout=2)
        _stop(flow)

        if flow.proc.returncode != 0:
            flow.state = "failed"
            flow.message = "Вход не удался."
            tail = _tail(flow, 4)
            if tail:
                flow.message += "\n\nВывод команды:\n" + tail
            return flow.as_dict()

        ok, answer = await check()
        if ok:
            flow.state = "done"
            flow.message = f"Вход выполнен, Claude отвечает: «{answer}»."
        else:
            flow.state = "failed"
            flow.message = "Вход записан, но проверочный вызов не прошёл: " + answer
        return flow.as_dict()


async def cancel() -> None:
    global _flow
    async with _lock:
        if _flow:
            _stop(_flow)
        _flow = None
