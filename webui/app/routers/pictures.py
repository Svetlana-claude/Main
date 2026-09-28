"""Картинки: одна галерея на все проекты.

Раздел отвечает на вопрос «где я это видела»: снимки, макеты, превью и
присланные заказчиком кадры лежат по десятку папок, и до сих пор посмотреть их
из браузера было нечем — «Файлы проекта» показывают только папку выдачи одного
проекта и только списком имён.

Устройство:

* **источники** — рабочий каталог каждого проекта из таблицы `projects` плюс
  `exchange/` (материалы заказчика живут вне проектов, правило 10);
* **разбивка** — проект → папка внутри него. Путь папки берётся как есть,
  поэтому дерево в точности повторяет диск;
* **загруженные через форму** файлы показываются отдельной папкой проекта:
  на диске они лежат в `uploads/` под сгенерированными именами, и по ним
  ничего не узнать — имя берётся из таблицы `files`;
* **превью** делаются Pillow один раз и складываются в `.thumbs/` рядом с
  проектом: отдавать в сетку исходники по 4 МБ нельзя.

Снаружи приходит не путь, а **ключ**: `p5/app/static/knopka.png`, `x/foto.jpg`
или `up/7`. Путь из ключа проверяется на попадание внутрь своего корня после
`resolve()` — иначе `?src=p5/../../.config/webui/webui.env` отдавал бы ключи
приложения тем же способом, каким это ловится в «Файлах проекта».
"""
import hashlib
import os
import stat
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

from .. import config, db
from ..deps import current_user, render
from .projects import TREE_SKIP_DIRS, _tree_closed

router = APIRouter()

# Растр раскладывается Pillow, вектор отдаётся как есть: браузер нарисует SVG
# сам и в сетке, и в просмотрщике.
RASTER_SUFFIXES = frozenset({
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".ico",
})
VECTOR_SUFFIXES = frozenset({".svg"})
IMAGE_SUFFIXES = RASTER_SUFFIXES | VECTOR_SUFFIXES

# Куда обход не заходит. К служебному из «Файлов проекта» добавлены `uploads`
# (те же файлы приходят из таблицы под настоящими именами — иначе каждый
# показался бы дважды, и один раз бессмысленным именем) и сам склад превью.
#
# Питоновское окружение узнаётся не по имени, а по `pyvenv.cfg` внутри: в
# `exchange/pwenv` лежит установленный playwright, и его значки и картинки
# страниц отладчика заполняли галерею чужим добром — имя каталога при этом
# может быть любым.
THUMB_DIRNAME = ".thumbs"
WALK_SKIP_DIRS = TREE_SKIP_DIRS | frozenset({"uploads", "site-packages", THUMB_DIRNAME})

# Пределы обхода: страница должна открываться сразу. Упёрлись — говорим об этом
# словами, молча показанная часть выглядела бы как всё, что есть.
MAX_IMAGES = 4000
MAX_DEPTH = 12

# Превью. 480 px хватает и на крупную плитку, и на экран с двойной плотностью.
THUMB_DIR = config.PROJECT_DIR / THUMB_DIRNAME
THUMB_MAX = 480
THUMB_QUALITY = 80
THUMB_KEEP_DAYS = 30

# Превью и сами картинки браузер вправе держать у себя: файл на диске меняется
# редко, а ключ превью считается по времени изменения — правка даёт новый адрес.
CACHE_HEADERS = {"Cache-Control": "private, max-age=604800"}

# Папка проекта, которой нет на диске: файлы, загруженные через форму.
UPLOADS_FOLDER = ":uploads"
UPLOADS_TITLE = "загруженные через форму"


@dataclass(frozen=True)
class _Root:
    """Источник картинок: проект или папка обмена."""
    key: str
    name: str
    path: Path
    kind: str                    # project | exchange
    project_id: int | None


@dataclass(frozen=True)
class _Found:
    """Разобранный ключ: файл на диске и имя, под которым он показывается."""
    path: Path
    name: str


