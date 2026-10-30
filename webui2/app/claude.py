"""Запуск Claude и разбор его потока.

В чате Claude запускается без CLAUDE.md, без памяти и настроек, в пустой
папке и без инструментов; с переключателем «Доступ к проектам» — с чтением
папок проектов (Read, Glob, Grep), без правки и команд. В теме проекта — полноценно, в папке проекта, с её
CLAUDE.md и памятью; что можно, решают галочки проекта. Сообщения подаются
через stdin потоком JSON: так дописку можно отдать в уже идущий запуск, она
станет следующим ходом того же ответа, а не новым запуском.
"""
import asyncio
import json
import os
from pathlib import Path
from typing import AsyncIterator

from . import config

SYSTEM_PROMPT = """Ты — Claude, собеседник Светланы. Это просто разговор: у тебя нет
инструментов, ты ничего не делаешь на сервере. Для работы с файлами и проектами
есть вкладка «Проекты» — если просят сделать, а не обсудить, скажи об этом.

Как пишешь:
- только по-русски, на «ты», по имени — Светлана или Светик;
- коротко и бытовым языком, без жаргона; термин, без которого никак, поясняй
  в двух словах;
- о себе — в мужском роде; к Светлане — в женском;
- время — только по Москве, с пометкой «по Москве»;
- догадку помечай «скорее всего»;
- если просьбу можно понять двояко — одно уточнение, начиная со слова «Уточню:»;
- не напоминай про GitHub;
- никаких ключей, паролей и секретов в ответах."""

SILENCE_SEC = 1800          # столько молчания — запуск считается зависшим
READ_CHUNK = 64 * 1024

# Ключи сайта не уходят в запуск Claude
_SITE_ENV = ("WEBUI2_", "ROOT_PATH", "SECRET_KEY")


def child_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if not k.startswith(_SITE_ENV)}


def _base(model: str) -> list[str]:
    return [
        config.CLAUDE_BIN, "-p",
        "--input-format", "stream-json",
        "--output-format", "stream-json",
        "--verbose", "--include-partial-messages",
        "--model", model,
    ]


# Ключ и база сайта закрыты в любом режиме: для файловых инструментов — по
# папке (абсолютный путь в правиле пишется с двумя косыми), для команд — по
# упоминанию папки или файла в строке команды.
def secret_deny() -> list[str]:
    dirs = sorted({str(config.ENV_FILE.parent), str(config.DB_PATH.parent)})
    rules = [f"{tool}(/{d}/**)" for d in dirs for tool in ("Read", "Edit", "Write")]
    names = sorted({config.ENV_FILE.name, config.DB_PATH.name})
    rules += [f"Bash(*{d.removeprefix(str(Path.home()))}*)" for d in dirs]
    rules += [f"Bash(*{name}*)" for name in names]
    return rules


BASH_FAMILY = ["Bash", "BashOutput", "KillShell"]


# Вопросы-уточнения Claude задаёт текстом в ответе, а не отдельным окном
NO_ASK_TOOLS = ["AskUserQuestion"]


def project_argv(model: str, session_id: str | None, project: dict) -> list[str]:
    """Тема проекта. Без галочек — чтение и правка файлов в папке проекта;
    «Запускать команды» — ещё и команды; «Полный доступ» — всё без вопросов.
    Что сверх разрешённого, Claude спрашивает у сайта (control_request в
    потоке), сайт — у хозяйки на странице «Разрешения». Безопасные команды
    только для чтения Claude выполняет сам, без вопроса."""
    if project["slug"] == config.MODELS_SLUG:
        return models_argv(model, session_id, project)
    cmd = _base(model)
    if project["full_access"]:
        cmd += ["--permission-mode", "bypassPermissions",
                "--disallowed-tools", *NO_ASK_TOOLS, *secret_deny()]
    else:
        cmd += ["--permission-mode", "acceptEdits", "--permission-prompt-tool", "stdio"]
        if project["allow_commands"]:
            cmd += ["--allowed-tools", *BASH_FAMILY]
        cmd += ["--disallowed-tools", *NO_ASK_TOOLS, *secret_deny()]
    if session_id:
        cmd += ["--resume", session_id]
    return cmd


