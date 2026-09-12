"""Общие зависимости: текущий пользователь, шаблоны, разбор запроса."""
from datetime import datetime, timezone

from fastapi import Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from . import config, db, security, timefmt

templates = Jinja2Templates(directory=str(config.TEMPLATES_DIR))


def client_ip(request: Request) -> str:
    """IP клиента с учётом того, что перед приложением стоит nginx."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "?"


def current_user(request: Request) -> dict | None:
    """Пользователь текущей сессии или None. Заодно продлевает last_seen."""
    token = request.cookies.get(config.COOKIE_NAME)
    if not token:
        return None
    session_id = security.unsign_session_id(token)
    if not session_id:
        return None

    row = db.query_one(
        """
        SELECT s.id AS session_id, s.expires_at, u.id, u.login, u.must_change
        FROM sessions s JOIN users u ON u.id = s.user_id
        WHERE s.id = %s
        """,
        (session_id,),
    )
    if not row:
        return None
    if row["expires_at"] <= datetime.now(timezone.utc):
        db.execute("DELETE FROM sessions WHERE id = %s", (session_id,))
        return None

    db.execute("UPDATE sessions SET last_seen = now() WHERE id = %s", (session_id,))
    return row


def login_redirect(request: Request) -> RedirectResponse:
    return RedirectResponse(request.url_for("login_form"), status_code=303)


def _local_time(tz):
    def local_time(value, pattern: str = timefmt.DEFAULT_PATTERN) -> str:
        return timefmt.fmt(value, pattern, tz)
    return local_time


def render(request: Request, template: str, ctx: dict | None = None):
    """Отрисовка с общим контекстом: пользователь, настройки, активный раздел."""
    user = ctx.get("user") if ctx and "user" in ctx else current_user(request)
    settings = db.get_settings()
    data = {
        "request": request,
        "user": user,
        "settings": settings,
        "theme": settings.get("theme", "light"),
        "root_path": config.ROOT_PATH,
        "tz_name": timefmt.zone_name(settings),
        # Время в поясе из настроек: `{{ time.when(m.created_at) }}` через
        # time-macros.html. Пояс читается здесь один раз на страницу, а не на
        # каждую дату в списке.
        "local_time": _local_time(timefmt.zone(settings)),
    }
    if ctx:
        data.update(ctx)
    return templates.TemplateResponse(template, data)
