"""Метрики сервера для дашборда.

Числа берутся из psutil и /proc. Значения намеренно совпадают с тем, что
показывают free, df и uptime, — иначе дашборд врёт, а проверить его нечем.
"""
import os
import shutil
import time
from datetime import datetime, timezone

import psutil

_last_net: tuple[float, int, int] | None = None


def _human_bytes(n: float) -> str:
    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}".replace(".0 ", " ")
        n /= 1024
    return f"{n:.1f} ПБ"


def _human_duration(seconds: float) -> str:
    seconds = int(seconds)
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    parts = []
    if days:
        parts.append(f"{days} дн")
    if hours or days:
        parts.append(f"{hours} ч")
    parts.append(f"{minutes} мин")
    return " ".join(parts)


def collect() -> dict:
    """Снимок состояния сервера."""
    global _last_net

    # interval=None даёт загрузку с прошлого вызова — на автообновлении раз в 10 с
    # это ровно то, что нужно, и не блокирует ответ на секунду
    cpu_pct = psutil.cpu_percent(interval=None)
    per_cpu = psutil.cpu_percent(interval=None, percpu=True)

    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()
    disk = shutil.disk_usage("/")
    load1, load5, load15 = os.getloadavg()
    boot = psutil.boot_time()

    # Скорость сети считаем сами: psutil даёт счётчики, а не скорость
    now = time.monotonic()
    net = psutil.net_io_counters()
    rx_rate = tx_rate = 0.0
    if _last_net is not None:
        prev_t, prev_rx, prev_tx = _last_net
        gap = now - prev_t
        if gap > 0:
            rx_rate = max(0.0, (net.bytes_recv - prev_rx) / gap)
            tx_rate = max(0.0, (net.bytes_sent - prev_tx) / gap)
    _last_net = (now, net.bytes_recv, net.bytes_sent)

    return {
        "at": datetime.now(timezone.utc).isoformat(),
        "cpu": {
            "percent": round(cpu_pct, 1),
            "cores": psutil.cpu_count(logical=True),
            "per_core": [round(v, 1) for v in per_cpu],
        },
        "memory": {
            "percent": round(mem.percent, 1),
            "used": mem.total - mem.available,
            "total": mem.total,
            "available": mem.available,
            "used_h": _human_bytes(mem.total - mem.available),
            "total_h": _human_bytes(mem.total),
            "available_h": _human_bytes(mem.available),
        },
        "swap": {
            "percent": round(swap.percent, 1),
            "used_h": _human_bytes(swap.used),
            "total_h": _human_bytes(swap.total),
            "present": swap.total > 0,
        },
        "disk": {
            "percent": round(disk.used / disk.total * 100, 1),
            "used": disk.used,
            "total": disk.total,
            "used_h": _human_bytes(disk.used),
            "total_h": _human_bytes(disk.total),
            "free_h": _human_bytes(disk.free),
        },
        "load": {
            "one": round(load1, 2),
            "five": round(load5, 2),
            "fifteen": round(load15, 2),
            # Нагрузка выше числа ядер означает очередь на процессор
            "per_core": round(load1 / max(1, psutil.cpu_count(logical=True)), 2),
        },
        "net": {
            "rx_rate_h": _human_bytes(rx_rate) + "/с",
            "tx_rate_h": _human_bytes(tx_rate) + "/с",
            "rx_total_h": _human_bytes(net.bytes_recv),
            "tx_total_h": _human_bytes(net.bytes_sent),
        },
        "uptime": {
            "seconds": int(time.time() - boot),
            "human": _human_duration(time.time() - boot),
            "boot": datetime.fromtimestamp(boot, timezone.utc).isoformat(),
        },
        "processes": len(psutil.pids()),
    }