def _roots() -> dict[str, _Root]:
    """Источники по ключу. Порядок — как в перечне проектов, обмен последним."""
    roots: dict[str, _Root] = {}
    for row in db.query("SELECT id, name, workdir FROM projects ORDER BY lower(name)"):
        path = Path(row["workdir"])
        if not path.is_dir():
            continue
        key = f"p{row['id']}"
        roots[key] = _Root(key, row["name"], path.resolve(), "project", row["id"])

    exchange = config.REPO_ROOT / "exchange"
    if exchange.is_dir():
        roots["x"] = _Root("x", "Обмен", exchange.resolve(), "exchange", None)
    return roots


# ── Размеры кадра ────────────────────────────────────────────────────────
#
# Ширина и высота нужны в подписи и в просмотрщике. Pillow читает их из
# заголовка, не разбирая картинку целиком, но сотня файлов на каждое открытие
# страницы — уже заметно, поэтому ответ запоминается по времени изменения.
_DIMS: dict[tuple[str, int, int], tuple[int, int] | None] = {}
_DIMS_MAX = 8000


def _dims(path: Path, info: os.stat_result) -> tuple[int, int] | None:
    key = (str(path), info.st_mtime_ns, info.st_size)
    if key in _DIMS:
        return _DIMS[key]
    try:
        from PIL import Image
        with Image.open(path) as im:
            size = im.size
    except Exception:                                  # noqa: BLE001
        size = None                                    # битый файл или формат не тот
    if len(_DIMS) >= _DIMS_MAX:
        _DIMS.clear()
    _DIMS[key] = size
    return size


def _item(src: str, name: str, path: Path, info: os.stat_result) -> dict:
    vector = path.suffix.lower() in VECTOR_SUFFIXES
    size = None if vector else _dims(path, info)
    return {
        "src": src,
        "name": name,
        "size": info.st_size,
        "mtime": datetime.fromtimestamp(info.st_mtime, timezone.utc).isoformat(),
        "w": size[0] if size else None,
        "h": size[1] if size else None,
        "vector": vector,
    }


def _inside_env(root: Path, rel: Path) -> bool:
    """Лежит ли файл внутри питоновского окружения.

    Обход в такие каталоги не заходит, и по прямой ссылке оттуда тоже ничего
    не отдаётся: показанное в сетке и отдаваемое по адресу должны совпадать,
    иначе перечень закрытого приходится держать в двух местах.
    """
    here = root
    for part in rel.parts[:-1]:
        here = here / part
        if (here / "pyvenv.cfg").exists():
            return True
    return False


def _walk(root: _Root, folders: dict[str, list[dict]], budget: int) -> int:
    """Картинки каталога по папкам. Возвращает, сколько из бюджета израсходовано."""
    used = 0
    for dirpath, dirnames, filenames in os.walk(root.path, followlinks=False):
        here = Path(dirpath)
        rel_dir = here.relative_to(root.path)
        if len(rel_dir.parts) >= MAX_DEPTH:
            dirnames[:] = []
        else:
            dirnames[:] = sorted(
                d for d in dirnames
                if d not in WALK_SKIP_DIRS and not (here / d / "pyvenv.cfg").exists()
            )

        for name in sorted(filenames):
            if Path(name).suffix.lower() not in IMAGE_SUFFIXES or _tree_closed(name):
                continue
            path = here / name
            if path.is_symlink():
                continue                               # ссылка наружу всё равно была бы отбита
            try:
                info = path.stat()
            except OSError:
                continue                               # исчез между обходом и чтением
            if not stat.S_ISREG(info.st_mode):
                continue
            if used >= budget:
                return used
            rel = str(rel_dir).replace(os.sep, "/")
            folder = "" if rel == "." else rel
            src = f"{root.key}/{rel_dir.as_posix()}/{name}" if folder else f"{root.key}/{name}"
            folders.setdefault(folder, []).append(_item(src, name, path, info))
            used += 1
    return used


def _is_image(filename: str, mime: str | None) -> bool:
    """Картинка ли это среди загруженных через форму.

    Смотрим и на имя, и на тип: браузер присылает `application/octet-stream`
    на всё подряд, а имя загруженного файла хранится как есть.
    """
    return (Path(filename).suffix.lower() in IMAGE_SUFFIXES
            or (mime or "").startswith("image/"))


