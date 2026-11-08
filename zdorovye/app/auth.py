"""Первая настройка, вход, выход, приглашения и доступ к чужим страничкам."""
import io
import logging
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import segno
from fastapi import APIRouter, Form, HTTPException, Request

from . import config, db, security
from .web import (client_ip, csrf_ok, current, need, need_owner, page, same_origin, templates,
                  set_cookie, to)

router = APIRouter()
log = logging.getLogger("uvicorn.error")


def _pre_page(request: Request, name: str, ctx: dict | None = None, status: int = 200):
    """Страница до входа со своим защитным знаком формы."""
    pre = secrets.token_urlsafe(16)
    resp = page(request, name, {"pre": pre, **(ctx or {})}, status)
    set_cookie(resp, config.PRE_COOKIE, pre)
    return resp


def _pre_ok(request: Request, pre: str) -> bool:
    return same_origin(request) and security.same(pre, request.cookies.get(config.PRE_COOKIE, ""))


def _too_many() -> str:
    return f"Слишком много попыток. Попробуй через {config.FAIL_WINDOW_MIN} минут"


def owner_exists() -> bool:
    return db.one("SELECT id FROM users WHERE role = 'owner'") is not None


def _enter(request: Request, user_id: int):
    resp = to(request, "home")
    set_cookie(resp, config.COOKIE_NAME, security.new_session(user_id), config.SESSION_HOURS * 3600)
    resp.delete_cookie(config.PRE_COOKIE, path=config.ROOT_PATH or "/")
    return resp


# ── Первая настройка (только для Светланы, по разовой ссылке) ────────────

def _setup_value(key: str) -> str | None:
    row = db.one("SELECT value FROM setup WHERE key = ?", (key,))
    return row["value"] if row else None


def _setup_ok(token: str) -> bool:
    stored = _setup_value("token_hash")
    return bool(stored) and security.same(security.token_hash(token), stored)


def _otp_uri(secret: str) -> str:
    # Латиницей и коротко: QR выходит крупнее и проще, камера айфона читает его увереннее
    return f"otpauth://totp/Zdorovye:{quote(config.OWNER_LOGIN)}?secret={secret}&issuer=Zdorovye"


def _qr_svg(secret: str) -> str:
    buf = io.BytesIO()
    segno.make(_otp_uri(secret), error="l").save(buf, kind="svg", scale=8, border=4, dark="#000", light="#fff", omitsize=True,
                                                 xmldecl=False, svgns=True)
    return buf.getvalue().decode()


def _setup_ctx(token: str) -> dict:
    secret = _setup_value("totp_secret") or ""
    pretty = " ".join(secret[i:i + 4] for i in range(0, len(secret), 4))
    return {"token": token, "login": config.OWNER_LOGIN, "qr": _qr_svg(secret), "secret": pretty,
            "otp_uri": _otp_uri(secret)}


@router.get("/setup/{token}", name="setup_form")
def setup_form(request: Request, token: str):
    if owner_exists() or not _setup_ok(token):
        return to(request, "login_form")
    return _pre_page(request, "setup.html", _setup_ctx(token))


@router.post("/setup/{token}", name="setup")
def setup(request: Request, token: str, password: str = Form(""), password2: str = Form(""),
          code: str = Form(""), pre: str = Form("")):
    if owner_exists() or not _setup_ok(token):
        return to(request, "login_form")
    ip = client_ip(request)

    def again(error: str):
        log.warning("первая настройка не прошла: %s", error.split(".")[0])   # для разбора, без секретов
        return _pre_page(request, "setup.html", {**_setup_ctx(token), "error": error}, 400)

    if not _pre_ok(request, pre):
        return again("Форма устарела — попробуй ещё раз")
    if security.blocked(ip):
        return again(_too_many())
    if password != password2:
        return again("Пароли не совпадают")
    if problem := security.password_problem(password):
        return again(problem)
    secret = _setup_value("totp_secret")
    step = security.totp_step(secret, code, 0)
    if step is None:
        security.note_fail(ip)
        return again("Код с телефона не подошёл. Нужен код из новой строки «Здоровье», не из старой "
                     "строки основного сайта. Если ключ вводила вручную: в нём нет цифр 0 и 1 — "
                     "это буквы O и I. Проще всего удалить строку «Здоровье» и добавить заново")
    db.insert("INSERT INTO users (login, password_hash, role, totp_secret, totp_last, created_at) "
              "VALUES (?, ?, 'owner', ?, ?, ?)",
              (config.OWNER_LOGIN, security.hash_secret(password), secret, step, db.now()))
    db.run("DELETE FROM setup")
    return to(request, "login_form")


# ── Вход ─────────────────────────────────────────────────────────────────

@router.get("/login", name="login_form")
def login_form(request: Request):
    if current(request):
        return to(request, "home")
    return _pre_page(request, "login.html", {"ready": owner_exists()})


