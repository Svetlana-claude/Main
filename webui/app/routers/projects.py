"""Проекты: диалог по темам, файлообмен, работа с файлами проекта.

В отличие от чатика тут у Claude есть доступ к рабочему каталогу проекта.
Правка файлов разрешена, запуск команд — только если у проекта поднят флаг
allow_bash. Так у веб-интерфейса нет права выполнять произвольные команды
по умолчанию.
"""
import mimetypes
import os
import re
import stat
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse

from .. import config, db
from ..deps import current_user, render
from ..services import claude_driver, runs
from .chats import _save_answer

router = APIRouter()

MAX_UPLOAD_BYTES = 64 * 1024 * 1024      # 64 МБ на файл

# ── Папка выдачи проекта ─────────────────────────────────────────────────
#
# Раздел «Файлы» справа показывает только то, что загрузили через форму,
# а забрать из браузера сделанное Claude было нечем. Кнопка «Файлы проекта»
# открывает окошко со списком папки `downloads/` в каталоге проекта.
#
# Показывается именно она, а не весь рабочий каталог: там сотни файлов кода,
# и нужный среди них не найти. Папка выдачи — место, куда кладётся то, что
# просили сделать или выложить, и список в окошке короткий и осмысленный.
DOWNLOADS_DIR = "downloads"

# Служебное и тяжёлое: в список не попадает и по прямой ссылке не отдаётся.
# Папка выдачи такого содержать не должна, но проверка дешевле уверенности.
TREE_SKIP_DIRS = frozenset({
    ".git", ".venv", "venv", "node_modules", "__pycache__",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build",
})
TREE_SKIP_SUFFIXES = frozenset({".pyc", ".pyo", ".key", ".pem"})

# Предел на список: окошко должно открываться сразу. Лучше показать свежие
# файлы и честно сказать, что список обрезан.
TREE_MAX_FILES = 2000
TREE_MAX_DEPTH = 12


def _downloads_dir(workdir: str | Path) -> Path:
    """Папка выдачи проекта. Заводится при первом обращении.

    Создаётся здесь, а не только при создании проекта: проекты, заведённые
    записью в таблице (каталог уже был), формы не проходили — и папки у них
    нет. Пустая папка лучше пустого окошка с ошибкой.
    """
    target = Path(workdir).resolve() / DOWNLOADS_DIR
    target.mkdir(parents=True, exist_ok=True)
    return target


def _tree_closed(name: str) -> bool:
    """Имя, которое не показывается и не отдаётся ни при каких условиях.

    Файлы настроек держатся вне каталога проекта (см. `config`), но проект
    заводится на любой каталог, и `.env` может оказаться внутри. Отдавать его
    кнопкой «скачать» — то же самое, что отдать ключи.
    """
    return name.startswith(".env") or Path(name).suffix in TREE_SKIP_SUFFIXES


def _tree_visible(root: Path, path: Path) -> bool:
    """Показывается ли этот файл в списке. По нему же решается и скачивание:
    иначе прямой ссылкой забирался бы файл, скрытый из списка."""
    try:
        rel = path.relative_to(root)
    except ValueError:
        return False
    if any(part in TREE_SKIP_DIRS for part in rel.parts[:-1]):
        return False
    return not _tree_closed(rel.name)


