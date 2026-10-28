"""Файлы проекта: папка downloads/ — список, загрузка, просмотр, скачивание.

Отдаётся только то, что лежит прямо в downloads/: без скрытых файлов, ссылок
и выхода из папки. Скачивание — с Content-Security-Policy: sandbox, чтобы
файл из проекта не исполнился как страница сайта."""
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from fastapi import Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

from . import config, markup
from .projects import project, router
from .web import csrf_ok, current, guarded, page, same_origin, short_time, templates, to

UPLOAD_LIMIT = 512 * 1024 * 1024
VIEW_LIMIT = 2 * 1024 * 1024          # больше — только скачать
CHUNK = 1024 * 1024
TEXT_EXT = {".md", ".txt", ".csv", ".tsv", ".json", ".xml", ".yml", ".yaml", ".toml", ".ini", ".log",
            ".py", ".js", ".ts", ".css", ".html", ".htm", ".sh", ".sql", ".php", ".svg"}
SANDBOX = {"Content-Security-Policy": "sandbox", "X-Content-Type-Options": "nosniff",
           "Cache-Control": "no-store"}
MESSAGES = {"ok": "Загружено", "big": "Файл больше 512 МБ — не загружен", "none": "Файл не выбран",
            "fail": "Не загрузилось — попробуй ещё раз"}

templates.env.globals["fname_url"] = lambda name: quote(name, safe="")


def folder(proj: dict) -> Path:
    return Path(proj["path"]) / "downloads"


def human_size(size: float) -> str:
    if size < 1024:
        return f"{int(size)} Б"
    for unit in ("КБ", "МБ", "ГБ"):
        size /= 1024
        if size < 1024 or unit == "ГБ":
            return (f"{size:.1f}" if size < 10 else f"{size:.0f}").replace(".", ",") + f" {unit}"
    return ""


def _visible(path: Path) -> bool:
    return not path.name.startswith(".") and not path.is_symlink() and path.is_file()


def list_files(proj: dict) -> list[dict]:
    """Файлы прямо в downloads/, новые сверху."""
    base = folder(proj)
    if not base.is_dir() or base.is_symlink():
        return []
    items = []
    for path in base.iterdir():
        if _visible(path):
            st = path.stat()
            stamp = datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat()
            items.append({"name": path.name, "size": human_size(st.st_size), "mtime": st.st_mtime,
                          "time": short_time(stamp), "text": is_text(path)})
    return sorted(items, key=lambda f: (-f["mtime"], f["name"]))


def is_text(path: Path) -> bool:
    if path.suffix.lower() in TEXT_EXT:
        return True
    try:
        with path.open("rb") as fh:
            head = fh.read(8192)
        head.decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    return b"\0" not in head and bool(head)


def find(proj: dict, name: str) -> Path | None:
    """Файл по имени — только прямо в downloads/."""
    if not name or "/" in name or "\\" in name or "\0" in name or name.startswith("."):
        return None
    base = folder(proj)
    path = base / name
    if base.is_symlink() or not _visible(path) or path.resolve().parent != base.resolve():
        return None
    return path


def clean_name(raw: str) -> str:
    """Имя загружаемого файла: без пути, управляющих знаков и точек в начале."""
    name = raw.replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(ch for ch in name if ch.isprintable()).strip().lstrip(".").strip()
    while len(name.encode()) > 200:
        stem, dot, ext = name.rpartition(".")
        name = (stem[:-1] + dot + ext) if dot and len(ext) < 10 and stem else name[:-1]
    return name or "файл"


def place(tmp: Path, name: str) -> str:
    """Положить загруженное под свободным именем: занято — «имя (2)»."""
    stem, suffix = Path(name).stem, Path(name).suffix
    n = 1
    while True:
        target = name if n == 1 else f"{stem} ({n}){suffix}"
        try:
            os.link(tmp, tmp.parent / target)      # не затирает: занято — ошибка
            return target
        except FileExistsError:
            n += 1


def files_ctx(proj: dict, request: Request) -> dict:
    code = request.query_params.get("f", "")
    return {"project": proj, "files": list_files(proj), "files_msg": MESSAGES.get(code, ""),
            "files_ok": code == "ok"}


