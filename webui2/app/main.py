"""Личный сайт для общения с Claude: вход, замок, страницы."""
import asyncio
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import chat, config, db, files, load, perms, pictures, projects, sec, security, settings, vpn  # noqa: F401 (files — свои адреса в projects.router)
from .web import client_ip, csrf_ok, current, guarded, page, same_origin, set_cookie, to


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not config.SECRET_KEY:
        raise RuntimeError(f"нет SECRET_KEY в {config.ENV_FILE}")
    db.init()
    recorder = asyncio.create_task(load.recorder())
    yield
    recorder.cancel()


app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(config.STATIC_DIR)), name="static")
app.include_router(chat.router)
app.include_router(projects.router)
app.include_router(perms.router)
app.include_router(settings.router)
app.include_router(sec.router)
app.include_router(vpn.router)
app.include_router(pictures.router)


def user_exists() -> bool:
    return db.one("SELECT id FROM users LIMIT 1") is not None


# ── Первая настройка ─────────────────────────────────────────────────────

def _setup_secret() -> str | None:
    row = db.one("SELECT value FROM setup WHERE key = 'totp_secret'")
    return row["value"] if row else None


@app.get("/setup", name="setup_form")
def setup_form(request: Request):
    if user_exists():
        return to(request, "login_form")
    pre = secrets.token_urlsafe(16)
    resp = page(request, "setup.html", {"pre": pre, "login": config.LOGIN,
                                        "ready": bool(_setup_secret())})
    set_cookie(resp, config.PRE_COOKIE, pre)
    return resp


@app.post("/setup", name="setup")
def setup(request: Request, password: str = Form(""), password2: str = Form(""),
          lock: str = Form(""), lock2: str = Form(""), code: str = Form(""),
          pre: str = Form("")):
    if user_exists():
        return to(request, "login_form")
    ip = client_ip(request)
    secret = _setup_secret()

    def again(error: str):
        new_pre = secrets.token_urlsafe(16)
        resp = page(request, "setup.html", {"pre": new_pre, "login": config.LOGIN,
                                            "ready": bool(secret), "error": error}, 400)
        set_cookie(resp, config.PRE_COOKIE, new_pre)
        return resp

    if not same_origin(request) or not security.same(pre, request.cookies.get(config.PRE_COOKIE, "")):
        return again("Форма устарела — попробуй ещё раз")
    if not secret:
        return again("Настройка не подготовлена")
    if security.blocked(ip):
        return again(f"Слишком много попыток. Попробуй через {config.FAIL_WINDOW_MIN} минут")
    # Код с телефона — первым: без него форму не заполнить никому, кроме хозяйки
    step = security.totp_step(secret, code, 0)
    if step is None:
        security.note_fail(ip)
        return again("Код с телефона не подошёл")
    if password != password2:
        return again("Пароли не совпадают")
    if problem := security.password_problem(password):
        return again(problem)
    if lock != lock2:
        return again("Коды замка не совпадают")
    if problem := security.lock_code_problem(lock):
        return again(problem)
    db.run(
        "INSERT INTO users (login, password_hash, lock_hash, totp_secret, totp_last, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (config.LOGIN, security.hash_secret(password), security.hash_secret(lock), secret, step, db.now()),
    )
    db.run("DELETE FROM setup WHERE key = 'totp_secret'")
    return to(request, "login_form")


# ── Вход ─────────────────────────────────────────────────────────────────

def _login_page(request: Request, name: str, ctx: dict | None = None, status: int = 200):
    pre = secrets.token_urlsafe(16)
    resp = page(request, name, {"pre": pre, **(ctx or {})}, status)
    set_cookie(resp, config.PRE_COOKIE, pre)
    return resp


def _pre_ok(request: Request, pre: str) -> bool:
    return same_origin(request) and security.same(pre, request.cookies.get(config.PRE_COOKIE, ""))


@app.get("/login", name="login_form")
def login_form(request: Request):
    if not user_exists():
        return to(request, "setup_form")
    if current(request):
        return to(request, "home")
    return _login_page(request, "login.html")


@app.post("/login", name="login")
def login(request: Request, login: str = Form(""), password: str = Form(""), pre: str = Form("")):
    ip = client_ip(request)
    if not _pre_ok(request, pre):
        return _login_page(request, "login.html", {"error": "Форма устарела — попробуй ещё раз"}, 400)
    if security.blocked(ip):
        return _login_page(request, "login.html",
                           {"error": f"Слишком много попыток. Попробуй через {config.FAIL_WINDOW_MIN} минут"}, 429)
    user = db.one("SELECT id, password_hash, totp_secret FROM users WHERE login = ?", (login.strip(),))
    if not user or not security.check_secret(user["password_hash"], password):
        security.note_fail(ip)
        return _login_page(request, "login.html", {"error": "Неверный логин или пароль"}, 401)
    if user["totp_secret"]:
        return _login_page(request, "login_code.html",
                           {"pass_token": security.make_pass(user["id"], user["password_hash"])})
    return _enter(request, user["id"])


