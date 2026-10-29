"""Нагрузка сервера: процессор, память, диск.

«Сейчас» — замер по кнопке. Для графика за сутки фоновая задача сайта раз
в минуту пишет замер в базу и стирает то, что старше суток."""
import asyncio
import os
from datetime import datetime, timedelta, timezone

from . import config, db

DISK_PATH = "/"


def _cpu_times() -> tuple[int, int]:
    """(всего, простой) из /proc/stat — счётчики с запуска сервера."""
    with open("/proc/stat", encoding="ascii") as fh:
        parts = [int(x) for x in fh.readline().split()[1:]]
    idle = parts[3] + (parts[4] if len(parts) > 4 else 0)   # idle + iowait
    return sum(parts), idle


def _cpu_percent(before: tuple[int, int], after: tuple[int, int]) -> float:
    total, idle = after[0] - before[0], after[1] - before[1]
    return round(100 * (total - idle) / total, 1) if total > 0 else 0.0


def memory() -> tuple[float, int, int]:
    """(занято %, занято байт, всего байт): занятое — всё, кроме доступного."""
    info: dict[str, int] = {}
    with open("/proc/meminfo", encoding="ascii") as fh:
        for line in fh:
            key, value = line.split(":", 1)
            info[key] = int(value.split()[0]) * 1024
    total = info.get("MemTotal", 0)
    used = total - info.get("MemAvailable", info.get("MemFree", 0))
    return (round(100 * used / total, 1) if total else 0.0), used, total


def disk() -> tuple[float, int, int]:
    st = os.statvfs(DISK_PATH)
    total = st.f_blocks * st.f_frsize
    used = total - st.f_bfree * st.f_frsize
    return (round(100 * used / total, 1) if total else 0.0), used, total


def gigabytes(size: int) -> str:
    return f"{size / 1024 ** 3:.1f}".replace(".", ",") + " ГБ"


async def now() -> dict:
    """Замер сейчас: процессор — за полсекунды."""
    before = _cpu_times()
    await asyncio.sleep(0.5)
    cpu = _cpu_percent(before, _cpu_times())
    mem, mem_used, mem_total = memory()
    dsk, disk_used, disk_total = disk()
    return {"cpu": cpu, "mem": mem, "disk": dsk, "cores": os.cpu_count() or 1,
            "mem_text": f"{gigabytes(mem_used)} из {gigabytes(mem_total)}",
            "disk_text": f"{gigabytes(disk_used)} из {gigabytes(disk_total)}"}


def _store(cpu: float) -> None:
    stamp = datetime.now(timezone.utc)
    db.run("INSERT INTO load_samples (at, cpu, mem, disk) VALUES (?, ?, ?, ?)",
           (stamp.isoformat(), cpu, memory()[0], disk()[0]))
    old = stamp - timedelta(hours=config.LOAD_KEEP_HOURS)
    db.run("DELETE FROM load_samples WHERE at < ?", (old.isoformat(),))


async def recorder() -> None:
    """Фоновая запись: процессор — средний за прошедшую минуту."""
    before = _cpu_times()
    while True:
        await asyncio.sleep(config.LOAD_EVERY_SEC)
        after = _cpu_times()
        try:
            _store(_cpu_percent(before, after))
        except Exception:                              # noqa: BLE001 — замер пропускается, запись идёт дальше
            pass
        before = after


def day() -> list[dict]:
    since = datetime.now(timezone.utc) - timedelta(hours=config.LOAD_KEEP_HOURS)
    return db.rows("SELECT at, cpu, mem, disk FROM load_samples WHERE at >= ? ORDER BY at",
                   (since.isoformat(),))
