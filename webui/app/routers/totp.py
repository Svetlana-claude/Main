"""Подключение и отключение второго фактора входа (код из приложения).

Порядок подключения нарочно в два шага: секрет сперва только «ожидает», и лишь
верный код из приложения его включает. Иначе ошибка при сканировании QR-кода —
не то приложение, сбитые часы на телефоне — закрыла бы вход своему же хозяину.

Отключение требует и пароль, и текущий код: одной открытой чужой сессии для
этого мало, иначе второй фактор снимался бы ровно тем, от чего он защищает.

Страницы с секретом и QR-кодом не кэшируются — ни браузером, ни прокси.
"""
from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from .. import db, security
from ..deps import current_user, render
from ..services import totp

router = APIRouter()


def _guard(request: Request):
    user = current_user(request)
    if not user:
        return None, RedirectResponse(request.url_for("login_form"), status_code=303)
    if user["must_change"]:
        return None, RedirectResponse(request.url_for("change_password_form"), status_code=303)
    return user, None


def _back(request: Request, **params) -> RedirectResponse:
    url = request.url_for("totp_page")
    if params:
        url = url.include_query_params(**params)
    return RedirectResponse(url, status_code=303)


def _row(user_id: int) -> dict:
    return db.query_one(
        "SELECT login, password_hash, totp_secret, totp_enabled, totp_last_step "
        "FROM users WHERE id = %s",
        (user_id,),
    )


@router.get("/settings/totp", name="totp_page")
def totp_page(request: Request):
    user, redirect = _guard(request)
    if redirect:
        return redirect

    row = _row(user["id"])
    ctx = {
        "user": user,
        "active": "settings",
        "enabled": row["totp_enabled"],
        "pending": bool(row["totp_secret"]) and not row["totp_enabled"],
        "err": request.query_params.get("err", ""),
        "ok": request.query_params.get("ok", ""),
    }
    if ctx["pending"]:
        uri = totp.provisioning_uri(row["totp_secret"], row["login"])
        ctx["secret"] = totp.grouped(row["totp_secret"])
        try:
            ctx["qr"] = totp.qr_svg(uri)
        except totp.TotpError as exc:
            ctx["qr"] = ""
            ctx["err"] = f"QR-код не построен ({exc}) — введите секрет в приложение вручную."

    page = render(request, "settings_totp.html", ctx)
    page.headers["Cache-Control"] = "no-store"
    return page


@router.post("/settings/totp/start", name="totp_start")
def totp_start(request: Request):
    user, redirect = _guard(request)
    if redirect:
        return redirect
    if _row(user["id"])["totp_enabled"]:
        return _back(request, err="Второй фактор уже включён.")
    # Новый секрет при каждом нажатии: прежний ожидавший мог быть показан
    # на чужом экране, и продолжать с ним незачем.
    db.execute(
        "UPDATE users SET totp_secret = %s, totp_last_step = 0 WHERE id = %s AND NOT totp_enabled",
        (totp.new_secret(), user["id"]),
    )
    return _back(request)


@router.post("/settings/totp/enable", name="totp_enable")
def totp_enable(request: Request, code: str = Form("")):
    user, redirect = _guard(request)
    if redirect:
        return redirect
    row = _row(user["id"])
    if row["totp_enabled"]:
        return _back(request, err="Второй фактор уже включён.")
    if not row["totp_secret"]:
        return _back(request, err="Сперва нажмите «Подключить».")

    step = totp.match(row["totp_secret"], code, 0)
    if step is None:
        return _back(request, err="Код не подошёл. Проверьте, что добавили именно этот "
                                  "QR-код, и что время на телефоне выставлено автоматически.")

    db.execute(
        "UPDATE users SET totp_enabled = true, totp_last_step = %s WHERE id = %s",
        (step, user["id"]),
    )
    # Прочие сессии закрываются: какая-то из них могла быть открыта чужим, кто
    # знал пароль, и после включения второго фактора держаться ей не на чем.
    db.execute(
        "DELETE FROM sessions WHERE user_id = %s AND id <> %s",
        (user["id"], user["session_id"]),
    )
    return _back(request, ok="Второй фактор включён. Остальные сессии закрыты.")


@router.post("/settings/totp/cancel", name="totp_cancel")
def totp_cancel(request: Request):
    user, redirect = _guard(request)
    if redirect:
        return redirect
    db.execute(
        "UPDATE users SET totp_secret = NULL, totp_last_step = 0 WHERE id = %s AND NOT totp_enabled",
        (user["id"],),
    )
    return _back(request)


@router.post("/settings/totp/disable", name="totp_disable")
def totp_disable(request: Request, password: str = Form(""), code: str = Form("")):
    user, redirect = _guard(request)
    if redirect:
        return redirect
    row = _row(user["id"])
    if not row["totp_enabled"]:
        return _back(request)
    if not security.verify_password(row["password_hash"], password):
        return _back(request, err="Пароль указан неверно.")
    step = totp.match(row["totp_secret"], code, row["totp_last_step"])
    if step is None:
        return _back(request, err="Код не подошёл.")

    db.execute(
        "UPDATE users SET totp_enabled = false, totp_secret = NULL, totp_last_step = 0 WHERE id = %s",
        (user["id"],),
    )
    return _back(request, ok="Второй фактор отключён. Вход снова только по паролю.")
