"""Перезапуск сайта и перезагрузка сервера — после того, как допишутся ответы.

Пока ждём, новые ответы не начинаются (дописки в идущие — можно). Сама
команда — обёртка с закрытым списком (`deploy/webui2-power`) через sudo -n:
прав root у сайта нет. Страница узнаёт, что сайт поднялся, по смене BOOT."""
import asyncio
import secrets
import time

from . import config, db

BOOT = secrets.token_hex(8)            # меняется при каждом запуске сайта
ACTIONS = {"site": "restart-site", "server": "reboot"}
STUCK_SEC = 180                        # команда прошла, а сайт всё жив — что-то не так

STATE: dict = {"what": None, "phase": "", "error": "", "since": 0.0}
_task: dict = {"t": None}


def busy() -> dict:
    """Что ещё идёт: ответы Claude и проверки/удаления проектов."""
    from .chat import RUNS                             # chat.py сам опирается на этот модуль
    deleting = db.one("SELECT COUNT(*) AS n FROM projects WHERE delete_state IN ('checking', 'removing')")["n"]
    return {"runs": len(RUNS), "deleting": deleting}


def pending() -> bool:
    return STATE["what"] is not None


def snapshot() -> dict:
    return {"boot": BOOT, "what": STATE["what"], "phase": STATE["phase"],
            "error": STATE["error"], **busy()}


def start(what: str) -> bool:
    if what not in ACTIONS or pending():
        return False
    STATE.update(what=what, phase="waiting", error="", since=time.monotonic())
    _task["t"] = asyncio.create_task(_worker(what))
    return True


def cancel(error: str = "") -> None:
    task = _task["t"]
    if task and not task.done() and task is not asyncio.current_task():
        task.cancel()
    STATE.update(what=None, phase="", error=error)


async def _worker(what: str) -> None:
    limit = config.POWER_WAIT_MIN * 60
    while True:
        left = busy()
        if not left["runs"] and not left["deleting"]:
            break
        if time.monotonic() - STATE["since"] > limit:
            cancel(f"Ответы не дописались за {config.POWER_WAIT_MIN} минут — отменено")
            return
        await asyncio.sleep(1)
    STATE["phase"] = "going"
    try:
        proc = await asyncio.create_subprocess_exec(
            *config.POWER_CMD, ACTIONS[what], stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT)
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
    except (OSError, asyncio.TimeoutError) as exc:
        cancel(f"Не получилось: {exc}")
        return
    if proc.returncode != 0:
        tail = out.decode("utf-8", "replace").strip().splitlines()[-1:] or ["без пояснений"]
        cancel(f"Не получилось: {tail[0][:200]}")
        return
    # Удалось — сайт вот-вот остановится; страница ждёт нового BOOT
    await asyncio.sleep(STUCK_SEC)
    cancel("Команда прошла, но сайт так и не перезапустился")
