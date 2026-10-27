"""Общее для всех страниц: шаблоны, вход, защита форм."""
from datetime import datetime

from fastapi import Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from . import config, security

templates = Jinja2Templates(directory=str(config.TEMPLATES_DIR))


def local_time(iso: str) -> str:
    """Время из базы (UTC) — в её поясе, с пометкой."""
    moment = datetime.fromisoformat(iso).astimezone(config.TIMEZONE)
    return f"{moment:%d.%m.%Y %H:%M} {config.TIMEZONE_LABEL}"


def short_time(iso: str) -> str:
    """Короткое время сообщения: сегодня — только часы, иначе с датой."""
    moment = datetime.fromisoformat(iso).astimezone(config.TIMEZONE)
    today = datetime.now(config.TIMEZONE).date()
    stamp = f"{moment:%H:%M}" if moment.date() == today else f"{moment:%d.%m.%Y %H:%M}"
    return f"{stamp} {config.TIMEZONE_LABEL}"


templates.env.globals["local_time"] = local_time
templates.env.globals["short_time"] = short_time


def client_ip(request: Request) -> str:
    real = request.headers.get("x-real-ip") or request.headers.get("x-forwarded-for", "")
    return real.split(",")[0].strip() or (request.client.host if request.client else "?")


def page(request: Request, name: str, ctx: dict | None = None, status: int = 200):
    data = {"request": request, "root": config.ROOT_PATH}
    data.update(ctx or {})
    resp = templates.TemplateResponse(request, name, data, status_code=status)
    resp.headers["Cache-Control"] = "no-store"
    return resp


def to(request: Request, route: str) -> RedirectResponse:
    return RedirectResponse(request.url_for(route), status_code=303)


def same_origin(request: Request) -> bool:
    """Запрос пришёл со страницы этого же сайта. Браузеры шлют Origin на
    POST; нет его — сверяем Referer."""
    origin = request.headers.get("origin") or request.headers.get("referer", "")
    host = request.headers.get("host", "")
    return bool(origin) and origin.split("://", 1)[-1].split("/", 1)[0] == host


def set_cookie(resp, name: str, value: str, max_age: int | None = None) -> None:
    resp.set_cookie(name, value, max_age=max_age, path=config.ROOT_PATH or "/",
                    httponly=True, secure=config.COOKIE_SECURE, samesite="lax")


def here(request: Request) -> str:
    """Путь текущей страницы вместе с корнем сайта."""
    path, root = request.url.path, config.ROOT_PATH or ""
    return path if path.startswith(root + "/") else root + path


def current(request: Request) -> dict | None:
    return security.session_of(request.cookies.get(config.COOKIE_NAME))


def csrf_ok(request: Request, sess: dict, token: str) -> bool:
    return same_origin(request) and security.same(token, sess["csrf"])


def guarded(request: Request, name: str, active: str, ctx: dict | None = None):
    """Страница только после входа. Под замком — только шторка."""
    sess = current(request)
    if not sess:
        return to(request, "login_form")
    if sess["locked"]:
        return page(request, "lock.html", {"sess": sess, "back": here(request)})
    return page(request, name, {"sess": sess, "active": active, **(ctx or {})})
