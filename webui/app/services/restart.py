"""Перезапуск приложения из интерфейса.

Правка кода `webui` применяется только перезапуском службы, а сделать это прямо
из темы проекта нельзя: `claude` запущен приложением и потому входит в
контрольную группу `webui.service`. Остановка службы гасит группу целиком —
вместе с процессом, который в этот момент готовит ответ. Ответ пишется в базу
по завершении, значит оборванный пропадает вместе с проделанной работой.

Отсюда устройство кнопки: она не перезапускает службу сразу, а **ставит
перезапуск в очередь** и ждёт, пока не завершатся все выполняющиеся ответы
(и ручной прогон аудита с вкладки «Безопасность» — он в той же группе).
Счётчик ответов ведёт драйвер. Когда счётчик обнулился, служба уходит на
перезапуск; браузер тем временем опрашивает состояние и сам обновляет страницу.

Команда перезапуска разрешена в `infra/sudo-allowed.list` дословно
(`/usr/bin/systemctl restart webui`), поэтому вызывается ровно в таком виде.
"""
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone

from . import claude_driver, security

RESTART_ARGV = ["/usr/bin/sudo", "-n", "/usr/bin/systemctl", "restart", "webui"]

# Ответ на нажатие должен успеть уйти в браузер до того, как служба остановится
GRACE_SEC = 2.0

# Опрос счётчика выполняющихся ответов
POLL_SEC = 1.0

# Предел ожидания. Совпадает с предельной длительностью одного ответа: дольше
# него ждать нечего — такой ответ драйвер и сам обрывает по времени.
MAX_WAIT_SEC = claude_driver.RUN_TIMEOUT_SEC


@dataclass
class State:
    """Состояние перезапуска. Живёт до остановки службы, дальше не нужно."""
    pending: bool = False
    requested_by: str = ""
    requested_at: datetime | None = None
    waiting_for: int = 0          # сколько ответов ещё выполняется
    error: str = ""

    def as_dict(self) -> dict:
        return {
            "pending": self.pending,
            "requested_by": self.requested_by,
            "requested_at": self.requested_at.isoformat() if self.requested_at else None,
            "waiting_for": self.waiting_for,
            "error": self.error,
        }


def _busy() -> int:
    """Сколько работы оборвёт остановка: ответы плюс идущий прогон аудита.
    Аудит запущен приложением и живёт в той же контрольной группе."""
    return claude_driver.active_runs() + (1 if security.run_active() else 0)


state = State()
_task: asyncio.Task | None = None     # ссылка нужна, чтобы задачу не собрал сборщик


def request(login: str) -> State:
    """Ставит перезапуск в очередь. Повторное нажатие ничего не меняет."""
    global _task
    if state.pending:
        return state
    state.pending = True
    state.requested_by = login
    state.requested_at = datetime.now(timezone.utc)
    state.waiting_for = _busy()
    state.error = ""
    _task = asyncio.create_task(_worker())
    return state


def current() -> State:
    """Состояние для опроса из браузера, со свежим числом ответов."""
    if state.pending:
        state.waiting_for = _busy()
    return state


async def _worker() -> None:
    """Ждёт завершения ответов и перезапускает службу."""
    await asyncio.sleep(GRACE_SEC)

    waited = 0.0
    while _busy() > 0 and waited < MAX_WAIT_SEC:
        state.waiting_for = _busy()
        await asyncio.sleep(POLL_SEC)
        waited += POLL_SEC
    state.waiting_for = 0

    try:
        proc = await asyncio.create_subprocess_exec(
            *RESTART_ARGV,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, err = await proc.communicate()
    except OSError as exc:
        state.pending = False
        state.error = f"не удалось запустить перезапуск: {exc}"
        return

    # Сюда обычно не доходит: служба уже остановлена вместе с этим процессом.
    # Если дошли — перезапуск не состоялся, и об этом надо сказать на странице.
    if proc.returncode != 0:
        state.pending = False
        state.error = (err.decode("utf-8", "replace").strip()
                       or f"код возврата {proc.returncode}")