def _tree_entries(root_dir: Path) -> tuple[list[dict], bool]:
    """Файлы папки выдачи, свежие сверху.

    Второе значение — признак того, что список упёрся в предел и обрезан.
    Символьные ссылки пропускаются целиком: ссылка наружу всё равно была бы
    отбита при скачивании, и строка в списке обещала бы то, чего не будет.
    """
    root = root_dir.resolve()
    rows: list[dict] = []
    truncated = False

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        here = Path(dirpath)
        depth = len(here.relative_to(root).parts)
        if depth >= TREE_MAX_DEPTH:
            dirnames[:] = []
        else:
            dirnames[:] = sorted(d for d in dirnames if d not in TREE_SKIP_DIRS)

        for name in filenames:
            if _tree_closed(name):
                continue
            path = here / name
            if path.is_symlink():
                continue
            try:
                info = path.stat()
            except OSError:
                continue                     # исчез между обходом и чтением
            if not stat.S_ISREG(info.st_mode):
                continue                     # сокеты, устройства, битые ссылки
            if len(rows) >= TREE_MAX_FILES:
                truncated = True
                break
            rows.append({
                "path": str(path.relative_to(root)),
                "name": name,
                "size": info.st_size,
                "mtime": datetime.fromtimestamp(info.st_mtime, timezone.utc).isoformat(),
                "mtime_ts": info.st_mtime,
            })
        if truncated:
            break

    rows.sort(key=lambda r: r["mtime_ts"], reverse=True)
    for row in rows:
        del row["mtime_ts"]
    return rows, truncated


def _resolve_in_dir(root_dir: Path, relative: str) -> Path:
    """Путь внутри папки выдачи — либо ValueError.

    Проверка не косметическая: без неё `?path=../../.config/webui/webui.env`
    отдаёт кнопкой «скачать» ключи приложения. Сравнение идёт после `resolve()`,
    поэтому и `..`, и абсолютный путь, и символьная ссылка наружу упираются
    в одно и то же условие. Заодно `..` не выпускает и в сам рабочий каталог:
    наружу папки выдачи ходить незачем.
    """
    root = root_dir.resolve()
    candidate = (root / relative).resolve()
    if candidate == root or root not in candidate.parents:
        raise ValueError("путь вне папки выдачи проекта")
    return candidate


def _guard(request: Request):
    user = current_user(request)
    if not user:
        return None, RedirectResponse(request.url_for("login_form"), status_code=303)
    if user["must_change"]:
        return None, RedirectResponse(request.url_for("change_password_form"), status_code=303)
    return user, None


# Кириллица в путях репозитория работает, но мешает в git, ssh и скриптах,
# поэтому имя каталога транслитерируется
_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def _slugify(name: str) -> str:
    lowered = unicodedata.normalize("NFKC", name).lower()
    text = "".join(_TRANSLIT.get(ch, ch) for ch in lowered)
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:50] or "project"


def _safe_workdir(slug: str) -> Path:
    """Рабочий каталог проекта строго внутри репозитория.

    Проверка не косметическая: без неё slug вида ../../etc уводит запись
    за пределы репозитория.
    """
    root = config.REPO_ROOT.resolve()
    candidate = (root / slug).resolve()
    if candidate == root or root not in candidate.parents:
        raise ValueError("недопустимое имя проекта")
    return candidate


@router.get("/projects", name="projects")
def projects(request: Request, id: int | None = None, topic: int | None = None):
    user, redirect = _guard(request)
    if redirect:
        return redirect

    items = db.query(
        """
        SELECT p.id, p.name, p.slug, p.workdir, p.allow_bash, p.created_at,
               (SELECT count(*) FROM conversations c WHERE c.project_id = p.id) AS topics,
               (SELECT count(*) FROM files f WHERE f.project_id = p.id) AS files
        FROM projects p WHERE NOT p.archived ORDER BY p.created_at
        """
    )

    project = None
    topics: list[dict] = []
    current_topic = None
    messages: list[dict] = []
    files: list[dict] = []

    if id is None and items:
        id = items[0]["id"]

    if id is not None:
        project = db.query_one("SELECT * FROM projects WHERE id = %s", (id,))

    if project:
        topics = db.query(
            """
            SELECT c.id, c.title, c.updated_at,
                   (SELECT count(*) FROM messages m WHERE m.conversation_id = c.id) AS msg_count
            FROM conversations c WHERE c.project_id = %s ORDER BY c.updated_at DESC
            """,
            (project["id"],),
        )
        files = db.query(
            "SELECT id, filename, size_bytes, mime, created_at FROM files "
            "WHERE project_id = %s ORDER BY created_at DESC",
            (project["id"],),
        )
        if topic is None and topics:
            topic = topics[0]["id"]
        if topic is not None:
            current_topic = db.query_one(
                "SELECT id, title, claude_session_id FROM conversations "
                "WHERE id = %s AND project_id = %s",
                (topic, project["id"]),
            )
        if current_topic:
            messages = db.query(
                """
                SELECT role, content, created_at, cost_usd, duration_ms,
                       input_tokens, output_tokens, model
                FROM messages WHERE conversation_id = %s ORDER BY id
                """,
                (current_topic["id"],),
            )

    return render(
        request,
        "projects.html",
        {
            "user": user,
            "active": "projects",
            "items": items,
            "project": project,
            "topics": topics,
            "current_topic": current_topic,
            "messages": messages,
            "files": files,
        },
    )


