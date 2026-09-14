"""Проверка: потолок контекста доходит до `claude`, сжатие и размер контекста видны.

Что должно выполняться:
* настройка потолка уходит в окружение `claude` как CLAUDE_CODE_AUTO_COMPACT_WINDOW,
  ниже 100 тыс. поднимается до границы, при нуле переменной нет вовсе — даже
  если она была в окружении самого приложения;
* начало, итог и отказ сжатия приходят событиями `compact`;
* размер контекста шага (вход + чтение + запись кэша) приходит в `usage`
  и в итоге ответа, причём по основному агенту, а не вспомогательному.

Запуск:  .venv/bin/python tests/check_compact_context.py
"""
import asyncio
import json
import os
import stat
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services import claude_driver     # noqa: E402

# Подставной движок: печатает полученный потолок, шаг, автосжатие, ещё шаг
FAKE_ENGINE = '''#!{python}
import json, os, sys

def emit(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\\n")
    sys.stdout.flush()

def start(usage, parent=None):
    emit({{"type": "stream_event", "parent_tool_use_id": parent,
          "event": {{"type": "message_start", "message": {{"usage": usage}}}}}})

emit({{"type": "system", "subtype": "init", "session_id": "s1", "model": "opus"}})
emit({{"type": "assistant", "message": {{"content": [
    {{"type": "text", "text": "окно=" + os.environ.get("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "нет")}}]}}}})

start({{"input_tokens": 10, "cache_read_input_tokens": 240000, "cache_creation_input_tokens": 5000}})
emit({{"type": "system", "subtype": "status", "status": "compacting", "session_id": "s1"}})
emit({{"type": "system", "subtype": "compact_boundary", "session_id": "s1",
      "compact_metadata": {{"trigger": "auto", "pre_tokens": 245010, "post_tokens": 1900}}}})
start({{"input_tokens": 12, "cache_read_input_tokens": 18000, "cache_creation_input_tokens": 3000}})
# Вспомогательный агент со своей короткой историей — контекст темы не меняет
start({{"input_tokens": 5, "cache_read_input_tokens": 900, "cache_creation_input_tokens": 0}}, parent="tool-1")
emit({{"type": "system", "subtype": "status", "status": None, "compact_result": "failed",
      "compact_error": "too_few_groups", "session_id": "s1"}})
emit({{"type": "result", "session_id": "s1", "usage": {{"input_tokens": 22, "output_tokens": 50}}}})
'''

failures: list[str] = []


def check(ok: bool, what: str) -> None:
    print(("OK   " if ok else "FAIL ") + what)
    if not ok:
        failures.append(what)


async def run_with(engine: Path, window: int) -> list[dict]:
    original = claude_driver.config.CLAUDE_BIN
    claude_driver.config.CLAUDE_BIN = str(engine)
    try:
        return [e async for e in claude_driver.run("проверка", compact_window=window)]
    finally:
        claude_driver.config.CLAUDE_BIN = original


def window_seen(events: list[dict]) -> str:
    texts = [e["text"] for e in events if e["type"] == "text"]
    return texts[0].removeprefix("окно=") if texts else "?"


async def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        engine = Path(tmp) / "fake-claude"
        engine.write_text(FAKE_ENGINE.format(python=sys.executable), encoding="utf-8")
        engine.chmod(engine.stat().st_mode | stat.S_IEXEC)

        # Унаследованное значение не должно подменять настройку
        os.environ[claude_driver.COMPACT_ENV] = "777777"

        events = await run_with(engine, 250_000)
        check(window_seen(events) == "250000", f"потолок 250000 дошёл до claude ({window_seen(events)})")

        low = await run_with(engine, 60_000)
        check(window_seen(low) == "100000", f"60000 поднят до границы 100000 ({window_seen(low)})")

        off = await run_with(engine, 0)
        check(window_seen(off) == "нет", f"при нуле переменной нет, унаследованная убрана ({window_seen(off)})")

    compact = [e for e in events if e["type"] == "compact"]
    print("  compact:", json.dumps(compact, ensure_ascii=False))
    check([e["state"] for e in compact] == ["start", "done", "failed"],
          "сжатие: начало, итог и отказ пришли событиями")
    done = next((e for e in compact if e["state"] == "done"), {})
    check(done.get("trigger") == "auto" and done.get("pre_tokens") == 245010
          and done.get("post_tokens") == 1900, "в итоге сжатия — причина, было и стало")
    failed = next((e for e in compact if e["state"] == "failed"), {})
    check(failed.get("reason") == claude_driver.COMPACT_REASONS["too_few_groups"],
          f"у отказа причина словами ({failed.get('reason')})")

    contexts = [e.get("context_tokens") for e in events if e["type"] == "usage"]
    print("  context в usage:", contexts)
    check(contexts[:2] == [245010, 21012], "контекст шага = вход + чтение + запись кэша")
    check(contexts[2:] == [21012], "шаг вспомогательного агента контекст темы не меняет")

    result = next((e for e in events if e["type"] == "result"), {})
    check(result.get("context_tokens") == 21012, f"контекст в итоге ответа ({result.get('context_tokens')})")

    check(claude_driver.compact_window("abc") == 0 and claude_driver.compact_window("2000000") == 1_000_000,
          "испорченная настройка — ноль, чрезмерная — до верхней границы")

    print("ПРОВАЛОВ:", len(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
