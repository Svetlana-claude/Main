"""Проверка: драйвер отдаёт расход токенов по ходу ответа.

Из этих событий информационная строка блока «Ход работы» показывает, что
процесс идёт, — иначе там был бы только таймер. Счёт выходных токенов
накопительный в пределах шага и обнуляется на новом шаге, поэтому начало
шага должно приходить отдельным признаком.

Запуск:  .venv/bin/python tests/check_usage_events.py
"""
import asyncio
import stat
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services import claude_driver     # noqa: E402

# Подставной движок: два шага работы, в каждом счёт выходных токенов свой
FAKE_ENGINE = '''#!{python}
import json, sys

def emit(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\\n")
    sys.stdout.flush()

def stream(ev):
    emit({{"type": "stream_event", "event": ev}})

emit({{"type": "system", "subtype": "init", "session_id": "test-session", "model": "opus"}})

# Первый шаг: 4 → 120 токенов
stream({{"type": "message_start", "message": {{"usage": {{"input_tokens": 1500, "output_tokens": 4}}}}}})
stream({{"type": "message_delta", "usage": {{"output_tokens": 60}}}})
stream({{"type": "message_delta", "usage": {{"output_tokens": 120}}}})

# Второй шаг: счёт выхода начинается заново
stream({{"type": "message_start", "message": {{"usage": {{"input_tokens": 1800, "output_tokens": 2}}}}}})
stream({{"type": "message_delta", "usage": {{"output_tokens": 35}}}})

emit({{"type": "result", "session_id": "test-session", "result": "готово",
      "usage": {{"input_tokens": 3300, "output_tokens": 155}}}})
'''


async def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        engine = Path(tmp) / "fake-claude"
        engine.write_text(FAKE_ENGINE.format(python=sys.executable), encoding="utf-8")
        engine.chmod(engine.stat().st_mode | stat.S_IEXEC)

        original = claude_driver.config.CLAUDE_BIN
        claude_driver.config.CLAUDE_BIN = str(engine)
        try:
            events = [e async for e in claude_driver.run("проверка", with_tools=False)]
        finally:
            claude_driver.config.CLAUDE_BIN = original

    usage = [e for e in events if e["type"] == "usage"]
    if not usage:
        print("ПРОВАЛ: расход по ходу ответа не доходит — строке нечего показывать")
        return 1

    starts = [e for e in usage if e.get("new_message")]
    if len(starts) != 2:
        print(f"ПРОВАЛ: начало шага отмечено {len(starts)} раз вместо 2 — "
              "счётчик на новом шаге откатится назад")
        return 1

    # Так считает панель: сумма завершённых шагов плюс текущий
    done = 0
    step = 0
    for e in usage:
        if e.get("new_message"):
            done += step
            step = 0
        if "output_tokens" in e:
            step = e["output_tokens"]
    if done + step != 155:
        print(f"ПРОВАЛ: насчитано {done + step} токенов выхода вместо 155")
        return 1

    print(f"OK: расход доходит ({len(usage)} событий), на конец шагов — {done + step} токенов")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