def _uploads(root: _Root, folders: dict[str, list[dict]], budget: int) -> int:
    """Загруженные через форму файлы проекта — отдельной папкой, под своими именами."""
    if root.project_id is None:
        return 0
    used = 0
    rows = db.query(
        "SELECT id, filename, stored_name, mime FROM files WHERE project_id = %s ORDER BY id",
        (root.project_id,),
    )
    for row in rows:
        if not _is_image(row["filename"], row["mime"]):
            continue
        path = config.UPLOADS_DIR / row["stored_name"]
        try:
            info = path.stat()
        except OSError:
            continue                                   # запись есть, файла нет
        if used >= budget:
            break
        folders.setdefault(UPLOADS_FOLDER, []).append(
            _item(f"up/{row['id']}", row["filename"], path, info)
        )
        used += 1
    return used


def _catalog() -> dict:
    """Всё дерево картинок: источники → папки → кадры."""
    groups = []
    left = MAX_IMAGES
    for root in _roots().values():
        folders: dict[str, list[dict]] = {}
        left -= _walk(root, folders, left)
        left -= _uploads(root, folders, left)
        if not folders:
            continue

        # Корень проекта первым, папки по алфавиту, загруженные — последними:
        # на диске их нет, и в ряду настоящих папок они сбивали бы порядок.
        def order(name: str) -> tuple:
            return (2 if name == UPLOADS_FOLDER else (0 if name == "" else 1), name.lower())

        items = []
        count = 0
        for folder in sorted(folders, key=order):
            images = folders[folder]
            count += len(images)
            items.append({
                "path": folder,
                "title": UPLOADS_TITLE if folder == UPLOADS_FOLDER else (folder or "корень"),
                "count": len(images),
                "images": images,
            })
        groups.append({
            "key": root.key,
            "name": root.name,
            "kind": root.kind,
            "dir": str(root.path),
            "count": count,
            "folders": items,
        })

    return {"groups": groups, "truncated": left <= 0, "limit": MAX_IMAGES}


# ── Разбор ключа ─────────────────────────────────────────────────────────

def _upload(raw: str) -> _Found | None:
    if not raw.isdigit():
        return None
    row = db.query_one(
        "SELECT filename, stored_name, mime FROM files WHERE id = %s", (int(raw),)
    )
    if not row or not _is_image(row["filename"], row["mime"]):
        return None
    path = (config.UPLOADS_DIR / row["stored_name"]).resolve()
    uploads = config.UPLOADS_DIR.resolve()
    # `stored_name` кладёт само приложение, но проверка дешевле уверенности
    if uploads not in path.parents or not path.is_file():
        return None
    return _Found(path, row["filename"])


def _resolve(src: str) -> _Found | None:
    """Файл по ключу из каталога — либо None.

    Здесь же решается и что отдавать по прямой ссылке: не показанное в сетке
    (служебное, `.env`, не картинка) не должно забираться подбором адреса.
    """
    prefix, _, rest = src.partition("/")
    if prefix == "up":
        return _upload(rest)

    root = _roots().get(prefix)
    if not root or not rest:
        return None
    candidate = (root.path / rest).resolve()
    # Сравнение после resolve(): и `..`, и абсолютный путь, и ссылка наружу
    # упираются в одно условие
    if root.path not in candidate.parents or not candidate.is_file():
        return None
    rel = candidate.relative_to(root.path)
    if any(part in WALK_SKIP_DIRS for part in rel.parts[:-1]) or _inside_env(root.path, rel):
        return None
    if _tree_closed(rel.name) or candidate.suffix.lower() not in IMAGE_SUFFIXES:
        return None
    return _Found(candidate, candidate.name)


# ── Превью ───────────────────────────────────────────────────────────────

def _web_mode(im):
    """Режим, который принимает WEBP. Прозрачность сохраняется: знак на
    прозрачном фоне при переводе в RGB стал бы чёрным прямоугольником."""
    if im.mode in ("RGB", "RGBA"):
        return im
    if im.mode in ("P", "PA"):
        clear = im.mode == "PA" or "transparency" in im.info
        return im.convert("RGBA" if clear else "RGB")
    if im.mode in ("LA", "La"):
        return im.convert("RGBA")
    return im.convert("RGB")


