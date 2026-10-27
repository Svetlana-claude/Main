"""Вкладка «Чат»: разговоры, ответ потоком в фоне, дописка, поиск."""
import asyncio
import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse

from . import claude, config, db, markup
from .web import csrf_ok, current, guarded, page, to

router = APIRouter()

TITLE_LEN = 60


# ── Фоновый ответ ────────────────────────────────────────────────────────

class Run:
    """Один запуск Claude на разговор. Живёт в памяти сайта, не зависит от
    открытой страницы: ушла — ответ дописывается, вернулась — подхватывается."""

    def __init__(self, conv_id: int):
        self.conv_id = conv_id
        self.proc: asyncio.subprocess.Process | None = None
        self.text = ""                 # текст текущего хода, пока он пишется
        self.pending: list[str] = []   # дописки: в базу — после ответа, к которому пришли
        self.sent = 0                  # сколько сообщений отдано запуску
        self.turns = 0                 # сколько ходов закончено
        self.open = True               # принимает ли запуск дописки
        self.lock = asyncio.Lock()
        self.listeners: set[asyncio.Queue] = set()
        self.stderr: list[str] = []

    def tell(self, event: dict) -> None:
        for queue in list(self.listeners):
            queue.put_nowait(event)

    async def begin(self, text: str, model: str, session_id: str | None) -> None:
        self.proc = await claude.start(model, session_id)
        self.proc.stdin.write(claude.user_line(text))
        await self.proc.stdin.drain()
        self.sent = 1
        asyncio.create_task(self._read_stderr())
        asyncio.create_task(self._work())

    async def add(self, text: str) -> bool:
        """Дописка в идущий ответ. False — запуск уже закрывается."""
        async with self.lock:
            if not self.open or self.proc.stdin.is_closing():
                return False
            self.proc.stdin.write(claude.user_line(text))
            await self.proc.stdin.drain()
            self.sent += 1
            self.pending.append(text)
        self.tell({"t": "added"})
        return True

    async def _read_stderr(self) -> None:
        async for raw in claude._lines(self.proc.stderr):
            line = raw.decode("utf-8", "replace").strip()
            if line:
                self.stderr = (self.stderr + [line])[-5:]

    def _flush_pending(self) -> None:
        for text in self.pending:
            save_message(self.conv_id, "user", text)
        self.pending.clear()

    async def _work(self) -> None:
        try:
            async for ev in claude.events(self.proc):
                if ev["type"] == "init" and ev["session_id"]:
                    db.run("UPDATE conversations SET session_id = ? WHERE id = ?",
                           (ev["session_id"], self.conv_id))
                elif ev["type"] == "delta":
                    self.text += ev["text"]
                    self.tell({"t": "delta", "x": ev["text"]})
                elif ev["type"] == "turn":
                    async with self.lock:
                        text = ev["text"] or self.text
                        if ev["is_error"]:
                            save_message(self.conv_id, "error", "Не получилось ответить: " + (text or "ошибка"))
                        else:
                            save_message(self.conv_id, "assistant", text)
                        db.run("UPDATE conversations SET context_tokens = ?, "
                               "session_id = COALESCE(?, session_id) WHERE id = ?",
                               (ev["context"], ev["session_id"], self.conv_id))
                        self._flush_pending()
                        self.text = ""
                        self.turns += 1
                        if self.turns >= self.sent:
                            self.open = False
                            self.proc.stdin.close()
                    self.tell({"t": "saved"})
            await self.proc.wait()
        except asyncio.TimeoutError:
            self.proc.kill()
        except Exception as exc:                       # noqa: BLE001
            self.stderr.append(str(exc))
        finally:
            async with self.lock:
                self.open = False
                if self.proc.returncode is None:
                    self.proc.kill()
                if self.turns < self.sent:
                    if self.text:
                        save_message(self.conv_id, "assistant", self.text)
                    why = self.stderr[-1] if self.stderr else "ответ оборвался"
                    save_message(self.conv_id, "error", "Не получилось ответить: " + why)
                self._flush_pending()
            RUNS.pop(self.conv_id, None)
            self.tell({"t": "done"})


RUNS: dict[int, Run] = {}


def active_runs() -> int:
    """Сколько ответов пишется сейчас (для перезапуска сайта)."""
    return len(RUNS)


# ── База ─────────────────────────────────────────────────────────────────

def save_message(conv_id: int, role: str, text: str) -> int:
    stamp = db.now()
    mid = db.insert("INSERT INTO messages (conv_id, role, text, norm, created_at) VALUES (?, ?, ?, ?, ?)",
                    (conv_id, role, text, db.norm(text), stamp))
    db.run("UPDATE conversations SET updated_at = ? WHERE id = ?", (stamp, conv_id))
    return mid