@router.get("/projects/{pid}/files", name="files")
def files_page(request: Request, pid: int):
    if not current(request):
        return to(request, "login_form")
    proj = project(pid)
    if not proj:
        return to(request, "projects")
    return guarded(request, "files.html", "projects", {"title": f"Файлы — {proj['name']}",
                                                         **files_ctx(proj, request)})


@router.get("/projects/{pid}/files/list", name="files_list")
def files_list(request: Request, pid: int):
    sess = current(request)
    proj = project(pid)
    if not sess or sess["locked"] or not proj:
        return JSONResponse({"error": "нет доступа"}, status_code=403)
    html = page(request, "_files.html", {"sess": sess, **files_ctx(proj, request)}).body.decode()
    return JSONResponse({"html": html}, headers={"Cache-Control": "no-store"})


def _back(pid: int, back: str, code: str, request: Request):
    if request.headers.get("x-upload") == "1":
        return JSONResponse({"ok": code == "ok", "message": MESSAGES[code]},
                            status_code=200 if code == "ok" else 400)
    own = f"{config.ROOT_PATH}/projects/{pid}"
    path = back if back == own or back.startswith(own + "/") else own + "/files"
    return RedirectResponse(f"{path}?f={code}#files", status_code=303)


@router.post("/projects/{pid}/files/upload", name="files_upload")
async def files_upload(request: Request, pid: int):
    sess = current(request)
    proj = project(pid)
    # Вход и адрес страницы — до чтения тела: чужой запрос не займёт диск
    if not sess or sess["locked"] or not proj or not same_origin(request):
        return JSONResponse({"error": "нет доступа"}, status_code=403)
    if int(request.headers.get("content-length") or 0) > UPLOAD_LIMIT + CHUNK:
        return _back(pid, "", "big", request)
    try:
        form = await request.form(max_files=50)
    except Exception:                                   # noqa: BLE001
        return _back(pid, "", "fail", request)
    back = str(form.get("back") or "")
    try:
        if not csrf_ok(request, sess, str(form.get("csrf") or "")):
            return JSONResponse({"error": "нет доступа"}, status_code=403)
        uploads = [f for f in form.getlist("files") if getattr(f, "filename", None)]
        if not uploads:
            return _back(pid, back, "none", request)
        base = folder(proj)
        base.mkdir(exist_ok=True)
        if base.is_symlink():
            return _back(pid, back, "fail", request)
        for up in uploads:
            tmp = base / f".upload-{secrets.token_hex(8)}"
            size = 0
            try:
                with tmp.open("xb") as out:
                    while chunk := await up.read(CHUNK):
                        size += len(chunk)
                        if size > UPLOAD_LIMIT:
                            return _back(pid, back, "big", request)
                        out.write(chunk)
                place(tmp, clean_name(up.filename))
            finally:
                tmp.unlink(missing_ok=True)
    except OSError:
        return _back(pid, back, "fail", request)
    finally:
        await form.close()
    return _back(pid, back, "ok", request)


@router.get("/projects/{pid}/files/view/{name}", name="file_view")
def file_view(request: Request, pid: int, name: str):
    if not current(request):
        return to(request, "login_form")
    proj = project(pid)
    path = find(proj, name) if proj else None
    if not path:
        return to(request, "projects") if not proj else RedirectResponse(
            f"{config.ROOT_PATH}/projects/{pid}/files", status_code=303)
    ctx = {"title": name, "project": proj, "name": name, "html": None, "text": None,
           "too_big": path.stat().st_size > VIEW_LIMIT, "is_text": is_text(path)}
    if ctx["is_text"] and not ctx["too_big"]:
        content = path.read_text(encoding="utf-8", errors="replace")
        if path.suffix.lower() == ".md":
            ctx["html"] = markup.render(content)
        else:
            ctx["text"] = content
    return guarded(request, "file_view.html", "projects", ctx)


@router.get("/projects/{pid}/files/get/{name}", name="file_get")
def file_get(request: Request, pid: int, name: str):
    sess = current(request)
    if not sess:
        return to(request, "login_form")
    proj = project(pid)
    path = find(proj, name) if proj and not sess["locked"] else None
    if not path:
        return JSONResponse({"error": "нет такого файла"}, status_code=404, headers=SANDBOX)
    return FileResponse(path, filename=name, headers=SANDBOX,
                        media_type="application/octet-stream")
