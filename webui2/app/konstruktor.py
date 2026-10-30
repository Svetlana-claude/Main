"""Конструктор 3D-моделей: редактор и его хранилище под входом сайта.

Страницы редактора лежат в 3d/konstruktor/redaktor/public и не знают, где живут:
те же адреса `api/…` отдаёт и этот модуль, и серверная часть для Cloudflare
(3d/konstruktor/redaktor/src/worker.js) — переезд не трогает страницы.
Внешнего ИИ здесь нет: модели составляет Claude в «Проектах», готовый файл
загружается в редактор. Хранилище — обычные файлы, вне папки проекта."""
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response

from . import config
from .web import current, here, page, same_origin, to

PUBLIC = (config.PROJECT_DIR.parent / "3d/konstruktor/redaktor/public").resolve()
DATA = Path(os.environ.get("KONSTRUKTOR3D_DIR", Path.home() / ".local/share/konstruktor3d"))
VIEWER_URL = "https://mokeevasky.ru/glavpryg/model-3d/parashyutnaya-sistema/"

MAX_PHOTO = 5 * 1024 * 1024
MAX_STORED = 40
MAX_EXPORT = 10 * 1024 * 1024
MAX_MODEL = 2 * 1024 * 1024
PHOTO_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
AI_OFF = "Создание через внешний ИИ выключено. Модель делается в «Проектах», готовый файл загружается в редактор."

router = APIRouter(prefix="/3d")


