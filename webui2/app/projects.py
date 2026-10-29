"""Вкладка «Проекты»: проекты, их темы, галочки, удаление проекта.

Тема — разговор с project_id: запуск, лента, дописка и прочее — в chat.py,
здесь только страницы. Claude в теме работает в папке проекта (claude.py)."""
import asyncio
import re
import shutil
import subprocess
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from . import chat, claude, config, db, markup
from .web import csrf_ok, current, guarded, to

router = APIRouter()

NAME_LEN = 80
SLUG_LEN = 40
RULES = config.APP_DIR / "project_rules.md"
GITIGNORE = """# Секреты и тяжёлое — не в git
.env
.env.*
*.key
*.pem
node_modules/
.venv/
__pycache__/
# Файлы для хозяйки
downloads/
"""
DONE_MARK = "ИТОГ:"

_LAT = dict(zip("абвгдеёзийклмнопрстуфхцыэ", "abvgdeeziyklmnoprstufhcye"))
_LAT.update({"ж": "zh", "ч": "ch", "ш": "sh", "щ": "sch", "ю": "yu", "я": "ya", "ь": "", "ъ": ""})

TASKS: set[asyncio.Task] = set()     # фоновые проверки и удаления (чтобы не собрал сборщик)


# ── Проекты в базе и на диске ────────────────────────────────────────────

def project(pid: int) -> dict | None:
    return db.one("SELECT * FROM projects WHERE id = ?", (pid,))


def all_projects() -> list[dict]:
    return db.rows("SELECT p.*, (SELECT COUNT(*) FROM conversations c WHERE c.project_id = p.id "
                   "AND EXISTS (SELECT 1 FROM messages m WHERE m.conv_id = c.id)) AS topics "
                   "FROM projects p ORDER BY p.updated_at DESC, p.id DESC")


def slugify(name: str) -> str:
    """Имя папки латиницей: «Мой сайт» → moy-sayt."""
    low = "".join(_LAT.get(ch, ch) for ch in name.lower())
    slug = re.sub(r"[^a-z0-9]+", "-", low).strip("-")[:SLUG_LEN].strip("-")
    return slug or "project"


def free_slug(base: str) -> str:
    slug, n = base, 1
    while db.one("SELECT 1 FROM projects WHERE slug = ?", (slug,)) or (config.PROJECTS_DIR / slug).exists():
        n += 1
        slug = f"{base}-{n}"
    return slug


def short_path(path: str) -> str:
    home = str(Path.home())
    return "~" + path[len(home):] if path.startswith(home + "/") else path


def _git_identity() -> tuple[str, str]:
    def site_git(key: str) -> str:
        out = subprocess.run(["git", "-C", str(config.PROJECT_DIR), "config", key],
                             capture_output=True, text=True, env=claude.child_env())
        return out.stdout.strip()
    return config.GIT_NAME or site_git("user.name"), config.GIT_EMAIL or site_git("user.email")


