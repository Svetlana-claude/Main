"""Запуск Claude для чата и разбор его потока.

Claude запускается в неинтерактивном режиме без инструментов, без CLAUDE.md,
без памяти и настроек, в пустой папке. Сообщения подаются через stdin потоком
JSON: так дописку можно отдать в уже идущий запуск, она станет следующим ходом
того же ответа, а не новым запуском.
"""
import asyncio
import json
import os
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


def argv(model: str, session_id: str | None) -> list[str]:
    cmd = [
        config.CLAUDE_BIN, "-p",
        "--input-format", "stream-json",
        "--output-format", "stream-json",
        "--verbose", "--include-partial-messages",
        "--model", model,
        "--tools", "",
        "--setting-sources", "",
        "--disable-slash-commands",
        "--strict-mcp-config",
        "--system-prompt", SYSTEM_PROMPT,
        "--permission-prompts", "none",
    ]
    if session_id:
        cmd += ["--resume", session_id]
    return cmd


def user_line(text: str) -> bytes:
    msg = {"type": "user", "message": {"role": "user", "content": text}}
    return (json.dumps(msg, ensure_ascii=False) + "\n").encode()


async def start(model: str, session_id: str | None) -> asyncio.subprocess.Process:
    config.CHAT_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    return await asyncio.create_subprocess_exec(
        *argv(model, session_id),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, cwd=str(config.CHAT_DIR), env=child_env(),
    )


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
    """События запуска: init (номер беседы), delta (кусок текста), turn (ход
    закончен: весь текст, вес беседы, ошибка ли)."""
    context = 0
    async for raw in _lines(proc.stdout):
        try:
            event = json.loads(raw)
        except ValueError:
            continue
        kind = event.get("type")
        if kind == "system" and event.get("subtype") == "init":
            yield {"type": "init", "session_id": event.get("session_id")}
        elif kind == "stream_event":
            ev = event.get("event") or {}
            if ev.get("type") == "content_block_delta":
                delta = ev.get("delta") or {}
                if delta.get("type") == "text_delta" and delta.get("text"):
                    yield {"type": "delta", "text": delta["text"]}
            elif ev.get("type") == "message_start":
                context = _context(((ev.get("message") or {}).get("usage")) or {}) or context
        elif kind == "result":
            usage = event.get("usage") or {}
            yield {
                "type": "turn",
                "text": str(event.get("result") or ""),
                "is_error": bool(event.get("is_error")),
                "session_id": event.get("session_id"),
                "context": context or _context(usage),
            }
