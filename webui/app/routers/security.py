"""Вкладка «Безопасность»: сводка, отчёты, ручной прогон.

Вся работа с аудитом идёт через службу `services.security`, то есть через
обёртку `webui-sec`. Прямых обращений к `/opt/secaudit` и к `iptables` здесь
нет и не должно быть.

Внимание к тому, что отдаётся наружу: отчёт содержит имена учёток, адреса
входов и отпечатки ключей. Поэтому маршруты закрыты тем же входом, что и
остальные страницы, дата сверяется с образцом до всякого обращения к файлу,
а кэширование выключено.
"""
import markdown
from fastapi import APIRouter, Form, Request
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse

from ..deps import current_user, render
from ..services import security

router = APIRouter()


def _guard(request: Request):
    user = current_user(request)
    if not user:
        return None, RedirectResponse(request.url_for("login_form"), status_code=303)
    if user["must_change"]:
        return None, RedirectResponse(request.url_for("change_password_form"), status_code=303)
    return user, None


def _back(request: Request, **params) -> RedirectResponse:
    url = request.url_for("sec_page")
    if params:
        url = url.include_query_params(**params)
    return RedirectResponse(url, status_code=303)


@router.get("/sec", name="sec_page")
def sec_page(request: Request):
    user, redirect = _guard(request)
    if redirect:
        return redirect

    return render(
        request,
        "security.html",
        {
            "user": user,
            "active": "sec",
            "state": security.state(),
            "running": security.run_info(),
            "last_run": security.last_run(),
            "err": request.query_params.get("err", ""),
            "ok": request.query_params.get("ok", ""),
        },
    )


@router.get("/sec/state", name="sec_state")
def sec_state(request: Request):
    """Состояние для опроса из браузера: идёт ли прогон, что в последнем отчёте."""
    if not current_user(request):
        # Опрос не должен уводить страницу на вход: пусть просто скажет «нет».
        return JSONResponse({"ok": False}, status_code=401)

    st = security.state()
    info = security.run_info()
    return JSONResponse(
        {
            "ok": True,
            "verdict": st.verdict,
            "alarm": st.alarm,
            "silent": st.silent,
            "findings": st.findings,
            "last_report": st.last_report,
            "quarantine": st.quarantine,
            "running": bool(info["active"]),
            "mode": info["mode"],
            "tail": info["tail"],
        }
    )


@router.post("/sec/run", name="sec_run")
def sec_run(request: Request, mode: str = Form("full")):
    user, redirect = _guard(request)
    if redirect:
        return redirect
    try:
        security.start_run(remediate=(mode == "full"))
    except security.SecError as exc:
        return _back(request, err=str(exc))
    return _back(request, ok="Прогон запущен. Он идёт на сервере: со страницы можно уйти, "
                             "итог будет виден здесь, когда вернётесь.")


@router.post("/sec/baseline", name="sec_baseline")
def sec_baseline(request: Request):
    user, redirect = _guard(request)
    if redirect:
        return redirect
    try:
        message = security.approve_baseline()
    except security.SecError as exc:
        return _back(request, err=str(exc))
    return _back(request, ok=message or "Эталон принят.")


@router.get("/sec/reports/{date}", name="sec_report")
def sec_report(request: Request, date: str):
    user, redirect = _guard(request)
    if redirect:
        return redirect
    try:
        text = security.report_text(date)
    except security.SecError as exc:
        return PlainTextResponse(str(exc), status_code=404)

    # `fenced_code` — ради блоков ``` в отчёте, `tables` — ради таблиц из
    # проверки после перезагрузки. Ничего, что исполняется, markdown не даёт.
    body = markdown.markdown(text, extensions=["fenced_code", "tables"])
    page = render(
        request,
        "security_report.html",
        {"user": user, "active": "sec", "date": date, "body": body},
    )
    # Отчёт с отпечатками ключей и адресами кэшировать незачем.
    page.headers["Cache-Control"] = "no-store"
    return page


@router.get("/sec/reports/{date}/raw", name="sec_report_raw")
def sec_report_raw(request: Request, date: str):
    user, redirect = _guard(request)
    if redirect:
        return redirect
    try:
        text = security.report_text(date)
    except security.SecError as exc:
        return PlainTextResponse(str(exc), status_code=404)
    return PlainTextResponse(
        text,
        headers={
            "Content-Disposition": f'attachment; filename="rep_{date}.md"',
            "Cache-Control": "no-store",
        },
    )
