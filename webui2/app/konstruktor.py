"""Конструктор 3D-моделей: редактор и его хранилище под входом сайта.

Страницы редактора лежат в 3d/konstruktor/redaktor/public и не знают, где живут:
те же адреса `api/…` отдаёт и этот модуль, и серверная часть для Cloudflare
(3d/konstruktor/redaktor/src/worker.js) — переезд не трогает страницы.
Внешнего ИИ здесь нет: модели составляет Claude в «Проектах», готовый файл
загружается в редактор. Хранилище — обычные файлы, вне папки проекта."""
import asyncio
import json
import re
import shutil
import subprocess
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from PIL import Image, ImageOps
from pillow_heif import register_heif_opener

from . import chat, claude, config, db, projects
from .web import current, here, page, same_origin, to

register_heif_opener()

PUBLIC = (config.PROJECT_DIR.parent / "3d/konstruktor/redaktor/public").resolve()
MEMO = PUBLIC.parent.parent / "pamyatka-modeli.md"
# Хранилище — папка проекта «3D-модели»: так Claude в окне чата правит те же файлы,
# что показывает редактор. modeli/ — описания, foto/ — материалы, eksporty/ — просмотрщики,
# .meta/ — служебное редактора (материалы, история, разговор модели).
DATA = config.PROJECTS_DIR / config.MODELS_SLUG
VIEWER_URL = "https://mokeevasky.ru/glavpryg/model-3d/parashyutnaya-sistema/"

MAX_PHOTO = 5 * 1024 * 1024
MAX_STORED = 100
MAX_EXPORT = 10 * 1024 * 1024
MAX_MODEL = 2 * 1024 * 1024
PHOTO_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif"}
ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
AI_OFF = "Создание через внешний ИИ выключено. Модель делается в «Проектах», готовый файл загружается в редактор."
SAMPLES = ("parashyut", "samolet")
TMP = DATA / ".meta" / "zagruzka"
TOKEN = re.compile(r"^[a-z0-9]{8,32}$")
CHUNK = 32 * 1024 * 1024
MAX_UPLOAD = 8 * 1024 * 1024 * 1024
DISK_RESERVE = 512 * 1024 * 1024         # столько оставляем серверу свободным
SIDE = 1568                              # длинная сторона снимка: больше Claude всё равно не увидит
FRAMES = 12                              # кадров из одного видео
FFMPEG_SEC = 1500
STILLS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".heic", ".heif"}
VIDEOS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm", ".3gp", ".mts", ".m2ts", ".wmv"}
KNOWN = STILLS | VIDEOS
IGNORE = "# Тяжёлое и служебное редактора\nfoto/\neksporty/\n.meta/\n"

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
    return DATA / "modeli" / f"{mid}.json"


def _meta_file(mid: str) -> Path:
    return DATA / ".meta" / f"{mid}.json"


def _meta(mid: str) -> dict:
    return _read_json(_meta_file(mid)) or {"source": None, "history": []}


def _version(mid: str) -> int:
    try:
        return _model_file(mid).stat().st_mtime_ns
    except OSError:
        return 0


def _record(mid: str, model: dict | None = None) -> dict | None:
    model = model if model is not None else _read_json(_model_file(mid))
    if not isinstance(model, dict):
        return None
    return {**_meta(mid), "model": model, "version": _version(mid)}


