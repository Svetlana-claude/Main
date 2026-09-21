"""«Настройки» → «Вход Claude»: состояние входа движка и повторный вход.

Сам вход — в `services/claude_auth.py`. Здесь только страница и кнопки,
по образцу второго фактора: POST → переадресация на страницу, которая
показывает, чем кончилось. Страница не кэшируется — на ней одноразовая
ссылка входа.
"""
from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from ..deps import current_user, render
from ..services import claude_auth

router = APIRouter()


def _guard(request: Request):
    user = current_user(request)
    if not user:
        return None, RedirectResponse(request.url_for("login_form"), status_code=303)
    if user["must_change"]:
        return None, RedirectResponse(request.url_for("change_password_form"), status_code=303)
    return user, None


def _back(request: Request, **params) -> RedirectResponse:
    url = request.url_for("claude_login_page")
    if params:
        url = url.include_query_params(**params)
    return RedirectResponse(url, status_code=303)


@router.get("/settings/claude", name="claude_login_page")
async def claude_login_page(request: Request):
    user, redirect = _guard(request)
    if redirect:
        return redirect
    flow = claude_auth.current()
    if flow and flow["state"] in ("done", "failed"):
        # Итог показывается один раз: при следующем открытии страницы
        # старое «вход выполнен» только путало бы.
        await claude_auth.cancel()
    page = render(request, "settings_claude.html", {
        "user": user,
        "active": "settings",
        "status": await claude_auth.status(),
        "flow": flow,
        "err": request.query_params.get("err", ""),
        "ok": request.query_params.get("ok", ""),
    })
    page.headers["Cache-Control"] = "no-store"
    return page


@router.post("/settings/claude/start", name="claude_login_start")
async def claude_login_start(request: Request):
    user, redirect = _guard(request)
    if redirect:
        return redirect
    await claude_auth.start()
    return _back(request)


@router.post("/settings/claude/code", name="claude_login_code")
async def claude_login_code(request: Request, code: str = Form("")):
    user, redirect = _guard(request)
    if redirect:
        return redirect
    flow = await claude_auth.submit(code)
    # Итог показывает сама страница по состоянию входа; если вход уже снят,
    # состояния нет — тогда сообщение передаётся адресом.
    if claude_auth.current() is None:
        return _back(request, err=flow["message"])
    return _back(request)


@router.post("/settings/claude/cancel", name="claude_login_cancel")
async def claude_login_cancel(request: Request):
    user, redirect = _guard(request)
    if redirect:
        return redirect
    await claude_auth.cancel()
    return _back(request)


@router.post("/settings/claude/check", name="claude_login_check")
async def claude_login_check(request: Request):
    user, redirect = _guard(request)
    if redirect:
        return redirect
    ok, answer = await claude_auth.check()
    if ok:
        return _back(request, ok=f"Claude отвечает: «{answer}». Вход действует.")
    return _back(request, err=answer)