@router.post("/projects/new", name="project_new")
def project_new(request: Request, name: str = Form(...)):
    user, redirect = _guard(request)
    if redirect:
        return redirect

    clean = " ".join(name.split())[:120]
    if not clean:
        return RedirectResponse(request.url_for("projects"), status_code=303)

    slug = _slugify(clean)
    try:
        workdir = _safe_workdir(slug)
    except ValueError:
        return render(
            request,
            "projects.html",
            {"user": user, "active": "projects", "items": [],
             "error": "Недопустимое имя проекта", "project": None,
             "topics": [], "current_topic": None, "messages": [], "files": []},
        )

    suffix = 1
    base_slug = slug
    while db.query_one("SELECT 1 FROM projects WHERE slug = %s", (slug,)):
        suffix += 1
        slug = f"{base_slug}-{suffix}"
        workdir = _safe_workdir(slug)

    workdir.mkdir(parents=True, exist_ok=True)
    _downloads_dir(workdir)          # папка выдачи заводится сразу вместе с проектом
    row = db.query_one(
        "INSERT INTO projects (name, slug, workdir) VALUES (%s, %s, %s) RETURNING id",
        (clean, slug, str(workdir)),
    )
    return RedirectResponse(
        str(request.url_for("projects")) + f"?id={row['id']}", status_code=303
    )


@router.post("/projects/{project_id}/bash", name="project_toggle_bash")
def project_toggle_bash(request: Request, project_id: int, allow: str = Form("")):
    """Разрешение запускать команды в проекте. По умолчанию выключено."""
    user, redirect = _guard(request)
    if redirect:
        return redirect
    db.execute(
        "UPDATE projects SET allow_bash = %s WHERE id = %s",
        (allow == "on", project_id),
    )
    return RedirectResponse(
        str(request.url_for("projects")) + f"?id={project_id}", status_code=303
    )


@router.post("/projects/{project_id}/topics/new", name="topic_new")
def topic_new(request: Request, project_id: int, title: str = Form(...)):
    user, redirect = _guard(request)
    if redirect:
        return redirect
    clean = " ".join(title.split())[:120] or "Новая тема"
    row = db.query_one(
        "INSERT INTO conversations (kind, project_id, title) "
        "VALUES ('topic', %s, %s) RETURNING id",
        (project_id, clean),
    )
    return RedirectResponse(
        str(request.url_for("projects")) + f"?id={project_id}&topic={row['id']}",
        status_code=303,
    )


@router.post("/projects/topics/{topic_id}/delete", name="topic_delete")
def topic_delete(request: Request, topic_id: int):
    user, redirect = _guard(request)
    if redirect:
        return redirect
    row = db.query_one(
        "SELECT project_id FROM conversations WHERE id = %s AND kind = 'topic'", (topic_id,)
    )
    db.execute("DELETE FROM conversations WHERE id = %s AND kind = 'topic'", (topic_id,))
    target = str(request.url_for("projects"))
    if row:
        target += f"?id={row['project_id']}"
    return RedirectResponse(target, status_code=303)