def ensure_project() -> dict:
    """Проект «3D-модели»: заводится сам, памятка в нём всегда свежая."""
    row = db.one("SELECT * FROM projects WHERE slug = ?", (config.MODELS_SLUG,))
    if not row:
        if (config.PROJECTS_DIR / config.MODELS_SLUG).exists():
            stamp = db.now()
            db.insert("INSERT INTO projects (name, slug, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                      ("3D-модели", config.MODELS_SLUG, str(config.PROJECTS_DIR / config.MODELS_SLUG), stamp, stamp))
        else:
            projects.create_project("3D-модели")
            _seed(config.PROJECTS_DIR / config.MODELS_SLUG)
        row = db.one("SELECT * FROM projects WHERE slug = ?", (config.MODELS_SLUG,))
    memo = Path(row["path"]) / "PAMYATKA.md"
    text = MEMO.read_text(encoding="utf-8")
    if not memo.is_file() or memo.read_text(encoding="utf-8") != text:
        memo.write_text(text, encoding="utf-8")
    return row


def _seed(path: Path) -> None:
    (path / "modeli").mkdir()
    for name in SAMPLES:
        shutil.copyfile(PUBLIC / "modeli" / f"{name}.json", path / "modeli" / f"{name}.json")
    with (path / ".gitignore").open("a", encoding="utf-8") as f:
        f.write(IGNORE)
    with (path / "CLAUDE.md").open("a", encoding="utf-8") as f:
        f.write("\n## Этот проект\nЗдесь делаются 3D-модели. Перед работой прочитай `PAMYATKA.md`.\n")
    env = claude.child_env()
    for cmd in (["add", "-A"], ["-c", "commit.gpgsign=false", "commit", "-q", "-m", "Образцы моделей"]):
        subprocess.run(["git", "-C", str(path), *cmd], check=True, capture_output=True, env=env)


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
    ensure_project()
    return _ok({"ai": False, "chat": True, "used": 0, "limit": 0, "maxPhotos": MAX_STORED, "maxPhotoMb": MAX_PHOTO >> 20,
                "maxStored": MAX_STORED, "email": "", "viewerUrl": VIEWER_URL})


@router.get("/api/models")
def models(request: Request):
    if bad := _denied(request):
        return bad
    found = []
    for path in (DATA / "modeli").glob("*.json"):
        m = _read_json(path)
        name = m.get("name") if isinstance(m, dict) else None
        found.append({"id": path.stem, "name": name or path.stem, "updated": path.stat().st_mtime})
    found.sort(key=lambda m: m["updated"], reverse=True)
    return _ok({"models": found})


@router.get("/api/models/{mid}")
def model_get(request: Request, mid: str):
    if bad := _denied(request):
        return bad
    if not ID.match(mid) or not _model_file(mid).is_file():
        return _error("Модель не найдена.", 404)
    z = _record(mid)
    return _ok(z) if z else _error("Файл модели сейчас не читается — в нём ошибка.", 409)


@router.get("/api/models/{mid}/versiya")
def model_version(request: Request, mid: str):
    if bad := _denied(request):
        return bad
    return _ok({"v": _version(mid) if ID.match(mid) else 0})


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
    _write(_model_file(mid), json.dumps(model, ensure_ascii=False, indent=2).encode("utf-8"))
    meta = _meta(mid)
    meta["history"] = [*meta.get("history", []), {"at": _now(), "kind": "save"}][-50:]
    _write_json(_meta_file(mid), meta)
    return _ok(_record(mid, model))


@router.delete("/api/models/{mid}")
def model_delete(request: Request, mid: str):
    if bad := _denied(request, write=True):
        return bad
    if not ID.match(mid):
        return _error("Неправильный id модели.")
    _model_file(mid).unlink(missing_ok=True)
    _meta_file(mid).unlink(missing_ok=True)
    shutil.rmtree(DATA / "foto" / mid, ignore_errors=True)
    for name in (f"{mid}.html", f"{mid}.json"):
        (DATA / "eksporty" / name).unlink(missing_ok=True)
    return _ok({"ok": True})


# ── Окно чата ────────────────────────────────────────────────────────────

def _conv_of(mid: str) -> dict | None:
    conv_id = _meta(mid).get("conv")
    conv = chat.conversation(conv_id) if conv_id else None
    return conv if conv and conv["project_id"] else None


@router.get("/api/chat/{mid}")
def chat_state(request: Request, mid: str):
    if bad := _denied(request):
        return bad
    if not ID.match(mid):
        return _error("Неправильный id модели.")
    conv = _conv_of(mid)
    return _ok({"conv": conv["id"] if conv else None, "csrf": current(request)["csrf"],
                "root": config.ROOT_PATH, "running": bool(conv and conv["id"] in chat.RUNS)})


@router.post("/api/chat/{mid}/start")
def chat_start(request: Request, mid: str):
    """Разговор модели заводится при первом сообщении: пустые сайт не хранит."""
    if bad := _denied(request, write=True):
        return bad
    if not ID.match(mid) or not _model_file(mid).is_file():
        return _error("Сначала сохраните модель.", 404)
    conv = _conv_of(mid)
    if conv:
        empty = not db.one("SELECT 1 FROM messages WHERE conv_id = ? LIMIT 1", (conv["id"],))
        return _ok({"conv": conv["id"], "first": empty})
    model = _read_json(_model_file(mid))
    title = (model.get("name") if isinstance(model, dict) else None) or mid
    stamp = db.now()
    # Напрямую, а не chat.new_conversation: тот убирает пустые темы, а пустой может
    # быть разговор другой модели, ещё не получивший первое сообщение
    conv_id = db.insert("INSERT INTO conversations (model, project_id, title, created_at, updated_at) "
                        "VALUES (?, ?, ?, ?, ?)", (config.TOPIC_MODEL, ensure_project()["id"], title, stamp, stamp))
    meta = _meta(mid)
    meta["conv"] = conv_id
    _write_json(_meta_file(mid), meta)
    return _ok({"conv": conv_id, "first": True})


# ── Фото и схемы ─────────────────────────────────────────────────────────

@router.post("/api/models/{mid}/materialy")
async def materials(request: Request, mid: str):
    if bad := _denied(request, write=True):
        return bad
    if not ID.match(mid):
        return _error("Неправильный id модели.")
    if not _model_file(mid).is_file():
        return _error("Сначала сохраните модель.", 404)
    body = await _json_body(request)
    if not isinstance(body, dict):
        return _error("Пустой запрос.")
    fresh = []
    for item in body.get("photos") or []:
        n = item.get("n") if isinstance(item, dict) else None
        if not isinstance(n, int):
            return _error("Неправильный номер фото.")
        meta = _read_json(DATA / "foto" / mid / f"{n}.json")
        if not meta:
            return _error(f"Фото №{n + 1} не дошло до сервера — загрузите ещё раз.")
        fresh.append({"n": n, "view": meta.get("view") or "вид не указан", "file": f"foto/{mid}/{meta['file']}"})
    meta = _meta(mid)
    source = meta.get("source") or {}
    numbers = {f["n"] for f in fresh}
    meta["source"] = {**source, "mode": body.get("mode") or source.get("mode"), "size": body.get("size") or source.get("size"),
                      "photos": [*(f for f in source.get("photos", []) if f["n"] not in numbers), *fresh]}
    _write_json(_meta_file(mid), meta)
    return _ok(_record(mid) or meta)


@router.get("/api/photos/{mid}/{n}")
def photo_get(request: Request, mid: str, n: int):
    if bad := _denied(request):
        return bad
    folder = DATA / "foto" / mid
    meta = _read_json(folder / f"{n}.json") if ID.match(mid) and n >= 0 else None
    if not meta or meta.get("type") not in PHOTO_TYPES or not (folder / meta["file"]).is_file():
        return _error("Фото не найдено.", 404)
    return FileResponse(folder / meta["file"], media_type=meta["type"], headers={"Cache-Control": "private, no-cache"})


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
    folder = DATA / "foto" / mid
    name = f"{n}.{PHOTO_TYPES[kind]}"
    _write(folder / name, data)
    _write_json(folder / f"{n}.json", {"type": kind, "file": name, "view": view[:40] or "вид не указан"})
    return _ok({"ok": True})


# ── Цифры по фото: считает сайт, а не Claude ─────────────────────────────
#
# Пропорции и главные цвета предмета Claude иначе подбирает на глаз и переделывает.
# Здесь они считаются сразу и уходят в сообщение готовыми числами — без расхода лимита.

ANALYSIS_MAX = 4                         # больше снимков в сообщение не берём: каждый — лишний текст


def _photo_numbers(path: Path) -> str | None:
    """Пропорции предмета и его главные цвета. Фон — цвет краёв снимка."""
    try:
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            im.thumbnail((160, 160))
    except OSError:
        return None
    w, h = im.size
    px = im.load()
    edge = [px[x, y] for x in range(w) for y in (0, h - 1)] + [px[x, y] for y in range(h) for x in (0, w - 1)]
    bg = tuple(sorted(c[i] for c in edge)[len(edge) // 2] for i in range(3))
    spread = sorted(sum((c[i] - bg[i]) ** 2 for i in range(3)) ** 0.5 for c in edge)[int(len(edge) * 0.8)]
    limit = max(60.0, spread * 1.3)
    inside = [(x, y) for y in range(h) for x in range(w)
              if sum((px[x, y][i] - bg[i]) ** 2 for i in range(3)) ** 0.5 > limit]
    share = len(inside) / (w * h)
    lines = []
    if 0.05 < share < 0.9:
        xs = [p[0] for p in inside]
        ys = [p[1] for p in inside]
        bw, bh = max(xs) - min(xs) + 1, max(ys) - min(ys) + 1
        lines.append(f"предмет в кадре: ширина к высоте {bw / bh:.2f}, занимает {share:.0%} снимка")
    else:
        lines.append("фон от предмета не отделился — пропорции оцени сам")
        inside = [(x, y) for y in range(h // 5, h - h // 5) for x in range(w // 5, w - w // 5)]
    sample = Image.new("RGB", (len(inside), 1))
    sample.putdata([px[x, y] for x, y in inside])
    pal = sample.quantize(colors=4, method=Image.Quantize.MEDIANCUT)
    rgb = pal.getpalette()[:12]
    counts = sorted(pal.getcolors() or [], reverse=True)
    total = sum(c for c, _ in counts) or 1
    colors = [f"#{rgb[i * 3]:02x}{rgb[i * 3 + 1]:02x}{rgb[i * 3 + 2]:02x} {c / total:.0%}"
              for c, i in counts if c / total >= 0.05]
    lines.append("главные цвета предмета: " + ", ".join(colors))
    return "; ".join(lines)


@router.post("/api/models/{mid}/analiz")
async def photo_analysis(request: Request, mid: str):
    if bad := _denied(request, write=True):
        return bad
    if not ID.match(mid):
        return _error("Неправильный id модели.")
    body = await _json_body(request)
    files = body.get("files") if isinstance(body, dict) else None
    if not isinstance(files, list):
        return _error("Пустой запрос.")
    folder = (DATA / "foto" / mid).resolve()
    picked = [f for f in files if isinstance(f, str) and f.startswith(f"foto/{mid}/")][:ANALYSIS_MAX]
    out = []
    for rel in picked:
        path = (DATA / rel).resolve()
        if path.parent != folder or not path.is_file():
            continue
        numbers = await asyncio.to_thread(_photo_numbers, path)
        if numbers:
            out.append(f"{rel}: {numbers}")
    return _ok({"text": "\n".join(out)})


# ── Готовые просмотрщики ─────────────────────────────────────────────────

# ── Архивы, видео и снимки, которые браузер сам не откроет ───────────────
#
# Файл приходит кусками: так проходит и архив больше предела одного запроса.
# Разбирает сервер: архивы всех видов сжатия, HEIC с телефона, видео любых кодеков.

@router.put("/api/arhiv/{mid}/{token}")
async def archive_chunk(request: Request, mid: str, token: str, offset: int = 0):
    if bad := _denied(request, write=True):
        return bad
    if not ID.match(mid) or not TOKEN.match(token):
        return _error("Неправильный запрос.")
    TMP.mkdir(parents=True, exist_ok=True)
    for old in TMP.iterdir():
        if time.time() - old.stat().st_mtime > 3 * 86400:
            shutil.rmtree(old, ignore_errors=True) if old.is_dir() else old.unlink(missing_ok=True)
    path = TMP / token
    have = path.stat().st_size if path.exists() else 0
    if offset != have:
        # Браузер продолжит с того места, где оборвалось: связь, перезагрузка страницы
        return JSONResponse({"error": "Загрузка сбилась — приложите файл ещё раз.", "have": have}, 409,
                            headers={"Cache-Control": "no-store"})
    data = await _body(request, CHUNK)
    if data is None:
        return _error("Слишком большой кусок файла.")
    room = shutil.disk_usage(TMP).free - DISK_RESERVE
    if have + len(data) > MAX_UPLOAD or len(data) > room:
        path.unlink(missing_ok=True)
        return _error(f"Файл слишком большой: на сервере есть место примерно на {max(room, 0) >> 30} ГБ.")
    with path.open("ab") as f:
        f.write(data)
    return _ok({"have": have + len(data)})


def _save_jpeg(mid: str, n: int, jpeg: Path, view: str) -> dict:
    folder = DATA / "foto" / mid
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{n}.jpg"
    shutil.move(str(jpeg), folder / name)
    view = view[:40]
    _write_json(folder / f"{n}.json", {"type": "image/jpeg", "file": name, "view": view})
    return {"n": n, "view": view, "file": f"foto/{mid}/{name}"}


def _image_to_jpeg(src: Path, out: Path) -> bool:
    try:
        with Image.open(src) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            im.thumbnail((SIDE, SIDE))
            im.save(out, "JPEG", quality=85)
        return True
    except (OSError, ValueError, Image.DecompressionBombError):
        return False


def _duration(src: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(src)],
                       capture_output=True, text=True, timeout=120)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def _video_frames(src: Path, out: Path, count: int) -> list[Path]:
    """Кадры равномерно по длине видео. Claude смотрит снимки, видео ему не показать."""
    out.mkdir()
    length = _duration(src)
    if length <= 0:
        return []
    size = f"scale='if(gt(iw,ih),min({SIDE},iw),-2)':'if(gt(iw,ih),-2,min({SIDE},ih))'"
    subprocess.run(["nice", "-n", "15", "ffmpeg", "-v", "error", "-nostdin", "-threads", "2", "-i", str(src),
                    "-vf", f"fps={count / length:.6f},{size}", "-frames:v", str(count), "-q:v", "3",
                    str(out / "k%03d.jpg")], capture_output=True, timeout=FFMPEG_SEC)
    return sorted(out.glob("k*.jpg"))


def _unpack(path: Path, out: Path) -> list[Path]:
    """Из архива — только снимки и видео, без папок: имя с «../» никуда не уведёт."""
    with zipfile.ZipFile(path) as z:
        wanted = [i for i in z.infolist() if not i.is_dir() and not i.filename.startswith("__MACOSX/")
                  and Path(i.filename).suffix.lower() in KNOWN]
        if any(i.flag_bits & 1 for i in wanted):
            raise ValueError("Архив с паролем: снимите пароль и загрузите снова.")
        need = sum(i.file_size for i in wanted)
    if need > shutil.disk_usage(TMP).free - DISK_RESERVE:
        raise ValueError(f"Для распаковки не хватает места на сервере: нужно {need >> 30} ГБ. Разбейте архив на части.")
    out.mkdir()
    keep = [f"-ir!*{ext}" for ext in KNOWN] + [f"-ir!*{ext.upper()}" for ext in KNOWN]
    subprocess.run(["nice", "-n", "15", "7z", "e", "-y", "-aou", "-p-", f"-o{out}", str(path), *keep, "-xr!__MACOSX"],
                   capture_output=True, timeout=FFMPEG_SEC)
    return sorted(out.iterdir(), key=lambda p: p.name)


def _parse(mid: str, path: Path, name: str, first: int) -> dict:
    """Разложить файл на снимки для модели. first — первый свободный номер."""
    work = TMP / f"{path.name}.d"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir()
    skipped: list[str] = []
    try:
        if zipfile.is_zipfile(path):
            try:
                files = _unpack(path, work / "a")
            except zipfile.BadZipFile as exc:
                raise ValueError("Архив повреждён или это не ZIP.") from exc
            with zipfile.ZipFile(path) as z:
                skipped = [Path(i.filename).name for i in z.infolist() if not i.is_dir()
                           and not i.filename.startswith("__MACOSX/") and not Path(i.filename).name.startswith(".")
                           and Path(i.filename).suffix.lower() not in KNOWN]
        else:
            local = work / Path(name).name
            shutil.move(str(path), local)
            if local.suffix.lower() not in KNOWN:
                raise ValueError(f"«{name}» — не снимок, не видео и не архив ZIP.")
            files = [local]
        photos: list[dict] = []
        n = first
        for src in (f for f in files if f.suffix.lower() in STILLS):
            if n >= MAX_STORED:
                skipped.append(src.name)
                continue
            jpeg = work / f"o{n}.jpg"
            if _image_to_jpeg(src, jpeg):
                photos.append(_save_jpeg(mid, n, jpeg, src.stem))
                n += 1
            else:
                skipped.append(src.name)
        for src in (f for f in files if f.suffix.lower() in VIDEOS):
            room = min(FRAMES, MAX_STORED - n)
            frames = _video_frames(src, work / f"v{n}", room) if room > 0 else []
            if not frames:
                skipped.append(src.name)
            for i, frame in enumerate(frames, 1):
                photos.append(_save_jpeg(mid, n, frame, f"{src.stem[:28]}, кадр {i}"))
                n += 1
            src.unlink(missing_ok=True)                  # место на диске нужно следующим видео
        return {"photos": photos, "skipped": skipped}
    finally:
        shutil.rmtree(work, ignore_errors=True)
        path.unlink(missing_ok=True)


@router.post("/api/arhiv/{mid}/{token}/razobrat")
async def archive_parse(request: Request, mid: str, token: str, name: str = ""):
    if bad := _denied(request, write=True):
        return bad
    if not ID.match(mid) or not TOKEN.match(token) or not (TMP / token).is_file():
        return _error("Файл не дошёл до сервера — приложите его ещё раз.")
    if not _model_file(mid).is_file():
        return _error("Сначала сохраните модель.", 404)
    meta = _meta(mid)
    source = meta.get("source") or {}
    used = [f["n"] for f in source.get("photos", [])]
    first = max(used, default=-1) + 1
    if first >= MAX_STORED:
        (TMP / token).unlink(missing_ok=True)
        return _error(f"К одной модели — не больше {MAX_STORED} фото.")
    try:
        done = await asyncio.to_thread(_parse, mid, TMP / token, name or "файл", first)
    except ValueError as exc:
        return _error(str(exc))
    except (OSError, subprocess.SubprocessError):
        return _error("Не получилось разобрать файл.")
    meta = _meta(mid)
    source = meta.get("source") or {}
    meta["source"] = {**source, "photos": [*source.get("photos", []), *done["photos"]]}
    _write_json(_meta_file(mid), meta)
    return _ok({**done, "zapis": _record(mid)})


@router.get("/api/exports")
def exports(request: Request):
    if bad := _denied(request):
        return bad
    found = []
    for path in (DATA / "eksporty").glob("*.json"):
        meta = _read_json(path)
        if meta:
            found.append({"id": path.stem, **meta})
    found.sort(key=lambda e: str(e.get("updated")), reverse=True)
    return _ok({"exports": found})


@router.get("/api/exports/{mid}")
def export_get(request: Request, mid: str):
    if bad := _denied(request):
        return bad
    path = DATA / "eksporty" / f"{mid}.html"
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
    _write(DATA / "eksporty" / f"{mid}.html", data)
    _write_json(DATA / "eksporty" / f"{mid}.json", {"name": name[:200] or mid, "size": len(data), "updated": _now()})
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


