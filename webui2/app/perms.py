"""Разрешения и кружки.

Claude в теме просит то, что галочки проекта не разрешают, — запрос ложится
в базу и ждёт хозяйку на странице «Разрешения». Нет ответа за 25 минут —
отказ. Кружки у разговоров, тем и проектов показывают, кто работает, кто ждёт
разрешения, а кто свободен; страница сверяет их с сайтом сама."""
import asyncio

from fastapi import APIRouter, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse

from . import claude, config, db
from .web import csrf_ok, current, guarded, templates, to

router = APIRouter()

WAIT_SEC = 25 * 60
HISTORY = 50

ASKING = "Жду твоего разрешения — щит вверху…"
DENIED = "Светлана запретила это действие. Не обходи запрет другим способом."
LATE = "Светлана не ответила за 25 минут — считай, что запрещено."

STATES = {"wait": "ждёт", "yes": "разрешено", "no": "запрещено",
          "late": "нет ответа за 25 минут — отказ", "gone": "ответ оборвался — вопрос снят"}

# Ждущие запросы: номер в базе → ответ (True — разрешено)
_waiters: dict[int, asyncio.Future] = {}


def _place(conv_id: int) -> tuple[int | None, str]:
    """Проект и подпись «где спрашивают» — на память, если тему потом удалят."""
    row = db.one("SELECT c.title, c.project_id, p.name FROM conversations c "
                 "LEFT JOIN projects p ON p.id = c.project_id WHERE c.id = ?", (conv_id,))
    if not row:
        return None, ""
    title = row["title"] or "Новая тема"
    return row["project_id"], f"{row['name']} · {title}" if row["name"] else title


def open_request(conv_id: int, request_id: str, tool: str, data: dict) -> int:
    project_id, place = _place(conv_id)
    what, detail = claude.ask_text(tool, data)
    pid = db.insert(
        "INSERT INTO permissions (conv_id, project_id, request_id, place, tool, what, detail, "
        "state, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'wait', ?)",
        (conv_id, project_id, request_id, place, tool, what, detail, db.now()))
    _waiters[pid] = asyncio.get_running_loop().create_future()
    return pid


async def wait(pid: int) -> tuple[bool, str]:
    """Ответ хозяйки: (разрешено ли, что сказать Claude при отказе)."""
    future = _waiters.get(pid)
    if future is None:
        return False, LATE
    try:
        allow = await asyncio.wait_for(asyncio.shield(future), timeout=WAIT_SEC)
        return allow, "" if allow else DENIED
    except asyncio.TimeoutError:
        _close(pid, "late")
        return False, LATE
    finally:
        _waiters.pop(pid, None)


def _close(pid: int, state: str) -> bool:
    """Закрыть запрос, если он ещё ждёт. Решает тот, кто успел первым."""
    with db.tx() as con:
        done = con.execute("UPDATE permissions SET state = ?, decided_at = ? WHERE id = ? AND state = 'wait'",
                           (state, db.now(), pid)).rowcount
    future = _waiters.get(pid)
    if done and future and not future.done():
        future.set_result(state == "yes")
    return bool(done)


def decide(pid: int, allow: bool) -> bool:
    return _close(pid, "yes" if allow else "no")


def cancel(conv_id: int, request_id: str | None = None) -> None:
    """Вопрос снят: Claude передумал или ответ оборвался."""
    sql, args = "SELECT id FROM permissions WHERE conv_id = ? AND state = 'wait'", (conv_id,)
    if request_id is not None:
        sql, args = sql + " AND request_id = ?", (conv_id, request_id)
    for row in db.rows(sql, args):
        _close(row["id"], "gone")


def waiting() -> list[dict]:
    return db.rows("SELECT * FROM permissions WHERE state = 'wait' ORDER BY id")


def history() -> list[dict]:
    return db.rows("SELECT * FROM permissions WHERE state <> 'wait' ORDER BY decided_at DESC, id DESC "
                   "LIMIT ?", (HISTORY,))


def count() -> int:
    return db.one("SELECT COUNT(*) AS n FROM permissions WHERE state = 'wait'")["n"]


# ── Кружки ───────────────────────────────────────────────────────────────

LIGHT_TEXT = {"free": "Свободен", "busy": "Работает", "wait": "Ждёт разрешения"}


def lights() -> dict:
    """Кто не свободен: {"c": {разговор: busy|wait}, "p": {проект: …}}.
    Кого нет в списке — тот свободен (зелёный)."""
    from .chat import RUNS                             # chat.py сам опирается на этот модуль
    convs: dict[int, str] = {cid: "busy" for cid in RUNS}
    asking = db.rows("SELECT DISTINCT conv_id FROM permissions WHERE state = 'wait'")
    for row in asking:
        if row["conv_id"] in convs:
            convs[row["conv_id"]] = "wait"
    projects: dict[int, str] = {}
    if convs:
        marks = ",".join("?" * len(convs))
        for row in db.rows(f"SELECT id, project_id FROM conversations WHERE id IN ({marks}) "
                           "AND project_id IS NOT NULL", tuple(convs)):
            if projects.get(row["project_id"]) != "wait":
                projects[row["project_id"]] = convs[row["id"]]
    return {"c": convs, "p": projects}


def light(kind: str, item_id: int) -> str:
    """Кружок, нарисованный сразу на странице: состояние на момент показа."""
    return lights()[kind].get(item_id, "free")


templates.env.globals["light"] = light
templates.env.globals["light_text"] = LIGHT_TEXT
templates.env.globals["asks_waiting"] = count


@router.get("/lights", name="lights")
def lights_now(request: Request):
    sess = current(request)
    if not sess or sess["locked"]:
        return JSONResponse({"error": "нет доступа"}, status_code=403)
    return JSONResponse({"ask": count(), **lights()}, headers={"Cache-Control": "no-store"})


# ── Страница «Разрешения» ────────────────────────────────────────────────

def _link(row: dict) -> str | None:
    from .chat import conv_path, conversation
    conv = conversation(row["conv_id"]) if row["conv_id"] else None
    return config.ROOT_PATH + conv_path(conv) if conv else None


@router.get("/permissions", name="permissions")
def permissions_page(request: Request):
    asks, done = waiting(), history()
    for row in asks + done:
        row["link"] = _link(row)
        row["state_text"] = STATES.get(row["state"], row["state"])
    return guarded(request, "permissions.html", "permissions",
                   {"title": "Разрешения", "asks": asks, "done": done, "wait_min": WAIT_SEC // 60})


# async: ответ будит ждущий запуск, а это можно только из цикла событий сайта
@router.post("/permissions/{pid}/{answer}", name="permission_answer")
async def permission_answer(request: Request, pid: int, answer: str, csrf: str = Form("")):
    sess = current(request)
    if sess and not sess["locked"] and csrf_ok(request, sess, csrf) and answer in ("yes", "no"):
        decide(pid, answer == "yes")
    if not sess:
        return to(request, "login_form")
    return RedirectResponse(f"{config.ROOT_PATH}/permissions", status_code=303)
