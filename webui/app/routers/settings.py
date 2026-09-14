"""Настройки: параметры приложения, файлы сопровождения, сессии, экспорт."""
from datetime import datetime, timezone
from pathlib import Path

import markdown as md
from fastapi import APIRouter, Form, Request
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse

from .. import config, db, timefmt
from ..deps import current_user, render
from ..services import restart

router = APIRouter()


def _guard(request: Request):
    user = current_user(request)
    if not user:
        return None, RedirectResponse(request.url_for("login_form"), status_code=303)
    if user["must_change"]:
        return None, RedirectResponse(request.url_for("change_password_form"), status_code=303)
    return user, None


def _support_path(name: str) -> Path | None:
    """Путь к файлу сопровождения.

    Имя сверяется со белым списком, а не просто чистится: иначе через параметр
    можно было бы открыть на запись любой файл на диске.
    """
    if name not in config.SUPPORT_FILES:
        return None
    return config.REPO_ROOT / name


@router.get("/settings", name="settings_page")
def settings_page(request: Request, file: str | None = None):
    user, redirect = _guard(request)
    if redirect:
        return redirect

    values = db.get_settings()

    files = []
    for name in config.SUPPORT_FILES:
        path = config.REPO_ROOT / name
        files.append(
            {
                "name": name,
                "exists": path.is_file(),
                "size": path.stat().st_size if path.is_file() else 0,
                "mtime": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) if path.is_file() else None,
            }
        )

    content = ""
    preview = ""
    selected = None
    if file:
        path = _support_path(file)
        if path and path.is_file():
            selected = file
            content = path.read_text(encoding="utf-8")
            preview = md.markdown(content, extensions=["tables", "fenced_code"])

    sessions = db.query(
        "SELECT id, created_at, last_seen, ip, user_agent FROM sessions "
        "WHERE user_id = %s ORDER BY last_seen DESC",
        (user["id"],),
    )

    projects = db.query(
        "SELECT id, name, slug, workdir, allow_bash FROM projects "
        "WHERE NOT archived ORDER BY name"
    )

    totp_row = db.query_one("SELECT totp_enabled FROM users WHERE id = %s", (user["id"],))

    return render(
        request,
        "settings.html",
        {
            "user": user,
            "active": "settings",
            "values": values,
            "files": files,
            "selected": selected,
            "content": content,
            "preview": preview,
            "sessions": sessions,
            "projects": projects,
            "restart": restart.current().as_dict(),
            "current_session": user["session_id"],
            "tz_choices": timefmt.zone_choices(),
            "tz_current": timefmt.zone_name(values),
            "totp_enabled": bool(totp_row and totp_row["totp_enabled"]),
        },
    )


@router.post("/settings/save", name="settings_save")
def settings_save(
    request: Request,
    refresh_seconds: str = Form("10"),
    model: str = Form("opus"),
    theme: str = Form("light"),
    metrics_keep_hours: str = Form("48"),
    limit_5h_tokens: str = Form("0"),
    limit_week_tokens: str = Form("0"),
    timezone_name: str = Form(timefmt.DEFAULT_TZ, alias="timezone"),
):
    user, redirect = _guard(request)
    if redirect:
        return redirect

    def clamp_int(raw: str, low: int, high: int, default: int) -> str:
        try:
            return str(max(low, min(high, int(float(raw)))))
        except (TypeError, ValueError):
            return str(default)

    db.set_setting("refresh_seconds", clamp_int(refresh_seconds, 2, 600, 10))
    db.set_setting("metrics_keep_hours", clamp_int(metrics_keep_hours, 1, 720, 48))

    allowed_models = {"opus", "sonnet", "haiku", "fable"}
    db.set_setting("model", model if model in allowed_models else "opus")
    db.set_setting("theme", theme if theme in {"light", "dark", "system"} else "light")
    # Пояс — только из списка: произвольная строка из формы уронила бы
    # перевод времени на каждой странице
    db.set_setting("timezone", timezone_name if timefmt.valid_zone(timezone_name) else timefmt.DEFAULT_TZ)

    # Пределы окон: ноль — «предел не задан», меры тогда не показываются.
    # Верхняя граница взята с большим запасом, она защищает от описки вроде
    # лишнего нуля, а не задаёт осмысленный потолок.
    db.set_setting("limit_5h_tokens", clamp_int(limit_5h_tokens, 0, 1_000_000_000, 0))
    db.set_setting("limit_week_tokens", clamp_int(limit_week_tokens, 0, 1_000_000_000, 0))

    return RedirectResponse(request.url_for("settings_page"), status_code=303)


