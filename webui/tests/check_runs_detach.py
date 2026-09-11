"""Проверка: уход со страницы не обрывает работу и не теряет ответ.

Смысл проверки. Раньше ответ движка шёл прямо в теле HTTP-ответа, и закрытое
соединение гасило процесс: перешёл на «Дашборд» — работа пропала, причём
вместе с ответом, потому что в базу он пишется только по завершении. Теперь
запуск живёт в задаче приложения, а страница — всего лишь читатель.

Проверяются оба свойства, которые из этого следуют:
  1. читатель ушёл — работа продолжается и доходит до конца;
  2. читатель вернулся — получает ответ ЦЕЛИКОМ, а не с середины.

Второе не мелочь: если бы события лежали в очереди, вернувшаяся страница
увидела бы обрывок с того места, до которого дошло дело, и человек решил бы,
что начало ответа потеряно.

Запуск:  .venv/bin/python tests/check_runs_detach.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services import runs  # noqa: E402

FAILED = []


def check(name: str, got, expected):
    ok = got == expected
    print(f"  {'ok  ' if ok else 'ПЛОХО'} {name}: {got}" + ("" if ok else f" (ждали {expected})"))
    if not ok:
        FAILED.append(name)


async def scenario():
    emitted = []

    async def producer(run):
        """Подставной движок: шесть событий с паузами."""
        for i in range(5):
            await asyncio.sleep(0.02)
            event = {"type": "delta", "text": f"кусок {i}"}
            emitted.append(event)
            await run.append(event)
        await asyncio.sleep(0.02)
        result = {"type": "result", "text": "готово", "output_tokens": 42}
        emitted.append(result)
        await run.append(result)

    run = runs.start("проверка", 1, producer)

    print("Читатель уходит после двух событий (это и есть переход на другую вкладку)")
    seen_by_first = []
    async for event in run.follow(0):
        seen_by_first.append(event)
        if len(seen_by_first) == 2:
            break            # соединение закрыто, страница покинута
    check("успел увидеть", len(seen_by_first), 2)

    # Ждём, пока работа закончится сама — за ней уже никто не следит
    await asyncio.wait_for(run._task, timeout=5)
    check("работа дошла до конца", run.done, True)
    check("движок выдал всё", len(emitted), 6)

    print("\nЧитатель вернулся: ответ приходит целиком, а не с середины")
    seen_by_second = [e async for e in run.follow(0)]
    check("событий получено", len(seen_by_second), 6)
    check("первое — начало ответа", seen_by_second[0]["text"], "кусок 0")
    check("последнее — итог", seen_by_second[-1]["type"], "result")

    print("\nПродолжение с позиции: пропущенное после ухода")
    tail = [e async for e in run.follow(2)]
    check("событий в хвосте", len(tail), 4)
    check("хвост начинается с третьего", tail[0]["text"], "кусок 2")

    print("\nЗаконченный запуск при открытии страницы не проигрывается заново")
    frames = [f async for f in runs.sse(run, 0, only_active=True)]
    check("кадров", len(frames), 2)
    check("первый кадр — idle", "idle" in frames[0], True)

    print("\nА без этого признака хвост всё ещё доступен — для переподключения")
    frames = [f async for f in runs.sse(run, 0, only_active=False)]
    check("кадров с событиями", len(frames), 7)      # 6 событий и done

    print("\nЗапуска не было вовсе: страница получает idle, а не вечное ожидание")
    frames = [f async for f in runs.sse(runs.get("проверка", 999), 0)]
    check("первый кадр — idle", "idle" in frames[0], True)


def main():
    asyncio.run(scenario())
    print()
    if FAILED:
        print(f"НЕ ПРОШЛО: {len(FAILED)} — {', '.join(FAILED)}")
        return 1
    print("Все проверки прошли")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