# Окно чата в редакторе 3D: только файлы этой папки. Команд нет, спросить не у кого
# (вопрос — сразу отказ), галочки проекта здесь не действуют. Чужие настройки не
# подхватываются, рабочая папка всего хозяйства закрыта отдельным запретом.
MODELS_TOOLS = ["Read", "Write", "Edit", "Glob", "Grep"]


def models_argv(model: str, session_id: str | None, project: dict) -> list[str]:
    cmd = _base(model) + [
        "--tools", ",".join(MODELS_TOOLS),
        "--setting-sources", "project",
        "--strict-mcp-config",
        "--disable-slash-commands",
        "--permission-mode", "acceptEdits",
        "--permission-prompts", "none",
        "--disallowed-tools", *NO_ASK_TOOLS, *secret_deny(),
        *[f"{tool}(/{config.PROJECT_DIR.parent}/**)" for tool in MODELS_TOOLS],
    ]
    if session_id:
        cmd += ["--resume", session_id]
    return cmd


# Чат с доступом к проектам: только чтение, только папки проектов
READ_TOOLS = ["Read", "Glob", "Grep"]
# Файлы с ключами и паролями закрыты и для чтения — в каждой папке проекта
# (правило с абсолютным путём пишется с двумя косыми; без пути оно считалось
# бы от пустой папки чата и не действовало)
SECRET_FILES = [".env", ".env.*", "*.key", "*.pem", "id_rsa*", "id_ed25519*"]

ACCESS_PROMPT = """

Доступ к проектам. В этом разговоре ты можешь читать файлы проектов Светланы —
только читать: смотреть список файлов, открывать их, искать по тексту. Править,
удалять и запускать ничего нельзя; для работы есть темы во вкладке «Проекты».
Проекты (название — папка):
{projects}
Что Светлана загрузила в «Файлы проекта», лежит в папке downloads внутри проекта.
Читай только нужное: сначала список, потом конкретный файл; длинный — по частям.
Картинки открывай, только когда она просит, — они дороже текста."""


def access_rules(paths: list[str]) -> list[str]:
    return [f"{tool}(/{path.rstrip('/')}/**/{name})"
            for path in paths for name in SECRET_FILES for tool in ("Read", "Grep")]


def argv(model: str, session_id: str | None, projects: list[dict] | None = None) -> list[str]:
    """Чат. projects — None: просто разговор, без инструментов; список —
    разговор с доступом к этим папкам только на чтение."""
    prompt = SYSTEM_PROMPT
    if projects is None:
        tools = [""]
    else:
        tools = [",".join(READ_TOOLS)]
        lines = "\n".join(f"- {p['name']} — {p['path']}" for p in projects) or "- (проектов пока нет)"
        prompt = SYSTEM_PROMPT.replace(
            "Это просто разговор: у тебя нет\nинструментов, ты ничего не делаешь на сервере.",
            "Это разговор: на сервере ты ничего\nне делаешь.") + ACCESS_PROMPT.format(projects=lines)
    cmd = _base(model) + [
        "--tools", *tools,
        "--setting-sources", "",
        "--disable-slash-commands",
        "--strict-mcp-config",
        "--system-prompt", prompt,
        "--permission-prompts", "none",
    ]
    if projects:
        cmd += ["--add-dir", *[p["path"] for p in projects],
                "--allowed-tools", *READ_TOOLS,
                "--disallowed-tools", *access_rules([p["path"] for p in projects]), *secret_deny()]
    if session_id:
        cmd += ["--resume", session_id]
    return cmd


def control_line(request_id: str, allow: bool, data: dict | None = None,
                 message: str = "") -> bytes:
    """Ответ на вопрос Claude о разрешении."""
    answer = {"behavior": "allow", "updatedInput": data or {}} if allow else \
        {"behavior": "deny", "message": message}
    msg = {"type": "control_response",
           "response": {"subtype": "success", "request_id": request_id, "response": answer}}
    return (json.dumps(msg, ensure_ascii=False) + "\n").encode()


def control_error(request_id: str) -> bytes:
    """Ответ на незнакомый служебный вопрос: чтобы Claude не ждал зря."""
    msg = {"type": "control_response",
           "response": {"subtype": "error", "request_id": request_id, "error": "не поддерживается"}}
    return (json.dumps(msg) + "\n").encode()