@router.post("/settings/file", name="settings_file_save")
def settings_file_save(request: Request, name: str = Form(...), content: str = Form(...)):
    user, redirect = _guard(request)
    if redirect:
        return redirect

    path = _support_path(name)
    if not path:
        return JSONResponse({"error": "недопустимое имя файла"}, status_code=400)

    # Перевод строк приводим к unix: правка через textarea в браузере даёт CRLF
    text = content.replace("\r\n", "\n").replace("\r", "\n")
    path.write_text(text, encoding="utf-8")
    return RedirectResponse(
        str(request.url_for("settings_page")) + f"?file={name}&saved=1", status_code=303
    )


@router.post("/settings/sessions/{session_id}/close", name="settings_session_close")
def settings_session_close(request: Request, session_id: str):
    user, redirect = _guard(request)
    if redirect:
        return redirect
    db.execute(
        "DELETE FROM sessions WHERE id = %s AND user_id = %s", (session_id, user["id"])
    )
    if session_id == user["session_id"]:
        return RedirectResponse(request.url_for("login_form"), status_code=303)
    return RedirectResponse(request.url_for("settings_page"), status_code=303)


@router.post("/settings/restart", name="settings_restart")
async def settings_restart(request: Request):
    """Ставит перезапуск приложения в очередь.

    Служба не останавливается сразу: сперва дописываются выполняющиеся ответы,
    иначе остановка оборвала бы их вместе с проделанной работой — см.
    `services/restart.py`.
    """
    user, redirect = _guard(request)
    if redirect:
        return JSONResponse({"error": "нет доступа"}, status_code=401)
    return JSONResponse(restart.request(user["login"]).as_dict())


@router.get("/settings/restart/state", name="settings_restart_state")
def settings_restart_state(request: Request):
    """Состояние перезапуска для опроса из браузера."""
    if not current_user(request):
        return JSONResponse({"error": "нет доступа"}, status_code=401)
    return JSONResponse(restart.current().as_dict())


@router.get("/export/{conversation_id}", name="export_conversation")
def export_conversation(request: Request, conversation_id: int):
    """Экспорт диалога в markdown — чтобы итог можно было положить в result.md."""
    if not current_user(request):
        return RedirectResponse(request.url_for("login_form"), status_code=303)

    conv = db.query_one(
        """
        SELECT c.id, c.title, c.kind, c.created_at, p.name AS project_name
        FROM conversations c LEFT JOIN projects p ON p.id = c.project_id
        WHERE c.id = %s
        """,
        (conversation_id,),
    )
    if not conv:
        return PlainTextResponse("Диалог не найден", status_code=404)

    rows = db.query(
        "SELECT role, content, created_at, cost_usd, model FROM messages "
        "WHERE conversation_id = %s ORDER BY id",
        (conversation_id,),
    )

    tz = timefmt.zone()
    lines = [f"# {conv['title']}", ""]
    if conv["project_name"]:
        lines.append(f"Проект: {conv['project_name']}")
    lines.append(f"Начат: {timefmt.fmt(conv['created_at'], tz=tz)} ({timefmt.offset_text(tz)})")
    lines += ["", "---", ""]

    names = {"user": "Светлана", "assistant": "Claude", "error": "Ошибка"}
    total = 0.0
    for row in rows:
        total += float(row["cost_usd"] or 0)
        lines.append(f"## {names.get(row['role'], row['role'])} — {timefmt.fmt(row['created_at'], tz=tz)}")
        lines.append("")
        lines.append(row["content"])
        lines.append("")

    lines += ["---", "", f"Расход по диалогу: ${total:.4f}"]
    body = "\n".join(lines)

    filename = f"dialog_{conversation_id}.md"
    return PlainTextResponse(
        body,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/journal", name="journal")
def journal(request: Request):
    """log.md в виде ленты задач — идея 4."""
    user, redirect = _guard(request)
    if redirect:
        return redirect

    path = config.REPO_ROOT / "log.md"
    entries = []
    if path.is_file():
        text = path.read_text(encoding="utf-8")
        chunks = text.split("\n## ")
        for chunk in chunks[1:]:
            head, _, body = chunk.partition("\n")
            status = ""
            for line in body.splitlines():
                if line.startswith("**Статус:**"):
                    status = line.replace("**Статус:**", "").strip()
                    break
            entries.append({"title": head.strip(), "status": status, "body": body.strip()})

    return render(
        request,
        "journal.html",
        {"user": user, "active": "journal", "entries": entries},
    )
