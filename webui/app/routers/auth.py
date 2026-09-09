"""Вход, смена пароля, выход."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from .. import config, db, security
from ..deps import client_ip, current_user, render

router = APIRouter()


def _recent_fails(ip: str) -> int:
    since = datetime.now(timezone.utc) - timedelta(minutes=config.LOGIN_WINDOW_MIN)
    row = db.query_one(
        "SELECT count(*) AS n FROM login_attempts WHERE ip = %s AND ok = false AND at > %s",
        (ip, since),
    )
    return int(row["n"]) if row else 0


def _record_attempt(login: str, ip: str, ok: bool) -> None:
    db.execute(
        "INSERT INTO login_attempts (login, ip, ok) VALUES (%s, %s, %s)", (login, ip, ok)
    )


@router.get("/login", name="login_form")
def login_form(request: Request):
    if current_user(request):
        return RedirectResponse(request.url_for("dashboard"), status_code=303)
    return render(request, "login.html", {"user": None})


@router.post("/login", name="login_submit")
def login_submit(
    request: Request,
    login: str = Form(...),
    password: str = Form(...),
):
    ip = client_ip(request)

    # Защита от перебора: после серии неудач с одного адреса вход закрывается на окно
    if _recent_fails(ip) >= config.LOGIN_MAX_FAILS:
        return render(
            request,
            "login.html",
            {
                "user": None,
                "error": f"Слишком много неудачных попыток. "
                         f"Повторите через {config.LOGIN_WINDOW_MIN} минут.",
            },
        )

    row = db.query_one(
        "SELECT id, login, password_hash, must_change FROM users WHERE login = %s",
        (login.strip(),),
    )
    if not row or not security.verify_password(row["password_hash"], password):
        _record_attempt(login, ip, False)
        return render(
            request, "login.html", {"user": None, "error": "Неверный логин или пароль"}
        )

    _record_attempt(login, ip, True)

    # Параметры хеширования могли усилиться со времени последнего входа
    if security.needs_rehash(row["password_hash"]):
        db.execute(
            "UPDATE users SET password_hash = %s WHERE id = %s",
            (security.hash_password(password), row["id"]),
        )

    session_id = security.new_session_id()
    db.execute(
        "INSERT INTO sessions (id, user_id, expires_at, ip, user_agent) "
        "VALUES (%s, %s, %s, %s, %s)",
        (
            session_id,
            row["id"],
            security.session_expiry(),
            ip,
            (request.headers.get("user-agent") or "")[:300],
        ),
    )
    db.execute("UPDATE users SET last_login_at = now() WHERE id = %s", (row["id"],))

    target = "change_password_form" if row["must_change"] else "dashboard"
    response = RedirectResponse(request.url_for(target), status_code=303)
    response.set_cookie(
        config.COOKIE_NAME,
        security.sign_session_id(session_id),
        max_age=config.SESSION_DAYS * 86400,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        path="/",
    )
    return response


@router.get("/password", name="change_password_form")
def change_password_form(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse(request.url_for("login_form"), status_code=303)
    return render(request, "password.html", {"user": user})


@router.post("/password", name="change_password_submit")
def change_password_submit(
    request: Request,
    current: str = Form(""),
    password: str = Form(...),
    confirm: str = Form(...),
):
    user = current_user(request)
    if not user:
        return RedirectResponse(request.url_for("login_form"), status_code=303)

    row = db.query_one("SELECT password_hash FROM users WHERE id = %s", (user["id"],))

    def fail(message: str):
        return render(request, "password.html", {"user": user, "error": message})

    # Действующий пароль спрашиваем всегда: иначе чужая открытая сессия
    # позволила бы сменить пароль, не зная текущего
    if not row or not security.verify_password(row["password_hash"], current):
        return fail("Действующий пароль указан неверно")
    if password != confirm:
        return fail("Пароли не совпадают")
    problem = security.password_problem(password)
    if problem:
        return fail(problem)

    db.execute(
        "UPDATE users SET password_hash = %s, must_change = false WHERE id = %s",
        (security.hash_password(password), user["id"]),
    )
    # Пароль сменён — все прочие сессии закрываются
    db.execute(
        "DELETE FROM sessions WHERE user_id = %s AND id <> %s",
        (user["id"], user["session_id"]),
    )
    return RedirectResponse(request.url_for("dashboard"), status_code=303)


@router.post("/logout", name="logout")
def logout(request: Request):
    user = current_user(request)
    if user:
        db.execute("DELETE FROM sessions WHERE id = %s", (user["session_id"],))
    response = RedirectResponse(request.url_for("login_form"), status_code=303)
    response.delete_cookie(config.COOKIE_NAME, path="/")
    return response