@router.post("/login", name="login")
def login(request: Request, login: str = Form(""), password: str = Form(""), pre: str = Form("")):
    ip = client_ip(request)
    if not _pre_ok(request, pre):
        return _pre_page(request, "login.html", {"ready": True, "error": "Форма устарела — попробуй ещё раз"}, 400)
    if security.blocked(ip):
        return _pre_page(request, "login.html", {"ready": True, "error": _too_many()}, 429)
    user = db.one("SELECT id, password_hash, totp_secret FROM users WHERE login = ?", (login.strip(),))
    if not security.check_secret(user["password_hash"] if user else None, password):
        security.note_fail(ip)
        return _pre_page(request, "login.html", {"ready": True, "error": "Неверный логин или пароль"}, 401)
    if user["totp_secret"]:
        return _pre_page(request, "login_code.html",
                         {"pass_token": security.make_pass(user["id"], user["password_hash"])})
    return _enter(request, user["id"])


@router.post("/login/code", name="login_code")
def login_code(request: Request, pass_token: str = Form(""), code: str = Form(""), pre: str = Form("")):
    ip = client_ip(request)
    user_id = security.read_pass(pass_token)
    if not _pre_ok(request, pre) or user_id is None:
        return _pre_page(request, "login.html", {"ready": True, "error": "Вход устарел — начни заново"}, 400)
    if security.blocked(ip):
        return _pre_page(request, "login.html", {"ready": True, "error": _too_many()}, 429)
    user = db.one("SELECT totp_secret, totp_last FROM users WHERE id = ?", (user_id,))
    step = security.totp_step(user["totp_secret"], code, user["totp_last"])
    if step is not None:
        with db.tx() as con:
            taken = con.execute("UPDATE users SET totp_last = ? WHERE id = ? AND totp_last < ?",
                                (step, user_id, step)).rowcount
        if taken:
            return _enter(request, user_id)
    security.note_fail(ip)
    return _pre_page(request, "login_code.html", {"pass_token": pass_token, "error": "Код не подошёл"}, 401)


@router.post("/logout", name="logout")
def logout(request: Request, csrf: str = Form("")):
    sess = current(request)
    if sess and csrf_ok(request, sess, csrf):
        security.end_session(sess["id"])
    resp = to(request, "login_form")
    resp.delete_cookie(config.COOKIE_NAME, path=config.ROOT_PATH or "/")
    return resp


# ── Приглашения ──────────────────────────────────────────────────────────

def _invite(token: str) -> dict | None:
    row = db.one("SELECT i.*, m.name FROM invites i JOIN members m ON m.id = i.member_id "
                 "WHERE i.token_hash = ?", (security.token_hash(token),))
    if not row or row["used_at"] or datetime.fromisoformat(row["expires_at"]) <= datetime.now(timezone.utc):
        return None
    return row


@router.post("/invites/new", name="invite_new")
def invite_new(request: Request, member_id: int = Form(...), csrf: str = Form("")):
    need_owner(request, csrf)
    if not db.one("SELECT id FROM members WHERE id = ?", (member_id,)):
        raise HTTPException(404, "Такого человека нет")
    if db.one("SELECT id FROM users WHERE member_id = ?", (member_id,)):
        raise HTTPException(400, "У этого человека уже есть вход")
    token = secrets.token_urlsafe(24)
    created = datetime.now(timezone.utc)
    # Старые неиспользованные приглашения этому же человеку больше не нужны
    db.run("DELETE FROM invites WHERE member_id = ? AND used_at IS NULL", (member_id,))
    db.insert("INSERT INTO invites (token_hash, member_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
              (security.token_hash(token), member_id, created.isoformat(),
               (created + timedelta(days=config.INVITE_DAYS)).isoformat()))
    link = f"{config.SITE_URL}{config.ROOT_PATH}/join/{token}"
    # Ссылка показывается один раз: в базе её не осталось
    return page(request, "invite_link.html", {"sess": need(request), "active": "access", "link": link,
                                              "member": db.one("SELECT * FROM members WHERE id = ?", (member_id,)),
                                              "days": config.INVITE_DAYS})


@router.post("/invites/{invite_id}/cancel", name="invite_cancel")
def invite_cancel(request: Request, invite_id: int, csrf: str = Form("")):
    need_owner(request, csrf)
    db.run("DELETE FROM invites WHERE id = ? AND used_at IS NULL", (invite_id,))
    return to(request, "access_page")


@router.get("/join/{token}", name="join_form")
def join_form(request: Request, token: str):
    inv = _invite(token)
    if not inv:
        return _pre_page(request, "join.html", {"dead": True}, 404)
    return _pre_page(request, "join.html", {"token": token, "name": inv["name"]})