def make_title(text: str) -> str:
    text = " ".join(text.split())
    if len(text) <= TITLE_LEN:
        return text
    cut = text[:TITLE_LEN].rsplit(" ", 1)[0] or text[:TITLE_LEN]
    return cut.rstrip(" ,.;:—-") + "…"


def conversations() -> list[dict]:
    return db.rows("SELECT id, title, updated_at FROM conversations ORDER BY updated_at DESC, id DESC")


def conversation(conv_id: int) -> dict | None:
    return db.one("SELECT * FROM conversations WHERE id = ?", (conv_id,))


def weight(tokens: int) -> str:
    if tokens < 1000:
        return "лёгкая"
    return f"{round(tokens / 1000)} тыс."


def suggest_new(conv: dict) -> bool:
    """Беседа большая и давно молчала — дешевле начать новую."""
    if conv["context_tokens"] < config.BIG_CONTEXT:
        return False
    quiet = datetime.now(timezone.utc) - datetime.fromisoformat(conv["updated_at"])
    return quiet > timedelta(hours=config.QUIET_HOURS)


def feed(conv_id: int, count: int) -> tuple[list[dict], bool]:
    rows = db.rows("SELECT id, role, text, created_at FROM messages WHERE conv_id = ? "
                   "ORDER BY id DESC LIMIT ?", (conv_id, count + 1))
    more = len(rows) > count
    rows = list(reversed(rows[:count]))
    for row in rows:
        row["html"] = markup.render(row["text"]) if row["role"] == "assistant" else None
    return rows, more


def feed_ctx(conv: dict, count: int) -> dict:
    messages, more = feed(conv["id"], count)
    run = RUNS.get(conv["id"])
    return {"conv": conv, "messages": messages, "more": more, "count": count,
            "running": bool(run), "live_text": run.text if run else "",
            "pending": list(run.pending) if run else []}


# ── Страницы ─────────────────────────────────────────────────────────────

def _count(raw: str | None) -> int:
    try:
        return max(config.PAGE_MESSAGES, min(int(raw or 0), 10_000))
    except ValueError:
        return config.PAGE_MESSAGES


@router.get("/chat", name="chat")
def chat_home(request: Request):
    """Открывается последний разговор; разговоров нет — пустой экран."""
    sess = current(request)
    if sess and not sess["locked"]:
        last = db.one("SELECT id FROM conversations ORDER BY updated_at DESC, id DESC LIMIT 1")
        if last:
            return to_conv(request, last["id"])
    return guarded(request, "chat.html", "chat", {"title": "Чат", "convs": conversations(),
                                                  "conv": None, "models": config.MODELS})


def to_conv(request: Request, conv_id: int):
    return RedirectResponse(str(request.url_for("conv", conv_id=conv_id)), status_code=303)


@router.get("/chat/{conv_id}", name="conv")
def conv_page(request: Request, conv_id: int, n: str | None = None):
    conv = conversation(conv_id)
    if not conv:
        return to(request, "chat")
    ctx = feed_ctx(conv, _count(n))
    ctx.update(title=conv["title"] or "Новый разговор", convs=conversations(), models=config.MODELS,
               weight=weight(conv["context_tokens"]), suggest_new=suggest_new(conv))
    return guarded(request, "chat.html", "chat", ctx)


@router.get("/chat/{conv_id}/feed", name="conv_feed")
def conv_feed(request: Request, conv_id: int, n: str | None = None):
    sess = current(request)
    conv = conversation(conv_id)
    if not sess or sess["locked"] or not conv:
        return JSONResponse({"error": "нет доступа"}, status_code=403)
    ctx = feed_ctx(conv, _count(n))
    return JSONResponse({
        "html": page(request, "_feed.html", ctx).body.decode(),
        "title": conv["title"] or "Новый разговор",
        "weight": weight(conv["context_tokens"]),
        "running": ctx["running"],
    }, headers={"Cache-Control": "no-store"})


def _allowed(request: Request, csrf: str) -> dict | None:
    sess = current(request)
    if sess and not sess["locked"] and csrf_ok(request, sess, csrf):
        return sess
    return None


@router.post("/chat/new", name="chat_new")
def chat_new(request: Request, csrf: str = Form("")):
    if not _allowed(request, csrf):
        return to(request, "chat")
    # Пустые разговоры не копятся: прежний пустой заменяется новым
    db.run("DELETE FROM conversations WHERE NOT EXISTS "
           "(SELECT 1 FROM messages m WHERE m.conv_id = conversations.id)")
    stamp = db.now()
    conv_id = db.insert("INSERT INTO conversations (model, created_at, updated_at) VALUES (?, ?, ?)",
                        (config.DEFAULT_MODEL, stamp, stamp))
    return to_conv(request, conv_id)


