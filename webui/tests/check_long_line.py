"""Проверка: длинная строка в потоке движка не срывает ответ.

Ловит дефект, из-за которого работа обрывалась ошибкой
«Сбой обработки: Separator is not found, and chunk exceed the limit»:
`StreamReader.readline()` держит буфер в 64 КиБ, а движок укладывает в одну
строку JSON и содержимое прочитанного файла, и вывод команды, и текст ответа.

Запуск:  .venv/bin/python tests/check_long_line.py
"""
import asyncio
import os
import stat
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services import claude_driver     # noqa: E402

# Заведомо больше 64 КиБ — того буфера, на котором всё падало
PAYLOAD_LEN = 300_000

# Подставной движок: настоящие аргументы игнорирует, выдаёт stream-json, где
# строка с ответом приходит кусками и без перевода строки до самого конца —
# это и есть случай «Separator is not found».
FAKE_ENGINE = '''#!{python}
import json, sys, time

payload = "я" * {payload_len}

def emit(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\\n")
    sys.stdout.flush()

emit({{"type": "system", "subtype": "init", "session_id": "test-session", "model": "opus"}})

# Длинную строку отдаём по кускам, как это делает настоящий движок
line = json.dumps(
    {{"type": "assistant", "message": {{"content": [{{"type": "text", "text": payload}}]}}}},
    ensure_ascii=False,
)
for i in range(0, len(line), 8192):
    sys.stdout.write(line[i:i + 8192])
    sys.stdout.flush()
    time.sleep(0.005)
sys.stdout.write("\\n")
sys.stdout.flush()

emit({{"type": "result", "session_id": "test-session", "result": payload,
      "usage": {{"input_tokens": 1, "output_tokens": 2}}}})
'''


async def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        engine = Path(tmp) / "fake-claude"
        engine.write_text(
            FAKE_ENGINE.format(python=sys.executable, payload_len=PAYLOAD_LEN),
            encoding="utf-8",
        )
        engine.chmod(engine.stat().st_mode | stat.S_IEXEC)

        original = claude_driver.config.CLAUDE_BIN
        claude_driver.config.CLAUDE_BIN = str(engine)
        try:
            events = [e async for e in claude_driver.run("проверка", with_tools=False)]
        finally:
            claude_driver.config.CLAUDE_BIN = original

    errors = [e for e in events if e["type"] == "error"]
    if errors:
        print("ПРОВАЛ: поток оборвался ошибкой:", errors[0]["message"])
        return 1

    texts = [e for e in events if e["type"] == "text"]
    if not texts:
        print("ПРОВАЛ: длинная строка с ответом не разобрана")
        return 1
    if len(texts[0]["text"]) != PAYLOAD_LEN:
        print(f"ПРОВАЛ: текст пришёл обрезанным — {len(texts[0]['text'])} из {PAYLOAD_LEN}")
        return 1

    results = [e for e in events if e["type"] == "result"]
    if not results or len(results[0]["text"]) != PAYLOAD_LEN:
        print("ПРОВАЛ: итоговое событие не дошло или текст в нём обрезан")
        return 1
    if results[0]["session_id"] != "test-session":
        print("ПРОВАЛ: потерян идентификатор сессии")
        return 1

    print(f"OK: строка в {PAYLOAD_LEN} символов прошла целиком, ответ разобран")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
