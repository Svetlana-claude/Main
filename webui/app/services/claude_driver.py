"""Драйвер Claude Code.

Приложение не обращается к Messages API и не реализует инструменты заново —
оно запускает тот же `claude`, что работает в терминале, в неинтерактивном режиме
и разбирает поток JSON. Отсюда следуют два свойства:

* аутентификация — та же подписка, отдельный API-ключ не нужен;
* правила из CLAUDE.md, скиллы и память подхватываются сами.

Чатики и темы проектов работают на одном движке, разница только в правах:
у чатика инструменты выключены, у темы проекта доступен её рабочий каталог.
"""
import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator

from .. import config

# Инструменты, которые в чатике не нужны: это болтовня, а не работа с файлами
CHAT_DISALLOWED = [
    "Bash", "Edit", "Write", "Read", "Glob", "Grep",
    "WebSearch", "WebFetch", "NotebookEdit", "Task",
]

# Что доступно в теме проекта помимо явно разрешённого bash
PROJECT_ALLOWED = ["Read", "Write", "Edit", "Glob", "Grep", "WebSearch", "WebFetch"]

# Всё, чем можно выполнить команду: запрещается целиком, иначе запрет обходится
# соседним инструментом того же семейства
BASH_FAMILY = ["Bash", "BashOutput", "KillShell"]

RUN_TIMEOUT_SEC = 1800  # 30 минут: агентская работа бывает долгой

# Каким куском забирается вывод движка
READ_CHUNK = 64 * 1024

# Потолок на одну строку JSON. Строка длиннее — уже не событие, а что-то нештатное,
# копить её в памяти незачем: такая строка пропускается, поток продолжается.
MAX_LINE_BYTES = 64 * 1024 * 1024

# Сколько ответов выполняется прямо сейчас. По этому счётчику перезапуск
# приложения ждёт: остановка службы гасит и запущенный ею `claude`, а ответ
# пишется в базу только по завершении — значит оборванный ответ пропадёт.
_active_runs = 0


def active_runs() -> int:
    """Число выполняющихся ответов. Ноль — приложение можно перезапускать."""
    return _active_runs


@dataclass
class RunResult:
    """Итог запуска. Поля соответствуют тому, что отдаёт CLI в JSON."""
    text: str = ""
    session_id: str | None = None
    model: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read: int = 0
    cache_write: int = 0
    cost_usd: float = 0.0
    duration_ms: int = 0
    num_turns: int = 0
    is_error: bool = False
    error_message: str = ""
    tools_used: list[str] = field(default_factory=list)


def _build_argv(
    prompt: str,
    *,
    model: str,
    session_id: str | None,
    with_tools: bool,
    workdir: Path | None,
    allow_bash: bool,
) -> list[str]:
    argv = [
        config.CLAUDE_BIN,
        "-p", prompt,
        "--output-format", "stream-json",
        "--include-partial-messages",
        "--verbose",
        "--model", model,
    ]

    if session_id:
        argv += ["--resume", session_id]

    if with_tools:
        allowed = list(PROJECT_ALLOWED)
        if allow_bash:
            allowed.append("Bash")
        else:
            # --allowed-tools только авто-одобряет перечисленное и НЕ запрещает
            # остальное: с одним этим флагом Bash всё равно выполняется.
            # Запрет даёт только явный --disallowed-tools.
            argv += ["--disallowed-tools", *BASH_FAMILY]
        argv += ["--allowed-tools", *allowed]
        argv += ["--permission-mode", "acceptEdits"]
        if workdir:
            argv += ["--add-dir", str(workdir)]
    else:
        argv += ["--disallowed-tools", *CHAT_DISALLOWED]

    # Ничто не должно ждать ответа на запрос разрешения: некому нажимать кнопку.
    # Всё, что вышло бы за разрешённое, отклоняется автоматически.
    argv += ["--permission-prompts", "none"]
    return argv


