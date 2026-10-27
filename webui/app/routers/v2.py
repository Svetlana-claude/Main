"""Рабочее место v2: один главный экран поверх тех же разговоров.

Работает рядом со старым интерфейсом и на той же базе. Отправка и поток
ответа — прежние адреса (`chat_send`/`topic_send`, `chat_stream`/`topic_stream`),
здесь только страница, переходы и остановка ответа.
"""
from fastapi import APIRouter, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse

from .. import db
from ..deps import current_user, render
from ..services import runs
from . import projects as projects_router

router = APIRouter(prefix="/v2")


def _guard(request: Request):
    user = current_user(request)
    if not user:
        return None, RedirectResponse(request.url_for("login_form"), status_code=303)
    if user["must_change"]:
        return None, RedirectResponse(request.url_for("change_password_form"), status_code=303)
    return user, None


def _tree() -> tuple[list[dict], list[dict]]:
    """Боковой список: проекты с темами (проект → тема) и отдельно чатики.

    Проекты и темы внутри — по свежести последнего разговора. Только проекты
    v2 (`in_v2`): старые переносятся сюда поэтапно.
    """
    projects = db.query("SELECT id, name FROM projects WHERE in_v2")
    by_id = {p["id"]: {**p, "topics": [], "fresh": None} for p in projects}
    for t in db.query(
        "SELECT id, project_id, title, updated_at FROM conversations "
        "WHERE kind = 'topic' ORDER BY updated_at DESC"
    ):
        p = by_id.get(t["project_id"])
        if p:
            p["topics"].append(t)
            p["fresh"] = p["fresh"] or t["updated_at"]
    ordered = sorted(by_id.values(),
                     key=lambda p: (p["fresh"] is not None, p["fresh"] or 0, p["name"]),
                     reverse=True)
    chats = db.query(
        "SELECT id, title FROM conversations WHERE kind = 'chat' "
        "ORDER BY updated_at DESC LIMIT 100"
    )
    return ordered, chats


@router.get("", name="v2_home")
def v2_home(request: Request):
    """Главная — последний разговор."""
    user, redirect = _guard(request)
    if redirect:
        return redirect
    last = db.query_one(
        """
        SELECT c.id FROM conversations c LEFT JOIN projects p ON p.id = c.project_id
        WHERE c.kind = 'chat' OR p.in_v2
        ORDER BY c.updated_at DESC LIMIT 1
        """
    )
    if not last:
        projects, chats = _tree()
        return render(request, "v2/main.html", {"user": user, "projects": projects,
                                               "chats": chats, "current": None,
                                               "messages": [], "running": False,
                                               "open_project": request.query_params.get("p")})
    return RedirectResponse(request.url_for("v2_conversation", conv_id=last["id"]),
                            status_code=303)


@router.get("/c/{conv_id}", name="v2_conversation")
def v2_conversation(request: Request, conv_id: int):
    user, redirect = _guard(request)
    if redirect:
        return redirect
    current = db.query_one(
        """
        SELECT c.id, c.kind, c.title, c.project_id, p.name AS project
        FROM conversations c LEFT JOIN projects p ON p.id = c.project_id
        WHERE c.id = %s
        """,
        (conv_id,),
    )
    if not current:
        return RedirectResponse(request.url_for("v2_home"), status_code=303)
    messages = db.query(
        "SELECT role, content FROM messages WHERE conversation_id = %s ORDER BY id",
        (conv_id,),
    )
    if current["kind"] == "chat":
        send_url = request.url_for("chat_send", chat_id=conv_id)
        stream_url = request.url_for("chat_stream", chat_id=conv_id)
    else:
        send_url = request.url_for("topic_send", topic_id=conv_id)
        stream_url = request.url_for("topic_stream", topic_id=conv_id)
    projects, chats = _tree()
    return render(
        request,
        "v2/main.html",
        {
            "user": user,
            "projects": projects,
            "chats": chats,
            "current": current,
            "messages": messages,
            "send_url": send_url,
            "stream_url": stream_url,
            "running": runs.active(current["kind"], conv_id),
            "open_project": request.query_params.get("p"),
        },
    )


@router.post("/new", name="v2_new")
def v2_new(request: Request):
    """Новый чатик — одно нажатие."""
    user, redirect = _guard(request)
    if redirect:
        return redirect
    row = db.query_one(
        "INSERT INTO conversations (kind, title) VALUES ('chat', 'Новый чат') RETURNING id"
    )
    return RedirectResponse(request.url_for("v2_conversation", conv_id=row["id"]),
                            status_code=303)


@router.post("/project", name="v2_project_new")
def v2_project_new(request: Request, name: str = Form(""), back: str = Form("")):
    """Новый проект v2: каталог в репозитории и папка выдачи — как в старом
    интерфейсе. После создания возвращаемся туда же, проект раскрыт."""
    user, redirect = _guard(request)
    if redirect:
        return redirect
    clean = " ".join(name.split())[:120]
    if not clean:
        return RedirectResponse(request.url_for("v2_home"), status_code=303)
    slug = base_slug = projects_router._slugify(clean)
    suffix = 1
    while db.query_one("SELECT 1 AS ok FROM projects WHERE slug = %s", (slug,)):
        suffix += 1
        slug = f"{base_slug}-{suffix}"
    try:
        workdir = projects_router._safe_workdir(slug)
    except ValueError:
        return RedirectResponse(request.url_for("v2_home"), status_code=303)
    workdir.mkdir(parents=True, exist_ok=True)
    projects_router._downloads_dir(workdir)
    row = db.query_one(
        "INSERT INTO projects (name, slug, workdir, in_v2) VALUES (%s, %s, %s, true) RETURNING id",
        (clean, slug, str(workdir)),
    )
    # Возврат только на свои же страницы v2 — адрес приходит из формы
    target = back if back.startswith(str(request.url_for("v2_home"))) else str(request.url_for("v2_home"))
    return RedirectResponse(f"{target.split('?')[0]}?p={row['id']}", status_code=303)


@router.post("/topic", name="v2_topic_new")
def v2_topic_new(request: Request, project_id: int = Form(...), title: str = Form("")):
    """Новая тема в проекте — сразу открывается в v2."""
    user, redirect = _guard(request)
    if redirect:
        return redirect
    if not db.query_one("SELECT 1 AS ok FROM projects WHERE id = %s AND in_v2", (project_id,)):
        return RedirectResponse(request.url_for("v2_home"), status_code=303)
    clean = " ".join(title.split())[:120] or "Новая тема"
    row = db.query_one(
        "INSERT INTO conversations (kind, project_id, title) "
        "VALUES ('topic', %s, %s) RETURNING id",
        (project_id, clean),
    )
    return RedirectResponse(request.url_for("v2_conversation", conv_id=row["id"]),
                            status_code=303)


@router.post("/c/{conv_id}/stop", name="v2_stop")
async def v2_stop(request: Request, conv_id: int):
    """«Стоп»: снимает фоновый запуск, драйвер при этом гасит процесс claude."""
    if not current_user(request):
        return JSONResponse({"error": "нет доступа"}, status_code=401)
    conv = db.query_one("SELECT kind FROM conversations WHERE id = %s", (conv_id,))
    run = runs.get(conv["kind"], conv_id) if conv else None
    if not run or run.done or not run._task:
        return JSONResponse({"ok": False})
    run._task.cancel()
    # Вопрос без ответа в ленте выглядел бы потерянным
    db.execute(
        "INSERT INTO messages (conversation_id, role, content) VALUES (%s, 'error', %s)",
        (conv_id, "Остановлено"),
    )
    return JSONResponse({"ok": True})