def _thumb(path: Path) -> Path:
    """Путь к превью; при надобности оно тут же и делается.

    Имя считается от времени изменения и размера исходника, поэтому правка
    картинки даёт новое имя — старое превью не подменяет собой новое, а адрес
    можно отдавать браузеру в кэш надолго.
    """
    info = path.stat()
    key = hashlib.sha1(
        f"{path}|{info.st_mtime_ns}|{info.st_size}|{THUMB_MAX}".encode()
    ).hexdigest()
    target = THUMB_DIR / key[:2] / f"{key}.webp"
    if target.is_file():
        return target

    from PIL import Image, ImageOps

    target.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(path) as im:
        # JPEG распаковывается сразу уменьшенным — на снимке в 4000 px это
        # разница в разы, а превью всё равно 480
        if im.format == "JPEG":
            im.draft("RGB", (THUMB_MAX, THUMB_MAX))
        im = ImageOps.exif_transpose(im)               # снимок с телефона лежит боком
        im = _web_mode(im)
        im.thumbnail((THUMB_MAX, THUMB_MAX), Image.LANCZOS)
        # Пишем во временный файл и переименовываем: два одновременных запроса
        # на одну картинку иначе дали бы недописанный файл в сетке
        tmp = target.with_name(f"{key}.{os.getpid()}.part")
        im.save(tmp, "WEBP", quality=THUMB_QUALITY, method=4)
    tmp.replace(target)
    return target


def purge_thumbs(days: int = THUMB_KEEP_DAYS) -> int:
    """Уборка склада превью: картинку переименовали или поправили — её превью
    больше никто не спросит, а место оно занимает. Зовётся фоновой уборкой."""
    if not THUMB_DIR.is_dir():
        return 0
    edge = datetime.now(timezone.utc).timestamp() - days * 86400
    removed = 0
    for path in THUMB_DIR.rglob("*.webp"):
        try:
            if path.stat().st_mtime < edge:
                path.unlink()
                removed += 1
        except OSError:
            continue
    return removed


# ── Страница и данные ────────────────────────────────────────────────────

@router.get("/pictures", name="pictures")
def pictures_page(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse(request.url_for("login_form"), status_code=303)
    if user["must_change"]:
        return RedirectResponse(request.url_for("change_password_form"), status_code=303)
    return render(request, "pictures.html", {"user": user, "active": "pictures"})


@router.get("/pictures/list", name="pictures_list")
def pictures_list(request: Request):
    if not current_user(request):
        return JSONResponse({"error": "нет доступа"}, status_code=401)
    return JSONResponse(_catalog())


@router.get("/pictures/thumb", name="picture_thumb")
def picture_thumb(request: Request, src: str = ""):
    if not current_user(request):
        return JSONResponse({"error": "нет доступа"}, status_code=401)
    found = _resolve(src)
    if not found:
        return JSONResponse({"error": "картинка не найдена"}, status_code=404)

    if found.path.suffix.lower() in VECTOR_SUFFIXES:
        return FileResponse(found.path, media_type="image/svg+xml", headers=CACHE_HEADERS)
    try:
        thumb = _thumb(found.path)
    except Exception as exc:                           # noqa: BLE001
        # Битый или неподъёмный файл: в сетке вместо кадра будет заглушка,
        # и это честнее пустого места
        return JSONResponse({"error": f"превью не сделать: {exc}"}, status_code=415)
    return FileResponse(thumb, media_type="image/webp", headers=CACHE_HEADERS)


@router.get("/pictures/view", name="picture_view")
def picture_view(request: Request, src: str = ""):
    """Сама картинка — её показывает просмотрщик."""
    if not current_user(request):
        return JSONResponse({"error": "нет доступа"}, status_code=401)
    found = _resolve(src)
    if not found:
        return JSONResponse({"error": "картинка не найдена"}, status_code=404)
    return FileResponse(found.path, headers=CACHE_HEADERS)


@router.get("/pictures/file", name="picture_download")
def picture_download(request: Request, src: str = ""):
    if not current_user(request):
        return JSONResponse({"error": "нет доступа"}, status_code=401)
    found = _resolve(src)
    if not found:
        return JSONResponse({"error": "картинка не найдена"}, status_code=404)
    return FileResponse(found.path, filename=found.name)