@router.post("/chat/{conv_id}/send", name="conv_send")
async def conv_send(request: Request, conv_id: int, text: str = Form(""), csrf: str = Form("")):
    if not _allowed(request, csrf):
        return JSONResponse({"error": "Нет доступа — обнови страницу"}, status_code=403)
    conv = conversation(conv_id)
    text = text.strip()
    if not conv:
        return JSONResponse({"error": "Разговор не найден"}, status_code=404)
    if not text:
        return JSONResponse({"error": "Пустое сообщение"}, status_code=400)
    run = RUNS.get(conv_id)
    if run and await run.add(text):
        return JSONResponse({"ok": True, "mode": "append"})
    if run:
        # Запуск как раз закрывается: дождаться его конца и начать новый
        for _ in range(100):
            if conv_id not in RUNS:
                break
            await asyncio.sleep(0.1)
    if not conv["title"]:
        db.run("UPDATE conversations SET title = ? WHERE id = ?", (make_title(text), conv_id))
    save_message(conv_id, "user", text)
    run = Run(conv_id)
    RUNS[conv_id] = run
    try:
        await run.begin(text, conv["model"], conv["session_id"])
    except Exception:                                  # noqa: BLE001
        RUNS.pop(conv_id, None)
        save_message(conv_id, "error", "Не получилось запустить Claude")
        return JSONResponse({"ok": False, "mode": "failed"})
    return JSONResponse({"ok": True, "mode": "new"})


@router.get("/chat/{conv_id}/stream", name="conv_stream")
async def conv_stream(request: Request, conv_id: int):
    sess = current(request)
    if not sess or sess["locked"]:
        return JSONResponse({"error": "нет доступа"}, status_code=403)

    async def gen():
        run = RUNS.get(conv_id)
        if not run:
            yield _sse({"t": "done"})
            return
        queue: asyncio.Queue = asyncio.Queue()
        run.listeners.add(queue)
        try:
            yield _sse({"t": "snapshot", "x": run.text})
            while True:
                try:
                    ev = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": жив\n\n"
                    continue
                yield _sse(ev)
                if ev["t"] == "done":
                    return
        finally:
            run.listeners.discard(queue)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


@router.post("/chat/{conv_id}/model", name="conv_model")
def conv_model(request: Request, conv_id: int, model: str = Form(""), csrf: str = Form("")):
    if _allowed(request, csrf) and model in config.MODELS:
        db.run("UPDATE conversations SET model = ? WHERE id = ?", (model, conv_id))
    return to_conv(request, conv_id)


@router.post("/chat/{conv_id}/rename", name="conv_rename")
def conv_rename(request: Request, conv_id: int, title: str = Form(""), csrf: str = Form("")):
    title = " ".join(title.split())[:120]
    if _allowed(request, csrf) and title:
        db.run("UPDATE conversations SET title = ? WHERE id = ?", (title, conv_id))
    return to_conv(request, conv_id)


@router.post("/chat/{conv_id}/delete", name="conv_delete")
def conv_delete(request: Request, conv_id: int, csrf: str = Form("")):
    if _allowed(request, csrf):
        run = RUNS.pop(conv_id, None)
        if run and run.proc and run.proc.returncode is None:
            run.proc.kill()
        db.run("DELETE FROM conversations WHERE id = ?", (conv_id,))
    return to(request, "chat")


# ── Поиск ────────────────────────────────────────────────────────────────

@router.get("/search", name="search")
def search(request: Request, q: str = ""):
    words = db.norm(q).split()[:10]
    results: list[dict] = []
    if words:
        where = " AND ".join("instr(m.norm, ?) > 0" for _ in words)
        results = db.rows(
            "SELECT m.id, m.conv_id, m.role, m.text, m.created_at, c.title "
            f"FROM messages m JOIN conversations c ON c.id = m.conv_id WHERE {where} "
            "ORDER BY m.id DESC LIMIT 100", tuple(words))
        for row in results:
            row["snippet"] = snippet(row["text"], words)
    return guarded(request, "search.html", "chat", {"title": "Поиск", "q": q, "results": results,
                                                    "searched": bool(words)})


def snippet(text: str, words: list[str], width: int = 160) -> str:
    """Кусок текста вокруг первого найденного слова."""
    low = db.norm(text)
    at = min((low.find(w) for w in words if low.find(w) >= 0), default=0)
    start = max(0, at - width // 3)
    part = " ".join(text[start:start + width].split())
    return ("…" if start else "") + part + ("…" if start + width < len(text) else "")