async def _iter_lines(
    stream: asyncio.StreamReader, timeout: float | None = None
) -> AsyncIterator[bytes]:
    """Читает поток построчно без ограничения на длину строки.

    Штатный `StreamReader.readline()` держит буфер в 64 КиБ и на строке длиннее
    падает с «Separator is not found, and chunk exceed the limit», а вызывающая
    сторона показывает это как «Сбой обработки». Движок такие строки выдаёт
    постоянно: в одну строку JSON укладывается и содержимое прочитанного файла,
    и вывод команды, и текст ответа целиком.

    `timeout` считается на кусок, а не на строку, — это время молчания движка.
    """
    buf = bytearray()
    skipping = False     # строка переросла потолок: досматриваем её до конца и выбрасываем
    while True:
        chunk = await asyncio.wait_for(stream.read(READ_CHUNK), timeout=timeout)
        if not chunk:
            break
        buf.extend(chunk)
        while True:
            nl = buf.find(b"\n")
            if nl < 0:
                break
            line = bytes(buf[:nl])
            del buf[: nl + 1]
            if skipping:
                skipping = False     # это был хвост выброшенной строки
                continue
            yield line
        if len(buf) > MAX_LINE_BYTES:
            buf.clear()
            skipping = True
    if buf and not skipping:
        yield bytes(buf)     # последняя строка без перевода в конце


def _extract_text(message: dict) -> str:
    """Собирает текст из блоков content ответа."""
    parts = []
    for block in message.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "".join(parts)


