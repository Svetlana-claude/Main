"""VPN: устройства WireGuard — список, новое с QR-кодом и файлом, отзыв.

Сервер VPN один, его завёл старый сайт; здесь — только управление
устройствами через обёртку `deploy/webui2-vpn` (sudo -n). В файле устройства
его закрытый ключ: файл и QR-код не хранятся, а каждый раз берутся у обёртки
и отдаются только после входа, без кэша."""
import asyncio
import re
import time
from urllib.parse import quote

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse, Response

from . import claude, config
from .projects import _LAT
from .web import csrf_ok, current, guarded, to

router = APIRouter()

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$")
SECRET_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache", "X-Content-Type-Options": "nosniff"}


async def _run(*args: str, data: bytes | None = None) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *args, stdin=asyncio.subprocess.PIPE if data is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=claude.child_env())
    try:
        out, err = await asyncio.wait_for(proc.communicate(data), timeout=60)
    except asyncio.TimeoutError:
        proc.kill()
        return 1, "", "VPN не ответил за минуту"
    return proc.returncode, out.decode("utf-8", "replace"), err.decode("utf-8", "replace").strip()


async def _vpn(*args: str) -> tuple[int, str, str]:
    try:
        return await _run(*config.VPN_CMD, *args)
    except OSError as exc:
        return 1, "", str(exc)


def _problem(err: str) -> str:
    line = (err.splitlines() or ["без пояснений"])[-1]
    return f"Не получилось: {line[:200]}"


def ago(stamp: int) -> str:
    """Последнее подключение словами."""
    if not stamp:
        return "ни разу не подключалось"
    sec = max(0, int(time.time()) - stamp)
    if sec < 180:
        return "на связи сейчас"
    if sec < 3600:
        return f"подключалось {sec // 60} мин назад"
    if sec < 86400:
        return f"подключалось {sec // 3600} ч назад"
    return f"подключалось {sec // 86400} дн назад"


def size(n: int) -> str:
    for unit, step in (("ГБ", 1024 ** 3), ("МБ", 1024 ** 2), ("КБ", 1024)):
        if n >= step:
            return f"{n / step:.1f}".replace(".", ",") + " " + unit
    return f"{n} Б"


async def devices() -> tuple[list[dict], str]:
    code, out, err = await _vpn("peers")
    if code != 0:
        return [], _problem(err)
    found = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < 6:
            continue
        name, ip, _key, rx, tx, shake = parts[:6]
        found.append({"name": name, "ip": ip.split("/")[0], "seen": ago(int(shake or 0)),
                      "online": bool(int(shake or 0)) and time.time() - int(shake) < 180,
                      "traffic": f"получено {size(int(rx or 0))}, отправлено {size(int(tx or 0))}",
                      "known": NAME_RE.match(name) is not None})
    return found, ""


def device_name(raw: str) -> str:
    """Имя устройства латиницей: «Телефон мамы» → telefon-mamy."""
    low = "".join(_LAT.get(ch, ch) for ch in raw.lower())
    return re.sub(r"[^a-z0-9]+", "-", low).strip("-")[:32].strip("-")


async def config_text(name: str) -> str | None:
    if not NAME_RE.match(name):
        return None
    code, out, _ = await _vpn("config", name)
    return out if code == 0 and "[Interface]" in out else None


def _sess_ok(request: Request, csrf: str | None = None):
    sess = current(request)
    if not sess or sess["locked"]:
        return None
    if csrf is not None and not csrf_ok(request, sess, csrf):
        return None
    return sess


def to_device(request: Request, name: str, tail: str = "") -> RedirectResponse:
    return RedirectResponse(f"{request.url_for('vpn_device', name=name)}{tail}", status_code=303)


@router.get("/vpn", name="vpn")
async def vpn_page(request: Request, error: str = "", done: str = ""):
    if not _sess_ok(request):
        return guarded(request, "vpn.html", "settings")
    found, problem = await devices()
    gone = done if NAME_RE.match(done or "") else ""
    return guarded(request, "vpn.html", "settings", {"title": "VPN", "devices": found,
                                                     "error": problem or error[:200], "gone": gone})


@router.post("/vpn/new", name="vpn_new")
async def vpn_new(request: Request, name: str = Form(""), csrf: str = Form("")):
    if not _sess_ok(request, csrf):
        return to(request, "vpn")
    slug = device_name(name)
    if not slug:
        return await vpn_page(request, error="Напиши имя устройства, например «телефон»")
    found, problem = await devices()
    if problem:
        return await vpn_page(request, error=problem)
    if any(d["name"].lower() == slug.lower() for d in found):
        return await vpn_page(request, error=f"Устройство «{slug}» уже есть — возьми другое имя")
    code, out, err = await _vpn("add", slug)
    if code != 0 or "[Interface]" not in out:
        return await vpn_page(request, error=_problem(err))
    return to_device(request, slug, "?new=1")


@router.get("/vpn/d/{name}", name="vpn_device")
async def vpn_device(request: Request, name: str, new: str = ""):
    if not _sess_ok(request):
        return guarded(request, "vpn_device.html", "settings")
    found, problem = await devices()
    device = next((d for d in found if d["name"] == name), None)
    if not device:
        return RedirectResponse(request.url_for("vpn"), status_code=303)
    has_file = await config_text(name) is not None
    resp = guarded(request, "vpn_device.html", "settings",
                   {"title": f"VPN — {name}", "device": device, "fresh": bool(new),
                    "has_file": has_file, "error": problem})
    resp.headers.update(SECRET_HEADERS)
    return resp


@router.get("/vpn/d/{name}/qr.svg", name="vpn_qr")
async def vpn_qr(request: Request, name: str):
    if not _sess_ok(request):
        return Response(status_code=403)
    text = await config_text(name)
    if text is None:
        return Response(status_code=404)
    try:
        code, svg, _ = await _run(config.QR_BIN, "-t", "SVG", "-l", "M", "-m", "2", "-o", "-",
                                  data=text.encode())
    except OSError:
        return Response(status_code=500)
    if code != 0:
        return Response(status_code=500)
    return Response(svg, media_type="image/svg+xml",
                    headers={**SECRET_HEADERS, "Content-Security-Policy": "sandbox"})


@router.get("/vpn/d/{name}/file", name="vpn_file")
async def vpn_file(request: Request, name: str):
    if not _sess_ok(request):
        return Response(status_code=403)
    text = await config_text(name)
    if text is None:
        return Response(status_code=404)
    return Response(text, media_type="application/octet-stream",
                    headers={**SECRET_HEADERS, "Content-Security-Policy": "sandbox",
                             "Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}.conf"})


@router.post("/vpn/d/{name}/remove", name="vpn_remove")
async def vpn_remove(request: Request, name: str, csrf: str = Form("")):
    if not _sess_ok(request, csrf) or not NAME_RE.match(name):
        return to(request, "vpn")
    code, _, err = await _vpn("remove", name)
    if code != 0:
        return RedirectResponse(f"{request.url_for('vpn')}?error={quote(_problem(err))}", status_code=303)
    return RedirectResponse(f"{request.url_for('vpn')}?done={quote(name)}", status_code=303)