@router.post("/projects/topics/{topic_id}/send", name="topic_send")
async def topic_send(request: Request, topic_id: int, text: str = Form(...)):
    user = current_user(request)
    if not user or user["must_change"]:
        return JSONResponse({"error": "нет доступа"}, status_code=401)

    conv = db.query_one(
        """
        SELECT c.id, c.claude_session_id, p.workdir, p.allow_bash
        FROM conversations c JOIN projects p ON p.id = c.project_id
        WHERE c.id = %s AND c.kind = 'topic'
        """,
        (topic_id,),
    )
    if not conv:
        return JSONResponse({"error": "тема не найдена"}, status_code=404)

    prompt = text.strip()
    if not prompt:
        return JSONResponse({"error": "пустое сообщение"}, status_code=400)

    # Проверка до записи вопроса: иначе при отказе вопрос остался бы в ленте
    # висеть без ответа, и выглядело бы это как потерянное сообщение.
    if runs.active("topic", topic_id):
        return JSONResponse({"error": "в этой теме уже идёт ответ"}, status_code=409)

    db.execute(
        "INSERT INTO messages (conversation_id, role, content) VALUES (%s, 'user', %s)",
        (topic_id, prompt),
    )
    db.execute("UPDATE conversations SET updated_at = now() WHERE id = %s", (topic_id,))

    model = db.get_settings().get("model", "opus")
    workdir = Path(conv["workdir"])

    async def producer(run):
        """Работа движка. Идёт в задаче приложения и о браузере не знает."""
        async for event in claude_driver.run(
            prompt,
            model=model,
            session_id=conv["claude_session_id"],
            with_tools=True,
            workdir=workdir,
            allow_bash=bool(conv["allow_bash"]),
        ):
            if event["type"] == "result":
                _save_answer(topic_id, event)
            elif event["type"] == "error":
                db.execute(
                    "INSERT INTO messages (conversation_id, role, content) "
                    "VALUES (%s, 'error', %s)",
                    (topic_id, event["message"]),
                )
            await run.append(event)

    runs.start("topic", topic_id, producer)
    # Ответ отдаётся сразу: за событиями страница приходит отдельно, и уход
    # с неё работу больше не обрывает.
    return JSONResponse({"ok": True})