async def run(
    prompt: str,
    *,
    model: str = "opus",
    session_id: str | None = None,
    with_tools: bool = False,
    workdir: Path | None = None,
    allow_bash: bool = False,
) -> AsyncIterator[dict]:
    """Запускает Claude Code и отдаёт события по мере поступления.

    Типы событий: init, delta, tool, text, result, error.
    Вызывающая сторона переправляет их в браузер через SSE.
    """
    argv = _build_argv(
        prompt,
        model=model,
        session_id=session_id,
        with_tools=with_tools,
        workdir=workdir,
        allow_bash=allow_bash,
    )
    cwd = str(workdir) if workdir else str(config.REPO_ROOT)

    global _active_runs
    _active_runs += 1
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
    except FileNotFoundError:
        _active_runs -= 1
        yield {"type": "error", "message": f"Не найден исполняемый файл {config.CLAUDE_BIN}"}
        return

    result = RunResult(session_id=session_id)
    stderr_tail: list[str] = []

    async def drain_stderr() -> None:
        assert proc.stderr is not None
        async for raw in _iter_lines(proc.stderr):
            line = raw.decode("utf-8", "replace").rstrip()
            if line:
                stderr_tail.append(line)
                del stderr_tail[:-20]     # держим только хвост, он и нужен в ошибке

    stderr_task = asyncio.create_task(drain_stderr())

    try:
        assert proc.stdout is not None
        async for raw in _iter_lines(proc.stdout, RUN_TIMEOUT_SEC):
            line = raw.decode("utf-8", "replace").strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue     # строка не JSON — служебный вывод, пропускаем

            etype = event.get("type")

            if etype == "system" and event.get("subtype") == "init":
                result.session_id = event.get("session_id") or result.session_id
                result.model = event.get("model") or result.model
                yield {"type": "init", "session_id": result.session_id}

            elif etype == "stream_event":
                # Частичные куски текста — из них складывается живой вывод
                ev = event.get("event") or {}
                if ev.get("type") == "content_block_delta":
                    delta = ev.get("delta") or {}
                    if delta.get("type") == "text_delta":
                        chunk = delta.get("text", "")
                        if chunk:
                            yield {"type": "delta", "text": chunk}

                # Расход по ходу ответа — для информационной строки «Хода работы».
                # В пределах одного шага значение накопительное, на новом шаге
                # счёт начинается заново, поэтому начало шага отмечается особо.
                elif ev.get("type") == "message_start":
                    usage = ((ev.get("message") or {}).get("usage")) or {}
                    yield {
                        "type": "usage",
                        "new_message": True,
                        "input_tokens": int(usage.get("input_tokens") or 0),
                        "output_tokens": int(usage.get("output_tokens") or 0),
                    }
                elif ev.get("type") == "message_delta":
                    usage = ev.get("usage") or {}
                    if usage.get("output_tokens") is not None:
                        yield {
                            "type": "usage",
                            "new_message": False,
                            "output_tokens": int(usage.get("output_tokens") or 0),
                        }

            elif etype == "assistant":
                message = event.get("message") or {}
                text = _extract_text(message)
                if text:
                    result.text = text
                    yield {"type": "text", "text": text}
                for block in message.get("content") or []:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        name = block.get("name", "?")
                        result.tools_used.append(name)
                        yield {"type": "tool", "name": name, "input": block.get("input")}

            elif etype == "result":
                usage = event.get("usage") or {}
                result.session_id = event.get("session_id") or result.session_id
                result.input_tokens = int(usage.get("input_tokens") or 0)
                result.output_tokens = int(usage.get("output_tokens") or 0)
                result.cache_read = int(usage.get("cache_read_input_tokens") or 0)
                result.cache_write = int(usage.get("cache_creation_input_tokens") or 0)
                result.cost_usd = float(event.get("total_cost_usd") or 0.0)
                result.duration_ms = int(event.get("duration_ms") or 0)
                result.num_turns = int(event.get("num_turns") or 0)
                result.is_error = bool(event.get("is_error"))
                if event.get("result"):
                    result.text = str(event["result"])
                # В modelUsage попадает и вспомогательная модель (например haiku
                # на служебные операции внутри Claude Code). Брать первый ключ
                # нельзя — порядок произвольный. Основной считаем ту, что выдала
                # больше всего токенов на выход.
                model_usage = event.get("modelUsage") or {}
                if model_usage:
                    result.model = max(
                        model_usage,
                        key=lambda name: (model_usage[name] or {}).get("outputTokens", 0),
                    )
                if result.is_error:
                    result.error_message = str(event.get("subtype") or "ошибка выполнения")

        await proc.wait()
        stderr_task.cancel()

        if proc.returncode != 0 and not result.text:
            tail = "\n".join(stderr_tail[-5:]) or f"код возврата {proc.returncode}"
            yield {"type": "error", "message": tail}
            return

        yield {
            "type": "result",
            "text": result.text,
            "session_id": result.session_id,
            "model": result.model,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "cache_read": result.cache_read,
            "cache_write": result.cache_write,
            "cost_usd": result.cost_usd,
            "duration_ms": result.duration_ms,
            "num_turns": result.num_turns,
            "is_error": result.is_error,
            "error_message": result.error_message,
            "tools_used": result.tools_used,
        }
    except asyncio.TimeoutError:
        # Молчание движка дольше RUN_TIMEOUT_SEC: ждать больше нечего
        proc.kill()
        yield {"type": "error", "message": "Превышено время ожидания ответа"}
        return
    finally:
        _active_runs -= 1
        stderr_task.cancel()
        if proc.returncode is None:
            proc.kill()


async def make_title(text: str, model: str = "haiku") -> str:
    """Короткое название диалога по первому сообщению.

    Отдельный дешёвый вызов: заголовок «Новый чат» через неделю ничего не говорит.
    """
    prompt = (
        "Придумай короткое название на русском (2-5 слов) для диалога, который "
        "начинается такой репликой. Ответь только названием, без кавычек и точки.\n\n"
        + text[:500]
    )
    title = ""
    async for event in run(prompt, model=model, with_tools=False):
        if event["type"] == "result":
            title = (event.get("text") or "").strip().strip('"').strip()
    title = " ".join(title.split())[:80]
    return title or "Без названия"
