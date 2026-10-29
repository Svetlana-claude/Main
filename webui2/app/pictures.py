"""Картинки: одна галерея на все проекты — проект → папка → кадры.

Картинки ищутся в папках проектов на диске. Не показывается и не отдаётся:
скрытое (имя с точки), ссылки, служебные папки (git, окружения питона,
node_modules…), папки самого сайта, файлы вроде .env и ключей.

Снаружи приходит не путь, а ключ «номер проекта/путь внутри»; путь
проверяется после resolve() на попадание внутрь папки проекта и проходит те
же правила, что и обход, — что не видно в сетке, то и по адресу не отдаётся.
Уменьшенные копии делаются один раз и лежат в config.THUMB_DIR (вне проектов).
"""
import hashlib
import os
import stat
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse

from . import config, db
from .web import current, guarded

router = APIRouter()

RASTER = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".ico"}
VECTOR = {".svg"}
IMAGES = RASTER | VECTOR
SKIP_DIRS = {"node_modules", "__pycache__", "venv", "site-packages", "dist", "build"}
SKIP_SUFFIXES = {".key", ".pem"}
MAX_IMAGES = 4000
MAX_DEPTH = 12
THUMB_MAX = 480
# Картинка и превью меняются редко; у превью адрес зависит от времени правки
CACHE = {"Cache-Control": "private, max-age=604800", "X-Content-Type-Options": "nosniff"}
# Открытый напрямую SVG не должен исполнить свой скрипт как страница сайта
SANDBOX = {**CACHE, "Content-Security-Policy": "sandbox"}


def _projects() -> dict[int, dict]:
    out = {}
    for p in db.rows("SELECT id, name, path FROM projects WHERE delete_state = '' ORDER BY lower(name)"):
        path = Path(p["path"])
        if path.is_dir() and not path.is_symlink():
            out[p["id"]] = {"id": p["id"], "name": p["name"], "root": path.resolve()}
    return out


def _site_dirs() -> list[Path]:
    """Папка кода сайта: её картинки — не её работа (база и ключи лежат в
    скрытых папках, туда обход и так не заходит)."""
    return [config.PROJECT_DIR.resolve()]


def _closed_dir(path: Path, name: str) -> bool:
    if name.startswith(".") or name in SKIP_DIRS or (path / "pyvenv.cfg").exists():
        return True
    real = path.resolve()
    return any(real == d or real.is_relative_to(d) for d in _site_dirs())


def _closed_file(name: str) -> bool:
    low = name.lower()
    return (name.startswith(".") or Path(low).suffix in SKIP_SUFFIXES
            or Path(low).suffix not in IMAGES)


def _item(src: str, name: str, info: os.stat_result) -> dict:
    return {"src": src, "name": name, "size": info.st_size,
            "mtime": datetime.fromtimestamp(info.st_mtime, timezone.utc).isoformat()}


def _walk(proj: dict, budget: int) -> tuple[dict[str, list], int]:
    folders: dict[str, list] = {}
    used = 0
    root = proj["root"]
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        here = Path(dirpath)
        rel = here.relative_to(root)
        if len(rel.parts) >= MAX_DEPTH:
            dirnames[:] = []
        else:
            dirnames[:] = sorted(d for d in dirnames
                                 if not (here / d).is_symlink() and not _closed_dir(here / d, d))
        folder = rel.as_posix() if rel.parts else ""
        for name in sorted(filenames):
            if _closed_file(name):
                continue
            path = here / name
            try:
                info = path.lstat()
            except OSError:
                continue
            if not stat.S_ISREG(info.st_mode):
                continue                     # ссылки и прочее не показываются
            if used >= budget:
                return folders, used
            src = f"{proj['id']}/{folder + '/' if folder else ''}{name}"
            folders.setdefault(folder, []).append(_item(src, name, info))
            used += 1
    return folders, used


def catalog() -> dict:
    """Проекты → папки → кадры. Корень проекта первым, папки по алфавиту."""
    groups, left = [], MAX_IMAGES
    for proj in _projects().values():
        folders, used = _walk(proj, left)
        left -= used
        if not folders:
            continue
        items = [{"path": f, "title": f or "в корне проекта", "images": folders[f]}
                 for f in sorted(folders, key=lambda f: (f != "", f.lower()))]
        groups.append({"id": proj["id"], "name": proj["name"],
                       "count": sum(len(f["images"]) for f in items), "folders": items})
        if left <= 0:
            break
    return {"groups": groups, "truncated": left <= 0, "limit": MAX_IMAGES}


