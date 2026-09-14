"""Вход, смена пароля, выход."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from .. import config, db, security
from ..deps import client_ip, current_user, render
from ..services import totp

# Пропуск ко второму шагу входа. Выдаётся только после верного пароля и живёт
# пять минут. Подписан тем же SECRET_KEY, но со своей солью — подпись сессии
# за пропуск не сойдёт и наоборот. В пропуск вшит хвост хеша пароля: сменили
# пароль — выданные до этого пропуска перестают действовать.
_pending = URLSafeTimedSerializer(config.SECRET_KEY, salt="totp-pending")
PENDING_MAX_AGE = 300

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
        "SELECT id, login, password_hash, must_change, totp_enabled FROM users WHERE login = %s",
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
        fresh = security.hash_password(password)
        db.execute("UPDATE users SET password_hash = %s WHERE id = %s", (fresh, row["id"]))
        # Пропуск ко второму шагу строится из хеша — из нового, иначе после
        # перехеширования второй шаг ответил бы «войдите заново».
        row = {**row, "password_hash": fresh}

    if row["totp_enabled"]:
        # Пароль верен, но сессии ещё нет: без кода из приложения она не выдаётся.
        token = _pending.dumps({"u": row["id"], "h": row["password_hash"][-16:]})
        return render(request, "login_totp.html", {"user": None, "token": token})

    return _start_session(request, row, ip)


def _start_session(request: Request, row: dict, ip: str):
    """Сессия и cookie. Вызывается только после всех факторов входа."""
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


@router.post("/login/totp", name="login_totp_submit")
def login_totp_submit(request: Request, token: str = Form(""), code: str = Form("")):
    ip = client_ip(request)

    def again(message: str, token_value: str = token):
        return render(request, "login_totp.html",
                      {"user": None, "token": token_value, "error": message})

    def restart(message: str):
        return render(request, "login.html", {"user": None, "error": message})

    # Перебор кода считается вместе с перебором пароля: окно одно на адрес.
    if _recent_fails(ip) >= config.LOGIN_MAX_FAILS:
        return restart(f"Слишком много неудачных попыток. "
                       f"Повторите через {config.LOGIN_WINDOW_MIN} минут.")

    try:
        data = _pending.loads(token, max_age=PENDING_MAX_AGE)
    except SignatureExpired:
        return restart("Время на ввод кода вышло — войдите заново.")
    except BadSignature:
        return restart("Войдите заново.")

    row = db.query_one(
        "SELECT id, login, password_hash, must_change, totp_secret, totp_enabled, totp_last_step "
        "FROM users WHERE id = %s",
        (data.get("u"),),
    )
    if (not row or not row["totp_enabled"] or not row["totp_secret"]
            or row["password_hash"][-16:] != data.get("h")):
        return restart("Войдите заново.")

    step = totp.match(row["totp_secret"], code, row["totp_last_step"])
    if step is None:
        _record_attempt(f"{row['login']} (код)", ip, False)
        return again("Код не подошёл. Введите текущий код из приложения.")

    # Отрезок фиксируется условным UPDATE, а не проверкой и записью порознь:
    # два одновременных запроса с одним кодом иначе прошли бы оба.
    taken = db.query_one(
        "UPDATE users SET totp_last_step = %s WHERE id = %s AND totp_last_step < %s RETURNING id",
        (step, row["id"], step),
    )
    if not taken:
        _record_attempt(f"{row['login']} (код)", ip, False)
        return again("Этот код уже использован. Дождитесь следующего.")

    _record_attempt(row["login"], ip, True)
    return _start_session(request, row, ip)


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
