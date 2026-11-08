"""Общее для всех страниц: шаблоны, вход, защита форм, права на странички."""
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from . import config, db, security

templates = Jinja2Templates(directory=str(config.TEMPLATES_DIR))
ZONE = ZoneInfo(config.ZONE)


# ── Даты ─────────────────────────────────────────────────────────────────

def parse_day(value: str) -> date | None:
    try:
        return date.fromisoformat((value or "").strip())
    except ValueError:
        return None


def day(value: str) -> str:
    """ГГГГ-ММ-ДД → ДД.ММ.ГГГГ; пусто — пусто."""
    d = parse_day(value)
    return f"{d:%d.%m.%Y}" if d else (value or "")


def moment(iso: str) -> str:
    """Время из базы (UTC) — по Москве, с пометкой."""
    if not iso:
        return ""
    return f"{datetime.fromisoformat(iso).astimezone(ZONE):%d.%m.%Y %H:%M} {config.ZONE_LABEL}"


def today() -> date:
    return datetime.now(ZONE).date()


def age(birth: str) -> str:
    b = parse_day(birth)
    if not b:
        return ""
    t = today()
    years = t.year - b.year - ((t.month, t.day) < (b.month, b.day))
    if years >= 1:
        last = years % 10
        word = "лет" if 11 <= years % 100 <= 14 or last == 0 or last >= 5 else ("год" if last == 1 else "года")
        return f"{years} {word}"
    months = (t.year - b.year) * 12 + t.month - b.month - (t.day < b.day)
    return f"{max(months, 0)} мес."


def num(value) -> str:
    """Число без лишних нулей и с запятой: 4.50 → 4,5."""
    if value is None:
        return ""
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return text.replace(".", ",")


templates.env.filters["day"] = day
templates.env.filters["moment"] = moment
templates.env.filters["num"] = num
templates.env.globals["age"] = age


# ── Запросы ──────────────────────────────────────────────────────────────

def client_ip(request: Request) -> str:
    real = request.headers.get("x-real-ip") or request.headers.get("x-forwarded-for", "")
    return real.split(",")[0].strip() or (request.client.host if request.client else "?")


def page(request: Request, name: str, ctx: dict | None = None, status: int = 200):
    data = {"request": request, "root": config.ROOT_PATH}
    data.update(ctx or {})
    resp = templates.TemplateResponse(request, name, data, status_code=status)
    resp.headers["Cache-Control"] = "no-store"
    return resp


def to(request: Request, route: str, **params) -> RedirectResponse:
    return RedirectResponse(request.url_for(route, **params), status_code=303)


def same_origin(request: Request) -> bool:
    origin = request.headers.get("origin") or request.headers.get("referer", "")
    host = request.headers.get("host", "")
    return bool(origin) and origin.split("://", 1)[-1].split("/", 1)[0] == host


def set_cookie(resp, name: str, value: str, max_age: int | None = None) -> None:
    resp.set_cookie(name, value, max_age=max_age, path=config.ROOT_PATH or "/",
                    httponly=True, secure=config.COOKIE_SECURE, samesite="lax")


def current(request: Request) -> dict | None:
    return security.session_of(request.cookies.get(config.COOKIE_NAME))


def csrf_ok(request: Request, sess: dict, token: str) -> bool:
    return same_origin(request) and security.same(token, sess["csrf"])


class NeedLogin(Exception):
    """Нет входа — на страницу входа (обрабатывается в main)."""


def need(request: Request, csrf: str | None = None) -> dict:
    """Сессия обязательна; для форм — ещё и защитный знак."""
    sess = current(request)
    if not sess:
        raise NeedLogin()
    if csrf is not None and not csrf_ok(request, sess, csrf):
        raise HTTPException(403, "Форма устарела — обнови страницу")
    return sess


def owner(sess: dict) -> bool:
    return sess["role"] == "owner"


def need_owner(request: Request, csrf: str | None = None) -> dict:
    sess = need(request, csrf)
    if not owner(sess):
        raise HTTPException(403, "Это может только Светлана")
    return sess


# ── Права на странички ───────────────────────────────────────────────────

def granted(user_id: int, member_id: int) -> bool:
    return db.one("SELECT id FROM access WHERE user_id = ? AND member_id = ? AND state = 'granted'",
                  (user_id, member_id)) is not None


def can_view(sess: dict, member_id: int) -> bool:
    return owner(sess) or sess["member_id"] == member_id or granted(sess["user_id"], member_id)


def can_edit(sess: dict, member_id: int) -> bool:
    """Править: Светлана — всё, остальные — только свою страничку."""
    return owner(sess) or sess["member_id"] == member_id


def member_for(request: Request, member_id: int, edit: bool = False, csrf: str | None = None) -> tuple[dict, dict]:
    """(сессия, член семьи) с проверкой прав. Чужая страничка без доступа — 404,
    чтобы не было видно даже, есть ли такая."""
    sess = need(request, csrf)
    member = db.one("SELECT * FROM members WHERE id = ?", (member_id,))
    if not member or not can_view(sess, member_id):
        raise HTTPException(404, "Такой странички нет или к ней нет доступа")
    if edit and not can_edit(sess, member_id):
        raise HTTPException(403, "Эту страничку можно только смотреть")
    return sess, member


def visible_members(sess: dict) -> list[dict]:
    members = db.rows("SELECT * FROM members ORDER BY id")
    return [m for m in members if can_view(sess, m["id"])]