def _error(text: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": text}, status, headers={"Cache-Control": "no-store"})


def _ok(data) -> JSONResponse:
    return JSONResponse(data, headers={"Cache-Control": "no-store"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _write(path: Path, data: bytes) -> None:
    """Запись целиком: оборвавшаяся не оставит половины файла."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def _write_json(path: Path, value) -> None:
    _write(path, json.dumps(value, ensure_ascii=False).encode("utf-8"))


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _model_file(mid: str) -> Path:
    return DATA / "models" / f"{mid}.json"


def _denied(request: Request, write: bool = False) -> JSONResponse | None:
    """Адреса хранилища: только после входа, не под замком и со своих страниц."""
    sess = current(request)
    if not sess:
        return _error("Вход истёк — обновите страницу и войдите снова.", 403)
    if sess["locked"]:
        return _error("Сайт закрыт замком — обновите страницу.", 403)
    if write and not same_origin(request):
        return _error("Запрос не со страницы редактора.", 403)
    return None


async def _body(request: Request, limit: int) -> bytes | None:
    """Тело запроса, но не больше предела: заголовку о длине верим только на отказ."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        return None
    got = bytearray()
    async for chunk in request.stream():
        got += chunk
        if len(got) > limit:
            return None
    return bytes(got)


async def _json_body(request: Request):
    raw = await _body(request, MAX_MODEL)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


@router.get("", include_in_schema=False)
def bare(request: Request):
    return RedirectResponse(here(request) + "/", status_code=307)


# ── Модели ───────────────────────────────────────────────────────────────

@router.get("/api/status")
def status(request: Request):
    if bad := _denied(request):
        return bad
    return _ok({"ai": False, "used": 0, "limit": 0, "maxPhotos": MAX_STORED, "maxPhotoMb": MAX_PHOTO >> 20,
                "maxStored": MAX_STORED, "email": "", "viewerUrl": VIEWER_URL})


@router.get("/api/models")
def models(request: Request):
    if bad := _denied(request):
        return bad
    found = []
    for path in (DATA / "models").glob("*.json"):
        z = _read_json(path)
        if z:
            found.append({"id": path.stem, "name": z["model"].get("name"), "updated": z.get("updated")})
    found.sort(key=lambda m: str(m["updated"]), reverse=True)
    return _ok({"models": found})


@router.get("/api/models/{mid}")
def model_get(request: Request, mid: str):
    if bad := _denied(request):
        return bad
    z = _read_json(_model_file(mid)) if ID.match(mid) else None
    return _ok(z) if z else _error("Модель не найдена.", 404)


@router.put("/api/models/{mid}")
async def model_put(request: Request, mid: str):
    if bad := _denied(request, write=True):
        return bad
    if not ID.match(mid):
        return _error("Неправильный id модели: только латиница, цифры и дефис.")
    body = await _json_body(request)
    model = body.get("model") if isinstance(body, dict) else None
    # Полная проверка формата — в браузере, общая с движком (format.js)
    if not isinstance(model, dict) or not model.get("name") or not isinstance(model.get("parts"), list):
        return _error("Это не описание модели.")
    model["id"] = mid
    z = _read_json(_model_file(mid)) or {"source": None, "history": []}
    z["model"] = model
    z["updated"] = _now()
    z["history"] = [*z.get("history", []), {"at": z["updated"], "kind": "save"}][-50:]
    _write_json(_model_file(mid), z)
    return _ok(z)


@router.delete("/api/models/{mid}")
def model_delete(request: Request, mid: str):
    if bad := _denied(request, write=True):
        return bad
    if not ID.match(mid):
        return _error("Неправильный id модели.")
    _model_file(mid).unlink(missing_ok=True)
    for path in (DATA / "photos" / mid).glob("*") if (DATA / "photos" / mid).is_dir() else ():
        path.unlink()
    for name in (f"{mid}.html", f"{mid}.json"):
        (DATA / "exports" / name).unlink(missing_ok=True)
    return _ok({"ok": True})


# ── Фото и схемы ─────────────────────────────────────────────────────────

@router.post("/api/models/{mid}/materialy")
async def materials(request: Request, mid: str):
    if bad := _denied(request, write=True):
        return bad
    if not ID.match(mid):
        return _error("Неправильный id модели.")
    z = _read_json(_model_file(mid))
    if not z:
        return _error("Сначала сохраните модель.", 404)
    body = await _json_body(request)
    if not isinstance(body, dict):
        return _error("Пустой запрос.")
    fresh = []
    for item in body.get("photos") or []:
        n = item.get("n") if isinstance(item, dict) else None
        if not isinstance(n, int):
            return _error("Неправильный номер фото.")
        meta = _read_json(DATA / "photos" / mid / f"{n}.json")
        if not meta:
            return _error(f"Фото №{n + 1} не дошло до сервера — загрузите ещё раз.")
        fresh.append({"n": n, "view": meta.get("view") or "вид не указан"})
    source = z.get("source") or {}
    numbers = {f["n"] for f in fresh}
    z["source"] = {**source, "mode": body.get("mode") or source.get("mode"), "size": body.get("size") or source.get("size"),
                   "photos": [*(f for f in source.get("photos", []) if f["n"] not in numbers), *fresh]}
    z["updated"] = _now()
    _write_json(_model_file(mid), z)
    return _ok(z)


@router.get("/api/photos/{mid}/{n}")
def photo_get(request: Request, mid: str, n: int):
    if bad := _denied(request):
        return bad
    folder = DATA / "photos" / mid
    meta = _read_json(folder / f"{n}.json") if ID.match(mid) and n >= 0 else None
    if not meta or meta.get("type") not in PHOTO_TYPES or not (folder / str(n)).is_file():
        return _error("Фото не найдено.", 404)
    return FileResponse(folder / str(n), media_type=meta["type"], headers={"Cache-Control": "private, no-cache"})


@router.put("/api/photos/{mid}/{n}")
async def photo_put(request: Request, mid: str, n: int, view: str = ""):
    if bad := _denied(request, write=True):
        return bad
    if not ID.match(mid) or n < 0:
        return _error("Неправильный id модели.")
    if n >= MAX_STORED:
        return _error(f"К одной модели — не больше {MAX_STORED} фото.")
    kind = request.headers.get("content-type", "")
    if kind not in PHOTO_TYPES:
        return _error("Можно загружать только картинки: JPEG, PNG, WebP.")
    data = await _body(request, MAX_PHOTO)
    if data is None:
        return _error(f"Фото больше {MAX_PHOTO >> 20} МБ — уменьшите его.")
    if not data:
        return _error("Пустой файл.")
    folder = DATA / "photos" / mid
    _write(folder / str(n), data)
    _write_json(folder / f"{n}.json", {"type": kind, "view": view[:40] or "вид не указан"})
    return _ok({"ok": True})


# ── Готовые просмотрщики ─────────────────────────────────────────────────

@router.get("/api/exports")
def exports(request: Request):
    if bad := _denied(request):
        return bad
    found = []
    for path in (DATA / "exports").glob("*.json"):
        meta = _read_json(path)
        if meta:
            found.append({"id": path.stem, **meta})
    found.sort(key=lambda e: str(e.get("updated")), reverse=True)
    return _ok({"exports": found})


@router.get("/api/exports/{mid}")
def export_get(request: Request, mid: str):
    if bad := _denied(request):
        return bad
    path = DATA / "exports" / f"{mid}.html"
    if not ID.match(mid) or not path.is_file():
        return _error("Экспорт не найден.", 404)
    # Только скачиванием: чужая страница не должна открываться на адресе сайта
    return FileResponse(path, media_type="application/octet-stream", filename=f"{mid}.html",
                        headers={"Cache-Control": "no-store"})


@router.put("/api/exports/{mid}")
async def export_put(request: Request, mid: str, name: str = ""):
    if bad := _denied(request, write=True):
        return bad
    if not ID.match(mid):
        return _error("Неправильный id модели.")
    if not request.headers.get("content-type", "").startswith("text/html"):
        return _error("Экспорт — это страница HTML.")
    data = await _body(request, MAX_EXPORT)
    if not data:
        return _error("Экспорт пустой или больше 10 МБ.")
    _write(DATA / "exports" / f"{mid}.html", data)
    _write_json(DATA / "exports" / f"{mid}.json", {"name": name[:200] or mid, "size": len(data), "updated": _now()})
    return _ok({"ok": True})


@router.post("/api/generate")
@router.post("/api/refine")
def ai_off(request: Request):
    return _denied(request, write=True) or _error(AI_OFF)


@router.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "DELETE"])
def api_unknown(request: Request, rest: str):
    return _denied(request) or _error("Нет такой функции.", 404)


# ── Страницы редактора ───────────────────────────────────────────────────

@router.get("/{path:path}")
def files(request: Request, path: str):
    sess = current(request)
    if not sess:
        return to(request, "login_form")
    if sess["locked"]:
        return page(request, "lock.html", {"sess": sess, "back": here(request)})
    target = (PUBLIC / (path or "index.html")).resolve()
    if not target.is_relative_to(PUBLIC) or not target.is_file():
        return Response("Нет такой страницы", 404, media_type="text/plain; charset=utf-8")
    return FileResponse(target, headers={"Cache-Control": "no-cache", "X-Robots-Tag": "noindex, nofollow"})