def user_line(text: str) -> bytes:
    msg = {"type": "user", "message": {"role": "user", "content": text}}
    return (json.dumps(msg, ensure_ascii=False) + "\n").encode()


async def start(model: str, session_id: str | None, project: dict | None = None,
                read_projects: list[dict] | None = None) -> asyncio.subprocess.Process:
    if project:
        cmd, cwd = project_argv(model, session_id, project), project["path"]
    else:
        config.CHAT_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
        cmd, cwd = argv(model, session_id, read_projects), str(config.CHAT_DIR)
    return await asyncio.create_subprocess_exec(
        *cmd, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, cwd=cwd, env=child_env(),
        limit=1024 * 1024,
    )


def _short(path: str) -> str:
    return path.rstrip("/").rsplit("/", 1)[-1] if path else ""


def tool_status(name: str, data: dict) -> str:
    """Что Claude делает сейчас — одной строкой по-русски."""
    data = data or {}
    if name in ("Read", "NotebookRead"):
        return f"Читаю {_short(data.get('file_path', ''))}…"
    if name in ("Edit", "MultiEdit", "Write", "NotebookEdit"):
        return f"Правлю {_short(data.get('file_path', '') or data.get('notebook_path', ''))}…"
    if name in ("Bash", "BashOutput"):
        what = data.get("description") or " ".join(str(data.get("command", "")).split())
        return f"Выполняю: {what[:80]}"
    if name in ("Glob", "Grep"):
        return "Ищу в файлах…"
    if name == "WebSearch":
        return "Ищу в интернете…"
    if name == "WebFetch":
        return "Открываю страницу…"
    if name in ("Task", "Agent"):
        return "Поручаю часть работы помощнику…"
    if name == "TodoWrite":
        return "Составляю план…"
    return "Работаю…"


def ask_text(name: str, data: dict) -> tuple[str, str]:
    """О чём просит Claude: (что сделать — по-русски, подробность)."""
    data = data or {}
    if name in ("Bash", "BashOutput", "KillShell"):
        return "Выполнить команду", str(data.get("command") or data.get("bash_id") or data.get("shell_id") or "")
    if name in ("Edit", "MultiEdit", "Write", "NotebookEdit"):
        return "Изменить файл", str(data.get("file_path") or data.get("notebook_path") or "")
    if name in ("Read", "NotebookRead"):
        return "Прочитать файл", str(data.get("file_path") or "")
    if name in ("Glob", "Grep"):
        return "Искать в файлах", " ".join(str(data.get(k)) for k in ("pattern", "path") if data.get(k))
    if name == "WebFetch":
        return "Открыть страницу", str(data.get("url") or "")
    if name == "WebSearch":
        return "Искать в интернете", str(data.get("query") or "")
    detail = json.dumps(data, ensure_ascii=False)
    return f"Инструмент {name}", detail[:2000]


async def _lines(stream: asyncio.StreamReader) -> AsyncIterator[bytes]:
    """Построчно, без предела на длину строки (штатный readline рвётся на 64 КБ)."""
    buf = bytearray()
    while True:
        chunk = await asyncio.wait_for(stream.read(READ_CHUNK), timeout=SILENCE_SEC)
        if not chunk:
            break
        buf.extend(chunk)
        while (nl := buf.find(b"\n")) >= 0:
            line = bytes(buf[:nl])
            del buf[:nl + 1]
            yield line
    if buf:
        yield bytes(buf)


def _context(usage: dict) -> int:
    return sum(int(usage.get(k) or 0) for k in
               ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))