@app.post("/login/code", name="login_code")
def login_code(request: Request, pass_token: str = Form(""), code: str = Form(""), pre: str = Form("")):
    ip = client_ip(request)
    user_id = security.read_pass(pass_token)
    if not _pre_ok(request, pre) or user_id is None:
        return _login_page(request, "login.html", {"error": "Вход устарел — начни заново"}, 400)
    if security.blocked(ip):
        return _login_page(request, "login.html",
                           {"error": f"Слишком много попыток. Попробуй через {config.FAIL_WINDOW_MIN} минут"}, 429)
    user = db.one("SELECT totp_secret, totp_last FROM users WHERE id = ?", (user_id,))
    step = security.totp_step(user["totp_secret"], code, user["totp_last"])
    if step is not None:
        # Условная запись: два запроса с одним кодом не пройдут оба
        with db.tx() as con:
            taken = con.execute("UPDATE users SET totp_last = ? WHERE id = ? AND totp_last < ?",
                                (step, user_id, step)).rowcount
        if taken:
            return _enter(request, user_id)
    security.note_fail(ip)
    return _login_page(request, "login_code.html",
                       {"pass_token": pass_token, "error": "Код не подошёл"}, 401)


def _enter(request: Request, user_id: int):
    resp = to(request, "home")
    set_cookie(resp, config.COOKIE_NAME, security.new_session(user_id), config.SESSION_HOURS * 3600)
    resp.delete_cookie(config.PRE_COOKIE, path=config.ROOT_PATH or "/")
    return resp


@app.post("/logout", name="logout")
def logout(request: Request, csrf: str = Form("")):
    sess = current(request)
    if sess and csrf_ok(request, sess, csrf):
        security.end_session(sess["id"])
    resp = to(request, "login_form")
    resp.delete_cookie(config.COOKIE_NAME, path=config.ROOT_PATH or "/")
    return resp


# ── Замок ────────────────────────────────────────────────────────────────

@app.post("/lock", name="lock")
def lock(request: Request, csrf: str = Form("")):
    sess = current(request)
    if not sess or not csrf_ok(request, sess, csrf):
        return JSONResponse({"error": "нет доступа"}, status_code=403)
    db.run("UPDATE sessions SET locked = 1 WHERE id = ?", (sess["id"],))
    return JSONResponse({"ok": True})


def _back_path(back: str) -> str:
    """Куда вернуться после замка — только на свою же страницу."""
    root = config.ROOT_PATH or ""
    if back.startswith(root + "/") and not back.startswith("//") and "\\" not in back:
        return back
    return root + "/"


@app.post("/unlock", name="unlock")
def unlock(request: Request, code: str = Form(""), csrf: str = Form(""), back: str = Form("")):
    sess = current(request)
    if not sess or not csrf_ok(request, sess, csrf):
        return to(request, "login_form")
    ip = client_ip(request)
    error = None
    if security.blocked(ip):
        error = f"Слишком много попыток. Попробуй через {config.FAIL_WINDOW_MIN} минут"
    else:
        user = db.one("SELECT lock_hash FROM users WHERE id = ?", (sess["user_id"],))
        if security.check_secret(user["lock_hash"], code):
            db.run("UPDATE sessions SET locked = 0 WHERE id = ?", (sess["id"],))
            return RedirectResponse(_back_path(back), status_code=303)
        security.note_fail(ip)
        error = "Код не подошёл"
    return page(request, "lock.html", {"sess": sess, "error": error, "back": _back_path(back)}, 401)


@app.get("/state", name="state")
def state(request: Request):
    """Для соседних вкладок: жива ли сессия и закрыт ли замок."""
    sess = current(request)
    return JSONResponse({"in": bool(sess), "locked": bool(sess and sess["locked"])},
                        headers={"Cache-Control": "no-store"})


# ── Страницы ─────────────────────────────────────────────────────────────

@app.get("/", name="home")
def home(request: Request):
    return to(request, "chat")


@app.get("/healthz", include_in_schema=False)
def healthz():
    try:
        db.one("SELECT 1 AS ok")
        return {"status": "ok"}
    except Exception as exc:                           # noqa: BLE001
        return JSONResponse({"status": "error", "detail": str(exc)}, status_code=500)


@app.exception_handler(404)
def not_found(request: Request, exc):
    # Незнакомый адрес страницы (например, закладка со старого черновика) —
    # на начало сайта; файлам оформления — честное «нет»
    if request.method == "GET" and "/static/" not in request.url.path:
        return to(request, "home")
    return HTMLResponse("<p>Такой страницы нет</p>", status_code=404)
