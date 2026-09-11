"""Проверка: расход по стенограммам считается без двойного счёта.

Смысл проверки. Один ответ движка разложен в стенограмме на несколько строк
(рассуждение, текст, вызовы инструментов), и в КАЖДОЙ лежит один и тот же
блок usage — полный расход ответа, а не его доля. Построчное сложение
завышает счёт вдвое и больше, а выглядит совершенно правдоподобно: число
на дашборде просто вырастет, и повода усомниться не будет.

Проверяется на подставном каталоге стенограмм, настоящие не трогаются.

Запуск:  .venv/bin/python tests/check_transcripts_usage.py
"""
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services import transcripts  # noqa: E402

FAILED = []


def check(name: str, got, expected):
    ok = got == expected
    print(f"  {'ok  ' if ok else 'ПЛОХО'} {name}: {got}" + ("" if ok else f" (ждали {expected})"))
    if not ok:
        FAILED.append(name)


def line(when, request_id, msg_id, tin, tout, cread=0, cwrite=0):
    """Строка стенограммы в том же виде, в каком её пишет Claude Code."""
    return json.dumps({
        "type": "assistant",
        "timestamp": when.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "uuid": f"{request_id}-{msg_id}-{tout}-{when.timestamp()}",
        "requestId": request_id,
        "sessionId": "проверочная-сессия",
        "message": {
            "id": msg_id,
            "model": "claude-opus-5",
            "usage": {
                "input_tokens": tin,
                "output_tokens": tout,
                "cache_read_input_tokens": cread,
                "cache_creation_input_tokens": cwrite,
            },
        },
    }, ensure_ascii=False)


def main():
    now = datetime.now(timezone.utc)
    tmp = tempfile.mkdtemp(prefix="stenogrammy-")
    project = Path(tmp) / "-proverka"
    project.mkdir()

    # Первый ответ — три строки с одним и тем же расходом (так пишет движок),
    # второй ответ — две строки. Ещё один ответ лежит вне окна, он не в счёт.
    hour_ago = now - timedelta(hours=1)
    long_ago = now - timedelta(hours=9)
    rows = [
        line(long_ago, "req-старый", "msg-старый", 1000, 1000),
        line(hour_ago, "req-1", "msg-1", 100, 500, cread=7000, cwrite=300),
        line(hour_ago, "req-1", "msg-1", 100, 500, cread=7000, cwrite=300),
        line(hour_ago, "req-1", "msg-1", 100, 500, cread=7000, cwrite=300),
        line(now - timedelta(minutes=10), "req-2", "msg-2", 50, 250),
        line(now - timedelta(minutes=10), "req-2", "msg-2", 50, 250),
    ]
    (project / "сессия.jsonl").write_text("\n".join(rows) + "\n", encoding="utf-8")

    transcripts.PROJECTS_DIR = tmp
    transcripts._cache.clear()

    print("Пятичасовое окно: шесть строк, но ответов два")
    got = transcripts.usage_since(now - timedelta(hours=5))
    check("ответов", got["requests"], 2)
    check("на вход", got["input_tokens"], 150)
    check("на выход", got["output_tokens"], 750)
    check("из кэша", got["cache_read"], 7000)
    check("в кэш", got["cache_write"], 300)
    check("начало окна — первый ответ в нём", got["started"].hour, hour_ago.hour)

    print("\nСтарый ответ за границей окна не считается")
    check("его токенов нет в сумме", got["input_tokens"] + got["output_tokens"], 900)

    print("\nДописанная строка подхватывается, прежние не пересчитываются")
    with open(project / "сессия.jsonl", "a", encoding="utf-8") as fh:
        fh.write(line(now, "req-3", "msg-3", 7, 3) + "\n")
    got = transcripts.usage_since(now - timedelta(hours=5))
    check("ответов стало", got["requests"], 3)
    check("на выход стало", got["output_tokens"], 753)

    # Стенограмму дописывают прямо во время чтения, поэтому последняя строка
    # регулярно попадается обрезанной на середине. Считать её нельзя, но и
    # терять нельзя: дочитается она в следующий раз.
    print("\nСтрока, застигнутая недописанной: сперва не в счёт, потом в счёт")
    whole = line(now, "req-4", "msg-4", 11, 22)
    half = len(whole) // 2
    with open(project / "сессия.jsonl", "a", encoding="utf-8") as fh:
        fh.write(whole[:half])
    got = transcripts.usage_since(now - timedelta(hours=5))
    check("недописанная не посчитана", got["requests"], 3)
    check("её токенов нет", got["output_tokens"], 753)

    with open(project / "сессия.jsonl", "a", encoding="utf-8") as fh:
        fh.write(whole[half:] + "\n")
    got = transcripts.usage_since(now - timedelta(hours=5))
    check("дописанная посчитана", got["requests"], 4)
    check("её токены пришли", got["output_tokens"], 775)

    print("\nНет каталога — источник признаётся недоступным, а не пустым")
    transcripts.PROJECTS_DIR = tmp + "-которого-нет"
    check("признак недоступности", transcripts.usage_since(now - timedelta(hours=5)), None)

    print()
    if FAILED:
        print(f"НЕ ПРОШЛО: {len(FAILED)} — {', '.join(FAILED)}")
        return 1
    print("Все проверки прошли")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