async def events(proc: asyncio.subprocess.Process) -> AsyncIterator[dict]:
    """События запуска: init (номер беседы), start (новое сообщение Claude —
    прежний черновой текст сбрасывается), delta (кусок текста), status (что
    делает), ask / unask (просит разрешения / вопрос снят), control (другой
    служебный вопрос), turn (ход закончен: весь текст, вес беседы, ошибка ли).
    События помощников (parent_tool_use_id) не показываются."""
    context = 0
    async for raw in _lines(proc.stdout):
        try:
            event = json.loads(raw)
        except ValueError:
            continue
        kind = event.get("type")
        if kind == "system" and event.get("subtype") == "init":
            yield {"type": "init", "session_id": event.get("session_id")}
        elif kind == "control_request":
            req = event.get("request") or {}
            rid = str(event.get("request_id") or "")
            if req.get("subtype") == "can_use_tool":
                yield {"type": "ask", "request_id": rid, "tool": str(req.get("tool_name") or ""),
                       "input": req.get("input") if isinstance(req.get("input"), dict) else {}}
            else:
                yield {"type": "control", "request_id": rid}
        elif kind == "control_cancel_request":
            yield {"type": "unask", "request_id": str(event.get("request_id") or "")}
        elif event.get("parent_tool_use_id"):
            continue
        elif kind == "stream_event":
            ev = event.get("event") or {}
            if ev.get("type") == "content_block_delta":
                delta = ev.get("delta") or {}
                if delta.get("type") == "text_delta" and delta.get("text"):
                    yield {"type": "delta", "text": delta["text"]}
            elif ev.get("type") == "message_start":
                context = _context(((ev.get("message") or {}).get("usage")) or {}) or context
                yield {"type": "start"}
        elif kind == "assistant":
            for block in (event.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    yield {"type": "status", "text": tool_status(block.get("name", ""), block.get("input"))}
        elif kind == "result":
            usage = event.get("usage") or {}
            yield {
                "type": "turn",
                "text": str(event.get("result") or ""),
                "is_error": bool(event.get("is_error")),
                "session_id": event.get("session_id"),
                "context": context or _context(usage),
            }


# ── Разовые запуски: проверка и удаление проекта ─────────────────────────

ONCE_SEC = 1200

LOOK_PROMPT = """Проект в этой папке ({path}) собираются удалить. Ничего не меняй и
не удаляй — только посмотри, что проект завёл на сервере ВНЕ своей папки: службы
и таймеры (systemctl и systemctl --user), задания cron, настройки nginx и других
программ, которые ссылаются на эту папку, контейнеры, запущенные процессы из
этой папки, файлы и папки вне неё, созданные для проекта. Смотри по истории git,
по CLAUDE.md и файлам проекта, по самим службам и настройкам.

Папку самого сайта ({site}) и всё, что относится к сайту, в список не включай.

Ответь по-русски, коротко, для человека без технических знаний: список того,
что нужно убрать, по пункту на строку, с путём или названием. Если вне папки
ничего нет — так и напиши одной фразой: «Вне папки проекта ничего нет»."""

REMOVE_PROMPT = """Проект в этой папке ({path}) удаляется, хозяйка согласилась.
Убери то, что проект завёл на сервере вне своей папки, — ровно по этому списку
и ничего больше:

{report}

Службы сначала останови и выключи. Саму папку проекта НЕ удаляй — её удалит
сайт после тебя. Папку сайта ({site}) не трогай. Если что-то убрать не вышло
(например, нужны права, которых нет), так и напиши. Ответь по-русски коротко:
что убрано и что не вышло."""


def once_argv(model: str, remove: bool) -> list[str]:
    cmd = [config.CLAUDE_BIN, "-p", "--output-format", "json", "--model", model,
           "--no-session-persistence"]
    if remove:
        return cmd + ["--permission-mode", "bypassPermissions", "--disallowed-tools", *secret_deny()]
    return cmd + ["--permission-mode", "default", "--permission-prompts", "none",
                  "--allowed-tools", "Bash", "Read", "Glob", "Grep",
                  "--disallowed-tools", "Edit", "Write", "NotebookEdit", *secret_deny()]


async def once(prompt: str, cwd: str, remove: bool) -> tuple[bool, str]:
    """Разовый запуск без продолжения беседы. Вопрос — через stdin, чтобы его
    не съел список правил. Возвращает (удалось ли, текст ответа)."""
    proc = await asyncio.create_subprocess_exec(
        *once_argv(config.TOPIC_MODEL, remove), stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        cwd=cwd, env=child_env())
    try:
        out, err = await asyncio.wait_for(proc.communicate(prompt.encode()), timeout=ONCE_SEC)
    except asyncio.TimeoutError:
        proc.kill()
        return False, "Claude не ответил за 20 минут"
    try:
        data = json.loads(out)
    except ValueError:
        tail = err.decode("utf-8", "replace").strip().splitlines()[-1:] or ["нет ответа"]
        return False, tail[0]
    return not data.get("is_error"), str(data.get("result") or "")