def create_project(name: str) -> int:
    """Папка с собственным git, .gitignore, downloads/ и правилами общения."""
    slug = free_slug(slugify(name))
    path = config.PROJECTS_DIR / slug
    config.PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    path.mkdir()
    try:
        (path / "downloads").mkdir()
        (path / ".gitignore").write_text(GITIGNORE, encoding="utf-8")
        (path / "CLAUDE.md").write_text(RULES.read_text(encoding="utf-8"), encoding="utf-8")
        user, email = _git_identity()
        env = claude.child_env()
        for cmd in (["init", "-q", "-b", "main"],
                    ["config", "user.name", user], ["config", "user.email", email],
                    ["add", ".gitignore", "CLAUDE.md"],
                    ["-c", "commit.gpgsign=false", "commit", "-q", "-m", f"Новый проект: {name}"]):
            subprocess.run(["git", "-C", str(path), *cmd], check=True, capture_output=True, env=env)
    except (OSError, subprocess.CalledProcessError):
        shutil.rmtree(path, ignore_errors=True)
        raise
    stamp = db.now()
    return db.insert("INSERT INTO projects (name, slug, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                     (name, slug, str(path), stamp, stamp))


def removable(path: str) -> bool:
    """Папку можно удалить: она внутри папки проектов, не ссылка и не папка
    сайта (ни внутри неё, ни вокруг)."""
    p = Path(path)
    if p.is_symlink():
        return False
    p, root = p.resolve(), config.PROJECTS_DIR.resolve()
    if p == root or not p.is_relative_to(root) or Path.home().resolve().is_relative_to(p):
        return False
    return not any(p.is_relative_to(d.resolve()) or d.resolve().is_relative_to(p) for d in config.SITE_DIRS)


# ── Удаление проекта: проверка, «да», удаление ───────────────────────────

def _set(pid: int, state: str, report: str | None = None) -> None:
    if report is None:
        db.run("UPDATE projects SET delete_state = ? WHERE id = ?", (state, pid))
    else:
        db.run("UPDATE projects SET delete_state = ?, delete_report = ? WHERE id = ?", (state, report, pid))


def _background(coro) -> None:
    task = asyncio.create_task(coro)
    TASKS.add(task)
    task.add_done_callback(TASKS.discard)


def nothing_outside(report: str) -> bool:
    return "ничего нет" in report.lower() and len(report) < 200


async def look(pid: int) -> None:
    """Claude смотрит, что проект завёл вне своей папки. Ничего не меняет."""
    proj = project(pid)
    try:
        if not Path(proj["path"]).is_dir():
            ok, text = True, "Папки проекта уже нет. Вне папки проекта ничего нет"
        else:
            prompt = claude.LOOK_PROMPT.format(path=proj["path"], site=config.PROJECT_DIR)
            ok, text = await claude.once(prompt, proj["path"], remove=False)
    except Exception as exc:                           # noqa: BLE001
        ok, text = False, str(exc)
    if project(pid):
        _set(pid, "ready" if ok else "unclear",
             text if ok else "Не получилось посмотреть, что убрать: " + (text or "ошибка"))


async def remove(pid: int) -> None:
    """После «да»: Claude убирает найденное вне папки, затем сайт удаляет
    саму папку и проект."""
    proj = project(pid)
    try:
        for conv in chat.conversations(pid):
            chat.stop(conv["id"])
        report = proj["delete_report"]
        if Path(proj["path"]).is_dir() and not nothing_outside(report):
            prompt = claude.REMOVE_PROMPT.format(path=proj["path"], site=config.PROJECT_DIR, report=report)
            prompt += f"\n\nПоследней строкой ответа напиши «{DONE_MARK} всё убрано» или «{DONE_MARK} не всё»."
            ok, text = await claude.once(prompt, proj["path"], remove=True)
            done = ok and f"{DONE_MARK} всё убрано" in text
            if not done:
                text = text.replace(f"{DONE_MARK} не всё", "").strip()
                _set(pid, "unclear", (text or "Не получилось убрать всё.") +
                     "\n\nПапка проекта не тронута.")
                return
        if Path(proj["path"]).exists():
            if not removable(proj["path"]):
                _set(pid, "unclear", "Эту папку удалить так нельзя: она не в папке проектов или "
                                    "относится к самому сайту. Папка не тронута.")
                return
            await asyncio.to_thread(shutil.rmtree, proj["path"])
        # Служебные журналы Claude по этой папке: их заводит и сама проверка
        logs = Path.home() / ".cache/claude-cli-nodejs" / proj["path"].replace("/", "-")
        if logs.parent.is_dir() and logs.name.startswith("-") and logs.is_dir() and not logs.is_symlink():
            await asyncio.to_thread(shutil.rmtree, logs, True)
        db.run("DELETE FROM projects WHERE id = ?", (pid,))
    except Exception as exc:                           # noqa: BLE001
        if project(pid):
            _set(pid, "unclear", f"Удаление прервалось: {exc}")


# ── Страницы ─────────────────────────────────────────────────────────────

def _allowed(request: Request, csrf: str) -> bool:
    sess = current(request)
    return bool(sess and not sess["locked"] and csrf_ok(request, sess, csrf))


def to_project(pid: int, tail: str = "") -> RedirectResponse:
    return RedirectResponse(f"{config.ROOT_PATH}/projects/{pid}{tail}", status_code=303)


def _ctx(proj: dict, request: Request) -> dict:
    from .files import files_ctx                       # files.py сам опирается на этот модуль
    return {"folder": short_path(proj["path"]), **files_ctx(proj, request)}


@router.get("/projects", name="projects")
def projects_page(request: Request, error: str = ""):
    rows = all_projects()
    for row in rows:
        row["folder"] = short_path(row["path"])
    return guarded(request, "projects.html", "projects",
                   {"title": "Проекты", "projects": rows, "error": error[:200]})


@router.post("/projects/new", name="project_new")
def project_new(request: Request, name: str = Form(""), csrf: str = Form("")):
    if not _allowed(request, csrf):
        return to(request, "projects")
    name = " ".join(name.split())[:NAME_LEN]
    if not name:
        return guarded(request, "projects.html", "projects",
                       {"title": "Проекты", "projects": all_projects(), "error": "Напиши название проекта"})
    try:
        pid = create_project(name)
    except (OSError, subprocess.CalledProcessError):
        return guarded(request, "projects.html", "projects",
                       {"title": "Проекты", "projects": all_projects(),
                        "error": "Не получилось завести папку проекта"})
    return to_project(pid)


@router.get("/projects/{pid}", name="project")
def project_page(request: Request, pid: int):
    if not current(request):
        return to(request, "login_form")
    proj = project(pid)
    if not proj:
        return to(request, "projects")
    if proj["delete_state"]:
        return to_project(pid, "/delete")
    if not current(request)["locked"]:
        last = chat.conversations(pid)
        if last:
            return chat.to_conv(last[0])
    return guarded(request, "chat.html", "projects",
                   {"title": proj["name"], "convs": [], "conv": None, **_ctx(proj, request)})


@router.get("/projects/{pid}/t/{conv_id}", name="topic")
def topic_page(request: Request, pid: int, conv_id: int, n: str | None = None):
    if not current(request):
        return to(request, "login_form")
    proj = project(pid)
    conv = chat.conversation(conv_id)
    if not proj:
        return to(request, "projects")
    if not conv or conv["project_id"] != pid:
        return to_project(pid)
    if proj["delete_state"]:
        return to_project(pid, "/delete")
    return guarded(request, "chat.html", "projects", {**chat.talk_ctx(conv, n), **_ctx(proj, request)})


@router.post("/projects/{pid}/topic/new", name="topic_new")
def topic_new(request: Request, pid: int, csrf: str = Form("")):
    if not project(pid) or not _allowed(request, csrf):
        return to_project(pid)
    return chat.to_conv(chat.new_conversation(pid, config.TOPIC_MODEL))


@router.post("/projects/{pid}/access", name="project_access")
def project_access(request: Request, pid: int, csrf: str = Form(""),
                   commands: str = Form(""), full: str = Form(""), back: str = Form("")):
    if project(pid) and _allowed(request, csrf):
        db.run("UPDATE projects SET allow_commands = ?, full_access = ? WHERE id = ?",
               (int(bool(commands) or bool(full)), int(bool(full)), pid))
    tail = f"/t/{int(back)}" if back.isdigit() else ""
    return to_project(pid, tail)


@router.post("/projects/{pid}/rename", name="project_rename")
def project_rename(request: Request, pid: int, name: str = Form(""), csrf: str = Form(""),
                   back: str = Form("")):
    """Меняется только название: папка и адрес остаются прежними."""
    name = " ".join(name.split())[:80]
    if project(pid) and _allowed(request, csrf) and name:
        db.run("UPDATE projects SET name = ? WHERE id = ?", (name, pid))
    tail = f"/t/{int(back)}" if back.isdigit() else ""
    return to_project(pid, tail)


@router.post("/projects/{pid}/delete", name="project_delete")
async def project_delete(request: Request, pid: int, csrf: str = Form("")):
    proj = project(pid)
    if proj and _allowed(request, csrf) and proj["delete_state"] in ("", "unclear"):
        _set(pid, "checking", "")
        _background(look(pid))
    return to_project(pid, "/delete")


@router.get("/projects/{pid}/delete", name="project_delete_page")
def project_delete_page(request: Request, pid: int):
    if not current(request):
        return to(request, "login_form")
    proj = project(pid)
    if not proj:
        return to(request, "projects")
    if not proj["delete_state"]:
        return to_project(pid)
    return guarded(request, "project_delete.html", "projects",
                   {"title": "Удаление проекта", "report": markup.render(proj["delete_report"]),
                    **_ctx(proj, request)})


@router.post("/projects/{pid}/delete/yes", name="project_delete_yes")
async def project_delete_yes(request: Request, pid: int, csrf: str = Form("")):
    proj = project(pid)
    if proj and _allowed(request, csrf) and proj["delete_state"] == "ready":
        _set(pid, "removing")
        _background(remove(pid))
    return to_project(pid, "/delete")


@router.post("/projects/{pid}/delete/no", name="project_delete_no")
def project_delete_no(request: Request, pid: int, csrf: str = Form("")):
    proj = project(pid)
    if proj and _allowed(request, csrf) and proj["delete_state"] in ("ready", "unclear"):
        _set(pid, "", "")
    return to_project(pid)
