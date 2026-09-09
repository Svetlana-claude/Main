"""Дашборд: ресурсы сервера и расход по токенам."""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

from .. import db
from ..deps import current_user, render
from ..services import metrics

router = APIRouter()


def _usage_summary() -> dict:
    """Расход за сегодня и за месяц. Считается по тому, что вернул CLI."""
    today = db.query_one(
        """
        SELECT coalesce(sum(cost_usd), 0) AS cost,
               coalesce(sum(input_tokens), 0) AS input_tokens,
               coalesce(sum(output_tokens), 0) AS output_tokens,
               coalesce(sum(cache_read), 0) AS cache_read,
               coalesce(sum(cache_write), 0) AS cache_write,
               count(*) AS requests
        FROM messages
        WHERE role = 'assistant' AND created_at >= date_trunc('day', now())
        """
    )
    month = db.query_one(
        """
        SELECT coalesce(sum(cost_usd), 0) AS cost,
               coalesce(sum(input_tokens + output_tokens), 0) AS tokens,
               count(*) AS requests
        FROM messages
        WHERE role = 'assistant' AND created_at >= date_trunc('month', now())
        """
    )
    by_kind = db.query(
        """
        SELECT c.kind,
               coalesce(sum(m.cost_usd), 0) AS cost,
               count(m.id) AS requests
        FROM messages m JOIN conversations c ON c.id = m.conversation_id
        WHERE m.role = 'assistant' AND m.created_at >= date_trunc('month', now())
        GROUP BY c.kind
        """
    )

    settings = db.get_settings()
    try:
        limit = float(settings.get("monthly_limit_usd") or 0)
    except ValueError:
        limit = 0.0
    month_cost = float(month["cost"]) if month else 0.0
    share = (month_cost / limit * 100) if limit > 0 else 0.0

    return {
        "today": {
            "cost": round(float(today["cost"]), 4) if today else 0,
            "input_tokens": int(today["input_tokens"]) if today else 0,
            "output_tokens": int(today["output_tokens"]) if today else 0,
            "cache_read": int(today["cache_read"]) if today else 0,
            "cache_write": int(today["cache_write"]) if today else 0,
            "requests": int(today["requests"]) if today else 0,
        },
        "month": {
            "cost": round(month_cost, 4),
            "tokens": int(month["tokens"]) if month else 0,
            "requests": int(month["requests"]) if month else 0,
            "limit": limit,
            "share": round(share, 1),
            "over": limit > 0 and month_cost >= limit,
            "near": limit > 0 and 80 <= share < 100,
        },
        "by_kind": {r["kind"]: {"cost": round(float(r["cost"]), 4),
                                "requests": int(r["requests"])} for r in by_kind},
    }


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
            "usage": _usage_summary(),
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
    return JSONResponse({"metrics": snapshot, "usage": _usage_summary()})


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