@router.post("/join/{token}", name="join")
def join(request: Request, token: str, login: str = Form(""), password: str = Form(""),
         password2: str = Form(""), pre: str = Form("")):
    ip = client_ip(request)
    inv = _invite(token)
    if not inv:
        return _pre_page(request, "join.html", {"dead": True}, 404)

    def again(error: str):
        return _pre_page(request, "join.html", {"token": token, "name": inv["name"],
                                                "login": login, "error": error}, 400)

    if not _pre_ok(request, pre):
        return again("Форма устарела — попробуй ещё раз")
    if security.blocked(ip):
        return again(_too_many())
    login = login.strip()
    if not 2 <= len(login) <= 40 or any(ch.isspace() for ch in login):
        return again("Логин — от 2 до 40 знаков, без пробелов")
    if db.one("SELECT id FROM users WHERE login = ?", (login,)):
        return again("Такой логин уже занят — придумай другой")
    if password != password2:
        return again("Пароли не совпадают")
    if problem := security.password_problem(password):
        return again(problem)
    with db.tx() as con:
        # Условная запись: одна ссылка — один вход, даже при двух нажатиях сразу
        if not con.execute("UPDATE invites SET used_at = ? WHERE id = ? AND used_at IS NULL",
                           (db.now(), inv["id"])).rowcount:
            return _pre_page(request, "join.html", {"dead": True}, 404)
        user_id = con.execute("INSERT INTO users (login, password_hash, role, member_id, created_at) "
                              "VALUES (?, ?, 'member', ?, ?)",
                              (login, security.hash_secret(password), inv["member_id"], db.now())).lastrowid
    return _enter(request, user_id)


# ── Доступ к чужим страничкам ────────────────────────────────────────────

@router.post("/access/ask", name="access_ask")
def access_ask(request: Request, member_id: int = Form(...), csrf: str = Form("")):
    sess = need(request, csrf)
    if sess["role"] == "owner" or sess["member_id"] == member_id:
        return to(request, "home")
    if not db.one("SELECT id FROM members WHERE id = ?", (member_id,)):
        raise HTTPException(404, "Такого человека нет")
    if not db.one("SELECT id FROM access WHERE user_id = ? AND member_id = ? AND state IN ('asked', 'granted')",
                  (sess["user_id"], member_id)):
        db.insert("INSERT INTO access (user_id, member_id, state, asked_at) VALUES (?, ?, 'asked', ?)",
                  (sess["user_id"], member_id, db.now()))
    return to(request, "home")


def _decide(request: Request, access_id: int, csrf: str, frm: str, new: str):
    need_owner(request, csrf)
    db.run("UPDATE access SET state = ?, decided_at = ? WHERE id = ? AND state = ?",
           (new, db.now(), access_id, frm))
    return to(request, "access_page")


@router.post("/access/{access_id}/grant", name="access_grant")
def access_grant(request: Request, access_id: int, csrf: str = Form("")):
    return _decide(request, access_id, csrf, "asked", "granted")


@router.post("/access/{access_id}/decline", name="access_decline")
def access_decline(request: Request, access_id: int, csrf: str = Form("")):
    return _decide(request, access_id, csrf, "asked", "declined")


@router.post("/access/{access_id}/end", name="access_end")
def access_end(request: Request, access_id: int, csrf: str = Form("")):
    return _decide(request, access_id, csrf, "granted", "ended")


@router.post("/users/{user_id}/delete", name="user_delete")
def user_delete(request: Request, user_id: int, csrf: str = Form("")):
    need_owner(request, csrf)
    db.run("DELETE FROM users WHERE id = ? AND role = 'member'", (user_id,))
    return to(request, "access_page")


@router.get("/access", name="access_page")
def access_page(request: Request):
    sess = need_owner(request)
    asked = db.rows("SELECT a.*, u.login, m.name FROM access a JOIN users u ON u.id = a.user_id "
                    "JOIN members m ON m.id = a.member_id WHERE a.state = 'asked' ORDER BY a.asked_at")
    granted_rows = db.rows("SELECT a.*, u.login, m.name FROM access a JOIN users u ON u.id = a.user_id "
                           "JOIN members m ON m.id = a.member_id WHERE a.state = 'granted' ORDER BY m.name")
    users = db.rows("SELECT u.id, u.login, u.created_at, m.name FROM users u "
                    "LEFT JOIN members m ON m.id = u.member_id WHERE u.role = 'member' ORDER BY u.login")
    invites = db.rows("SELECT i.id, i.expires_at, m.name FROM invites i JOIN members m ON m.id = i.member_id "
                      "WHERE i.used_at IS NULL AND i.expires_at > ? ORDER BY i.created_at",
                      (datetime.now(timezone.utc).isoformat(),))
    with_login = {r["member_id"] for r in db.rows("SELECT member_id FROM users WHERE member_id IS NOT NULL")}
    free = [m for m in db.rows("SELECT id, name FROM members ORDER BY name") if m["id"] not in with_login]
    from . import kopii
    return page(request, "access.html", {"sess": sess, "active": "access", "asked": asked,
                                         "granted": granted_rows, "users": users, "invites": invites,
                                         "free": free, "kopii": kopii.state()})


def asked_count() -> int:
    return db.one("SELECT count(*) AS n FROM access WHERE state = 'asked'")["n"]


templates.env.globals["asked_total"] = asked_count
