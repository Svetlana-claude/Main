"""Работа движка, не привязанная к соединению браузера.

ЗАЧЕМ. Раньше ответ движка шёл прямо в теле HTTP-ответа: `StreamingResponse`
с генератором, который сам же и запускал `claude`. Переход на другую вкладку —
обычная навигация браузера, соединение закрывается, Starlette отменяет
генератор, драйвер гасит процесс. Работа обрывалась, и ответ пропадал совсем:
в базу он пишется по событию `result`, а до него дело не доходило.

КАК УСТРОЕНО ТЕПЕРЬ. Запуск живёт в задаче приложения и о браузере ничего
не знает. События копятся в списке, а HTTP-поток — только читатель: его можно
оборвать и открыть заново, попросив продолжить с нужного места. Уйти со
страницы и вернуться теперь можно на любом месте ответа.

ПОЧЕМУ СПИСОК, А НЕ ОЧЕРЕДЬ. Очередь читается один раз, и вернувшийся браузер
получил бы обрывок с середины. Список хранит весь ответ целиком, поэтому
страница при возврате восстанавливает его с начала.

ПЕРЕЗАПУСК СЛУЖБЫ фоновый запуск не переживает — задача живёт в памяти
процесса. Это не потеря: перезапуск и так ждёт завершения всех ответов
(см. `restart.py`), а счётчик выполняющихся ведёт драйвер, и фоновая работа
считается им наравне с прежней.
"""
import asyncio
import json
import logging
import time
from typing import AsyncIterator, Awaitable, Callable

log = logging.getLogger("webui.runs")

# Сколько держать законченный запуск, чтобы вернувшаяся страница успела
# показать концовку. Меньше — и, уйдя на пять минут, человек вернётся
# к пустому месту вместо ответа, который на самом деле удался.
KEEP_FINISHED_SEC = 30 * 60

# Предохранитель от разрастания памяти на очень длинном ответе. Считается
# в событиях, а не в знаках: кусочки текста мелкие, счёт по ним нагляднее.
MAX_EVENTS = 20_000


class Run:
    """Один выполняющийся (или недавно законченный) ответ движка."""

    def __init__(self, key: str):
        self.key = key
        self.events: list[dict] = []
        self.done = False
        self.started_at = time.monotonic()
        self.finished_at: float | None = None
        self._cond = asyncio.Condition()
        self._task: asyncio.Task | None = None

    async def append(self, event: dict) -> None:
        async with self._cond:
            if len(self.events) < MAX_EVENTS:
                self.events.append(event)
            elif not self.events[-1].get("truncated"):
                # Молча обрывать нельзя: страница решит, что ответ таков
                self.events.append({
                    "type": "error",
                    "truncated": True,
                    "message": "Ответ слишком длинный, показ оборван; "
                               "в базу он сохранится целиком.",
                })
            self._cond.notify_all()

    async def finish(self) -> None:
        async with self._cond:
            self.done = True
            self.finished_at = time.monotonic()
            self._cond.notify_all()

    async def follow(self, start: int = 0) -> AsyncIterator[dict]:
        """События с позиции `start` и далее — до конца работы.

        Отдаёт накопленное сразу, поэтому вернувшаяся страница получает ответ
        с начала, а не с того места, до которого он дошёл.
        """
        idx = max(0, start)
        while True:
            async with self._cond:
                if idx >= len(self.events) and not self.done:
                    await self._cond.wait()
                pending = self.events[idx:]
                idx += len(pending)
                finished = self.done and idx >= len(self.events)
            for event in pending:
                yield event
            if finished:
                return


# Ключ «раздел:номер разговора» -> запуск. Больше одного ответа на разговор
# одновременно не бывает: движку и так отвечать по одному, а два процесса
# в одной теме перемешали бы сессию.
_runs: dict[str, Run] = {}


def _prune() -> None:
    now = time.monotonic()
    for key, run in list(_runs.items()):
        if run.done and run.finished_at and now - run.finished_at > KEEP_FINISHED_SEC:
            del _runs[key]


def key_of(kind: str, conversation_id: int) -> str:
    return f"{kind}:{conversation_id}"


def get(kind: str, conversation_id: int) -> Run | None:
    _prune()
    return _runs.get(key_of(kind, conversation_id))


def active(kind: str, conversation_id: int) -> bool:
    run = get(kind, conversation_id)
    return bool(run and not run.done)


def start(
    kind: str,
    conversation_id: int,
    producer: Callable[[Run], Awaitable[None]],
) -> Run:
    """Заводит фоновый запуск. Если он уже идёт — отдаёт его же."""
    _prune()
    key = key_of(kind, conversation_id)
    existing = _runs.get(key)
    if existing and not existing.done:
        return existing

    run = Run(key)
    _runs[key] = run

    async def wrapper() -> None:
        try:
            await producer(run)
        except asyncio.CancelledError:
            await run.append({"type": "error", "message": "Работа прервана"})
            raise
        except Exception as exc:                       # noqa: BLE001
            log.exception("фоновый запуск %s сорвался", key)
            await run.append({"type": "error", "message": f"Сбой обработки: {exc}"})
        finally:
            await run.finish()

    run._task = asyncio.create_task(wrapper(), name=f"run {key}")
    return run


def _frame(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def sse(run: Run | None, start: int = 0, only_active: bool = False) -> AsyncIterator[str]:
    """События запуска кадрами SSE — то, что читает страница.

    Разговора без запуска не бывает только на первый взгляд: страницу могли
    открыть, когда отвечать уже нечего. Тогда сразу говорим `idle`, иначе
    браузер будет держать соединение и ждать событий, которых не будет.

    `only_active` нужен при открытии страницы. Законченный запуск держится
    ещё полчаса, и без этого признака страница проиграла бы прошлый ответ
    заново — поверх того же ответа, уже показанного из базы.
    """
    if run is None or (only_active and run.done):
        yield _frame({"type": "idle"})
        yield _frame({"type": "done"})
        return
    async for event in run.follow(start):
        yield _frame(event)
    yield _frame({"type": "done"})
