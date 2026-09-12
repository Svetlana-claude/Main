"""Панель управления VPN: клиенты, QR-коды, трафик.

Вся работа с сервером идёт через службу `services.vpn`, то есть через обёртку
`webui-vpn`. Прямых обращений к `/etc/wireguard` здесь нет и не должно быть.

Внимание к тому, что отдаётся наружу: конфиг клиента и QR-код содержат его
закрытый ключ. Поэтому оба маршрута закрыты тем же входом, что и остальные
страницы, а имя клиента сверяется с образцом до всякого обращения к файлу.
"""
from fastapi import APIRouter, Form, Request
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse, Response

from ..deps import current_user, render
from ..services import vpn

router = APIRouter()


def _guard(request: Request):
    user = current_user(request)
    if not user:
        return None, RedirectResponse(request.url_for("login_form"), status_code=303)
    if user["must_change"]:
        return None, RedirectResponse(request.url_for("change_password_form"), status_code=303)
    return user, None


def _back(request: Request, **params) -> RedirectResponse:
    url = request.url_for("vpn_page")
    if params:
        url = url.include_query_params(**params)
    return RedirectResponse(url, status_code=303)


@router.get("/vpn", name="vpn_page")
def vpn_page(request: Request):
    user, redirect = _guard(request)
    if redirect:
        return redirect

    state = vpn.state()
    return render(
        request,
        "vpn.html",
        {
            "user": user,
            "active": "vpn",
            "state": state,
            "err": request.query_params.get("err", ""),
            "added": request.query_params.get("added", ""),
            "removed": request.query_params.get("removed", ""),
        },
    )


@router.get("/vpn/state", name="vpn_state")
def vpn_state(request: Request):
    """Состояние для опроса из браузера: трафик и рукопожатия обновляются сами."""
    user, redirect = _guard(request)
    if redirect:
        # Опрос не должен уводить страницу на вход: пусть просто скажет «нет».
        return JSONResponse({"ok": False}, status_code=401)

    state = vpn.state()
    return JSONResponse(
        {
            "ok": True,
            "active": state.active,
            "note": state.note,
            # Готовые строки считает Python: повтори их в браузере — и «5 минут
            # назад» разойдётся с тем, что нарисовано на странице при отрисовке.
            "rx_total_text": state.rx_total_text,
            "tx_total_text": state.tx_total_text,
            "peers": [
                {
                    "name": p.name,
                    "ip": p.ip,
                    "rx_text": p.rx_text,
                    "tx_text": p.tx_text,
                    "seen_text": p.seen_text,
                    "online": p.online,
                    "endpoint": p.endpoint,
                }
                for p in state.peers
            ],
        }
    )


@router.post("/vpn/add", name="vpn_add")
def vpn_add(request: Request, name: str = Form(""), split: str = Form("")):
    user, redirect = _guard(request)
    if redirect:
        return redirect
    try:
        vpn.add(name.strip(), split=bool(split))
    except vpn.VpnError as exc:
        return _back(request, err=str(exc))
    return _back(request, added=name.strip())


@router.post("/vpn/remove", name="vpn_remove")
def vpn_remove(request: Request, name: str = Form("")):
    user, redirect = _guard(request)
    if redirect:
        return redirect
    try:
        vpn.remove(name.strip())
    except vpn.VpnError as exc:
        return _back(request, err=str(exc))
    return _back(request, removed=name.strip())


@router.get("/vpn/qr/{name}", name="vpn_qr")
def vpn_qr(request: Request, name: str):
    user, redirect = _guard(request)
    if redirect:
        return redirect
    try:
        svg = vpn.qr_svg(name)
    except vpn.VpnError as exc:
        return PlainTextResponse(str(exc), status_code=404)
    # Картинку с закрытым ключом кэшировать незачем — ни браузеру, ни прокси.
    return Response(
        svg,
        media_type="image/svg+xml",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/vpn/conf/{name}", name="vpn_conf")
def vpn_conf(request: Request, name: str):
    user, redirect = _guard(request)
    if redirect:
        return redirect
    try:
        text = vpn.conf_text(name)
    except vpn.VpnError as exc:
        return PlainTextResponse(str(exc), status_code=404)
    return PlainTextResponse(
        text,
        headers={
            "Content-Disposition": f'attachment; filename="{name}.conf"',
            "Cache-Control": "no-store",
        },
    )
