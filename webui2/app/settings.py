"""Шестерёнка «Настройки»: пароль, часовой пояс, перезапуск, нагрузка."""
import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse

from . import config, db, load, power, security
from .web import client_ip, csrf_ok, current, guarded, page, to, zone, zone_name, set_zone

router = APIRouter()

# График: поле в условных точках; линия рвётся, где замеров не было (сайт стоял)
W, H, PAD_L, PAD_B, PAD_T = 600, 150, 50, 22, 14
GAP = timedelta(minutes=3)
SERIES = (("cpu", "Процессор"), ("mem", "Память"), ("disk", "Диск"))


def chart(samples: list[dict], key: str) -> dict:
    """Одна линия за сутки, ось 0–100 %: отрезки линии, подписи часов, точки
    для подсказки при наведении."""
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=config.LOAD_KEEP_HOURS)
    span = (end - start).total_seconds()
    plot_w, plot_h = W - PAD_L, H - PAD_B - PAD_T

    def x_of(moment: datetime) -> float:
        return round(PAD_L + plot_w * (moment - start).total_seconds() / span, 1)

    lines: list[list[str]] = []
    points: list[list] = []
    last = None
    for row in samples:
        moment = datetime.fromisoformat(row["at"])
        x, value = x_of(moment), row[key]
        y = round(PAD_T + plot_h - plot_h * min(max(value, 0), 100) / 100, 1)
        if last is None or moment - last > GAP:
            lines.append([])
        lines[-1].append(f"{x},{y}")
        local = moment.astimezone(zone())
        points.append([x, y, f"{value:.0f} %".replace(".", ","), f"{local:%H:%M}"])
        last = moment
    # Подписи часов: каждые 6 часов по её поясу
    ticks = []
    mark = start.astimezone(zone()).replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    while mark <= end:
        if mark.hour % 6 == 0:
            ticks.append({"x": x_of(mark), "label": f"{mark:%H:%M}"})
        mark += timedelta(hours=1)
    return {"key": key, "lines": [" ".join(p) for p in lines if len(p) > 1],
            "dots": [p for p in lines if len(p) == 1],
            "ticks": ticks, "points": json.dumps(points), "w": W, "h": H,
            "pad_l": PAD_L, "pad_t": PAD_T, "plot_h": plot_h, "plot_w": plot_w}


def hourly(samples: list[dict]) -> list[dict]:
    """Таблица для тех, кому график не подходит: среднее по часам."""
    groups: dict[str, list[dict]] = {}
    for row in samples:
        hour = datetime.fromisoformat(row["at"]).astimezone(zone()).strftime("%d.%m %H:00")
        groups.setdefault(hour, []).append(row)
    return [{"hour": hour, **{k: round(sum(r[k] for r in rows) / len(rows)) for k, _ in SERIES}}
            for hour, rows in groups.items()]


def settings_ctx(**extra) -> dict:
    samples = load.day()
    latest = samples[-1] if samples else None
    return {"title": "Настройки", "zones": config.ZONES, "zone": zone_name(),
            "power": power.snapshot(),
            "charts": [(name, chart(samples, key)) for key, name in SERIES] if samples else [],
            "hours": hourly(samples), "latest": latest, **extra}


@router.get("/settings", name="settings")
def settings_page(request: Request):
    return guarded(request, "settings.html", "settings", settings_ctx())


def _ok(request: Request, csrf: str) -> dict | None:
    sess = current(request)
    if sess and not sess["locked"] and csrf_ok(request, sess, csrf):
        return sess
    return None


@router.post("/settings/password", name="change_password")
def change_password(request: Request, old: str = Form(""), new: str = Form(""),
                    new2: str = Form(""), csrf: str = Form("")):
    sess = current(request)
    if not sess:
        return to(request, "login_form")
    if sess["locked"] or not csrf_ok(request, sess, csrf):
        return guarded(request, "settings.html", "settings", settings_ctx())
    ip = client_ip(request)

    def answer(msg: str, ok: bool = False):
        return page(request, "settings.html", {"sess": sess, "active": "settings",
                                               **settings_ctx(pw_msg=msg, pw_ok=ok)}, 200 if ok else 400)

    if security.blocked(ip):
        return answer(f"Слишком много попыток. Попробуй через {config.FAIL_WINDOW_MIN} минут")
    user = db.one("SELECT password_hash FROM users WHERE id = ?", (sess["user_id"],))
    if not security.check_secret(user["password_hash"], old):
        security.note_fail(ip)
        return answer("Старый пароль не подошёл")
    if new != new2:
        return answer("Новые пароли не совпадают")
    if problem := security.password_problem(new):
        return answer(problem)
    db.run("UPDATE users SET password_hash = ? WHERE id = ?", (security.hash_secret(new), sess["user_id"]))
    # Прочие входы закрываются: пароль меняют, когда опасаются чужого
    db.run("DELETE FROM sessions WHERE user_id = ? AND id <> ?", (sess["user_id"], sess["id"]))
    return answer("Пароль изменён", ok=True)


@router.post("/settings/timezone", name="set_timezone")
def set_timezone(request: Request, zone_id: str = Form(""), csrf: str = Form("")):
    if _ok(request, csrf):
        set_zone(zone_id)
    return RedirectResponse(f"{config.ROOT_PATH}/settings#zone", status_code=303)


# ── Перезапуск ───────────────────────────────────────────────────────────

@router.get("/settings/power", name="power_state")
def power_state(request: Request):
    sess = current(request)
    if not sess or sess["locked"]:
        return JSONResponse({"error": "нет доступа"}, status_code=403)
    return JSONResponse(power.snapshot(), headers={"Cache-Control": "no-store"})


# async: задача ожидания живёт в цикле событий сайта
@router.post("/settings/power/{what}", name="power_start")
async def power_start(request: Request, what: str, csrf: str = Form("")):
    if not _ok(request, csrf):
        return JSONResponse({"error": "Нет доступа — обнови страницу"}, status_code=403)
    if what == "cancel":
        if power.STATE["phase"] == "waiting":
            power.cancel()
    elif not power.start(what):
        return JSONResponse({"error": "Уже ждём перезапуска", **power.snapshot()}, status_code=409)
    return JSONResponse(power.snapshot())


# ── Нагрузка ─────────────────────────────────────────────────────────────

@router.get("/settings/load", name="load_now")
async def load_now(request: Request):
    sess = current(request)
    if not sess or sess["locked"]:
        return JSONResponse({"error": "нет доступа"}, status_code=403)
    return JSONResponse(await load.now(), headers={"Cache-Control": "no-store"})