@router.get("/projects/topics/{topic_id}/stream", name="topic_stream")
async def topic_stream(request: Request, topic_id: int, start: int = 0, active: int = 0):
    """События идущего ответа, начиная с позиции `start`.

    Поток можно оборвать и открыть заново — работа от этого не страдает.
    Если запуска нет, сразу отвечаем `idle`: страница поймёт, что показывать
    нечего, и не станет ждать впустую.
    """
    user = current_user(request)
    if not user or user["must_change"]:
        return JSONResponse({"error": "нет доступа"}, status_code=401)

    return StreamingResponse(
        runs.sse(runs.get("topic", topic_id), start, only_active=bool(active)),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/projects/{project_id}/tree", name="project_tree")
def project_tree(request: Request, project_id: int):
    """Список файлов папки выдачи — его читает окошко «Файлы проекта»."""
    if not current_user(request):
        return JSONResponse({"error": "нет доступа"}, status_code=401)

    project = db.query_one(
        "SELECT id, name, workdir FROM projects WHERE id = %s", (project_id,)
    )
    if not project:
        return JSONResponse({"error": "проект не найден"}, status_code=404)

    if not Path(project["workdir"]).is_dir():
        return JSONResponse(
            {"error": f"рабочий каталог {project['workdir']} не найден"}, status_code=404
        )

    try:
        root_dir = _downloads_dir(project["workdir"])
    except OSError as exc:
        return JSONResponse(
            {"error": f"не удалось завести папку выдачи: {exc}"}, status_code=500
        )

    rows, truncated = _tree_entries(root_dir)
    return JSONResponse({
        "dir": str(root_dir),
        "files": rows,
        "truncated": truncated,
        "limit": TREE_MAX_FILES,
    })


@router.get("/projects/{project_id}/tree/file", name="project_tree_download")
def project_tree_download(request: Request, project_id: int, path: str = ""):
    """Отдаёт файл из папки выдачи проекта."""
    if not current_user(request):
        return JSONResponse({"error": "нет доступа"}, status_code=401)

    project = db.query_one("SELECT id, workdir FROM projects WHERE id = %s", (project_id,))
    if not project:
        return JSONResponse({"error": "проект не найден"}, status_code=404)

    root_dir = Path(project["workdir"]).resolve() / DOWNLOADS_DIR
    try:
        target = _resolve_in_dir(root_dir, path)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    if not _tree_visible(root_dir.resolve(), target):
        return JSONResponse({"error": "файл закрыт для скачивания"}, status_code=403)
    if not target.is_file():
        return JSONResponse({"error": "файл не найден"}, status_code=404)

    return FileResponse(
        target,
        filename=target.name,
        media_type=mimetypes.guess_type(target.name)[0] or "application/octet-stream",
    )


@router.post("/projects/{project_id}/upload", name="project_upload")
async def project_upload(
    request: Request, project_id: int, upload: UploadFile = File(...)
):
    user, redirect = _guard(request)
    if redirect:
        return redirect

    project = db.query_one("SELECT id FROM projects WHERE id = %s", (project_id,))
    if not project:
        return RedirectResponse(request.url_for("projects"), status_code=303)

    config.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    original = Path(upload.filename or "файл").name          # без путей из имени
    stored_name = f"{uuid.uuid4().hex}_{_slugify(Path(original).stem)}{Path(original).suffix}"
    target = config.UPLOADS_DIR / stored_name

    size = 0
    with target.open("wb") as sink:
        while chunk := await upload.read(1024 * 256):
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                sink.close()
                target.unlink(missing_ok=True)
                return RedirectResponse(
                    str(request.url_for("projects")) + f"?id={project_id}&err=big",
                    status_code=303,
                )
            sink.write(chunk)

    db.execute(
        "INSERT INTO files (project_id, filename, stored_name, size_bytes, mime) "
        "VALUES (%s, %s, %s, %s, %s)",
        (
            project_id,
            original,
            stored_name,
            size,
            upload.content_type or mimetypes.guess_type(original)[0],
        ),
    )
    return RedirectResponse(
        str(request.url_for("projects")) + f"?id={project_id}", status_code=303
    )


@router.get("/projects/files/{file_id}", name="project_file_download")
def project_file_download(request: Request, file_id: int):
    if not current_user(request):
        return RedirectResponse(request.url_for("login_form"), status_code=303)

    row = db.query_one(
        "SELECT filename, stored_name, mime FROM files WHERE id = %s", (file_id,)
    )
    if not row:
        return JSONResponse({"error": "файл не найден"}, status_code=404)

    path = config.UPLOADS_DIR / row["stored_name"]
    if not path.is_file():
        return JSONResponse({"error": "файл отсутствует на диске"}, status_code=410)

    return FileResponse(
        path,
        filename=row["filename"],
        media_type=row["mime"] or "application/octet-stream",
    )


@router.post("/projects/files/{file_id}/delete", name="project_file_delete")
def project_file_delete(request: Request, file_id: int):
    user, redirect = _guard(request)
    if redirect:
        return redirect
    row = db.query_one(
        "SELECT project_id, stored_name FROM files WHERE id = %s", (file_id,)
    )
    if row:
        (config.UPLOADS_DIR / row["stored_name"]).unlink(missing_ok=True)
        db.execute("DELETE FROM files WHERE id = %s", (file_id,))
    target = str(request.url_for("projects"))
    if row:
        target += f"?id={row['project_id']}"
    return RedirectResponse(target, status_code=303)
