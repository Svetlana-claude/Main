"""Дашборд: ресурсы сервера и расход токенов по окнам тарифного плана."""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

from .. import db
from ..deps import current_user, render
from ..services import metrics, usage

router = APIRouter()


@router.get("/", name="dashboard")
def dashboard(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse(request.url_for("login_form"), status_code=303)
    if user["must_change"]:
        return RedirectResponse(request.url_for("change_password_form"), status_code=303)

    return render(
        request,
        "dashboard.html",
        {
            "user": user,
            "active": "dashboard",
            "metrics": metrics.collect(),
            "usage": usage.summary(),
        },
    )


@router.get("/api/metrics", name="api_metrics")
def api_metrics(request: Request):
    """Данные для автообновления. Пишет точку в историю для графика."""
    if not current_user(request):
        return JSONResponse({"error": "нет сессии"}, status_code=401)

    snapshot = metrics.collect()
    db.execute(
        "INSERT INTO metrics_history (cpu_pct, mem_pct, disk_pct, load1) "
        "VALUES (%s, %s, %s, %s) ON CONFLICT (at) DO NOTHING",
        (
            snapshot["cpu"]["percent"],
            snapshot["memory"]["percent"],
            snapshot["disk"]["percent"],
            snapshot["load"]["one"],
        ),
    )
    return JSONResponse({"metrics": snapshot, "usage": usage.summary()})


@router.get("/api/metrics/history", name="api_metrics_history")
def api_metrics_history(request: Request, hours: int = 24):
    if not current_user(request):
        return JSONResponse({"error": "нет сессии"}, status_code=401)

    hours = max(1, min(hours, 168))
    rows = db.query(
        """
        SELECT at, cpu_pct, mem_pct, disk_pct, load1
        FROM metrics_history
        WHERE at > now() - make_interval(hours => %s)
        ORDER BY at
        """,
        (hours,),
    )
    return JSONResponse(
        {
            "points": [
                {
                    "at": r["at"].isoformat(),
                    "cpu": round(r["cpu_pct"], 1),
                    "mem": round(r["mem_pct"], 1),
                    "load": round(r["load1"], 2),
                }
                for r in rows
            ]
        }
    )