def resolve(src: str) -> Path | None:
    """Файл по ключу — только если его показала бы и сетка."""
    head, _, rest = src.partition("/")
    if not head.isdigit() or not rest or "\0" in rest:
        return None
    proj = _projects().get(int(head))
    if not proj:
        return None
    root = proj["root"]
    path = root / rest
    try:
        real = path.resolve()
    except (OSError, RuntimeError):
        return None
    if not real.is_relative_to(root) or real == root or real != path.absolute():
        return None                          # выход из папки или ссылка по пути
    rel = real.relative_to(root)
    if len(rel.parts) > MAX_DEPTH or _closed_file(rel.name):
        return None
    here = root
    for part in rel.parts[:-1]:
        here = here / part
        if _closed_dir(here, part):
            return None
    try:
        info = real.lstat()
    except OSError:
        return None
    return real if stat.S_ISREG(info.st_mode) else None


def _thumb(path: Path) -> Path:
    """Уменьшенная копия (webp). Имя — от пути, времени правки и размера."""
    info = path.stat()
    key = hashlib.sha1(f"{path}|{info.st_mtime_ns}|{info.st_size}|{THUMB_MAX}".encode()).hexdigest()
    target = config.THUMB_DIR / key[:2] / f"{key}.webp"
    if target.is_file():
        return target
    from PIL import Image, ImageOps
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with Image.open(path) as im:
        if im.format == "JPEG":
            im.draft("RGB", (THUMB_MAX, THUMB_MAX))
        im = ImageOps.exif_transpose(im)     # снимок с телефона не лежит боком
        if im.mode not in ("RGB", "RGBA"):
            clear = im.mode in ("PA", "LA", "La") or "transparency" in im.info
            im = im.convert("RGBA" if clear else "RGB")
        im.thumbnail((THUMB_MAX, THUMB_MAX), Image.LANCZOS)
        tmp = target.with_name(f"{key}.{os.getpid()}.part")
        im.save(tmp, "WEBP", quality=80, method=4)
    tmp.replace(target)
    return target


def _allowed(request: Request) -> bool:
    sess = current(request)
    return bool(sess) and not sess["locked"]


def _deny() -> JSONResponse:
    return JSONResponse({"error": "нет доступа"}, status_code=403)


@router.get("/pictures", name="pictures")
def pictures_page(request: Request):
    return guarded(request, "pictures.html", "pictures", {"title": "Картинки"})


@router.get("/pictures/list", name="pictures_list")
def pictures_list(request: Request):
    if not _allowed(request):
        return _deny()
    resp = JSONResponse(catalog())
    resp.headers["Cache-Control"] = "no-store"
    return resp


@router.get("/pictures/thumb", name="picture_thumb")
def picture_thumb(request: Request, src: str = ""):
    if not _allowed(request):
        return _deny()
    path = resolve(src)
    if not path:
        return JSONResponse({"error": "картинка не найдена"}, status_code=404)
    if path.suffix.lower() in VECTOR:
        return FileResponse(path, media_type="image/svg+xml", headers=SANDBOX)
    try:
        thumb = _thumb(path)
    except Exception:                        # noqa: BLE001 — битый файл: в сетке будет заглушка
        return JSONResponse({"error": "превью не сделать"}, status_code=415)
    return FileResponse(thumb, media_type="image/webp", headers=CACHE)


@router.get("/pictures/view", name="picture_view")
def picture_view(request: Request, src: str = ""):
    if not _allowed(request):
        return _deny()
    path = resolve(src)
    if not path:
        return JSONResponse({"error": "картинка не найдена"}, status_code=404)
    media = "image/svg+xml" if path.suffix.lower() in VECTOR else None
    return FileResponse(path, media_type=media, headers=SANDBOX)


@router.get("/pictures/file", name="picture_file")
def picture_file(request: Request, src: str = ""):
    if not _allowed(request):
        return _deny()
    path = resolve(src)
    if not path:
        return JSONResponse({"error": "картинка не найдена"}, status_code=404)
    return FileResponse(path, filename=path.name, headers=SANDBOX)
