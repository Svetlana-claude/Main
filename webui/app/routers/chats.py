"""Чатики: болтовня на отвлечённые темы. Инструменты выключены."""

from fastapi import APIRouter, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse

from .. import db
from ..deps import current_user, render
from ..services import claude_driver, runs

router = APIRouter()


def _guard(request: Request):
    user = current_user(request)
    if not user:
        return None, RedirectResponse(request.url_for("login_form"), status_code=303)
    if user["must_change"]:
        return None, RedirectResponse(request.url_for("change_password_form"), status_code=303)
    return user, None


def _chat_list() -> list[dict]:
    return db.query(
        """
        SELECT c.id, c.title, c.updated_at,
               (SELECT count(*) FROM messages m WHERE m.conversation_id = c.id) AS msg_count
        FROM conversations c
        WHERE c.kind = 'chat'
        ORDER BY c.updated_at DESC
        """
    )


@router.get("/chats", name="chats")
def chats(request: Request, id: int | None = None):
    user, redirect = _guard(request)
    if redirect:
        return redirect

    items = _chat_list()
    current = None
    messages: list[dict] = []

    if id is not None:
        current = db.query_one(
            "SELECT id, title, claude_session_id FROM conversations "
            "WHERE id = %s AND kind = 'chat'",
            (id,),
        )
    elif items:
        current = db.query_one(
            "SELECT id, title, claude_session_id FROM conversations WHERE id = %s",
            (items[0]["id"],),
        )

    if current:
        messages = db.query(
            """
            SELECT role, content, created_at, cost_usd, duration_ms,
                   input_tokens, output_tokens, model
            FROM messages WHERE conversation_id = %s ORDER BY id
            """,
            (current["id"],),
        )

    return render(
        request,
        "chats.html",
        {
            "user": user,
            "active": "chats",
            "items": items,
            "current": current,
            "messages": messages,
        },
    )


@router.post("/chats/new", name="chat_new")
def chat_new(request: Request):
    user, redirect = _guard(request)
    if redirect:
        return redirect
    row = db.query_one(
        "INSERT INTO conversations (kind, title) VALUES ('chat', %s) RETURNING id",
        ("Новый чат",),
    )
    return RedirectResponse(
        str(request.url_for("chats")) + f"?id={row['id']}", status_code=303
    )


@router.post("/chats/{chat_id}/delete", name="chat_delete")
def chat_delete(request: Request, chat_id: int):
    user, redirect = _guard(request)
    if redirect:
        return redirect
    db.execute("DELETE FROM conversations WHERE id = %s AND kind = 'chat'", (chat_id,))
    return RedirectResponse(request.url_for("chats"), status_code=303)


@router.post("/chats/{chat_id}/rename", name="chat_rename")
def chat_rename(request: Request, chat_id: int, title: str = Form(...)):
    user, redirect = _guard(request)
    if redirect:
        return redirect
    clean = " ".join(title.split())[:120] or "Без названия"
    db.execute(
        "UPDATE conversations SET title = %s WHERE id = %s AND kind = 'chat'",
        (clean, chat_id),
    )
    return RedirectResponse(
        str(request.url_for("chats")) + f"?id={chat_id}", status_code=303
    )


@router.post("/chats/{chat_id}/send", name="chat_send")
async def chat_send(request: Request, chat_id: int, text: str = Form(...)):
    """Отправка сообщения. Ответ идёт потоком через SSE."""
    user = current_user(request)
    if not user or user["must_change"]:
        return JSONResponse({"error": "нет доступа"}, status_code=401)

    conv = db.query_one(
        "SELECT id, title, claude_session_id FROM conversations "
        "WHERE id = %s AND kind = 'chat'",
        (chat_id,),
    )
    if not conv:
        return JSONResponse({"error": "чат не найден"}, status_code=404)

    prompt = text.strip()
    if not prompt:
        return JSONResponse({"error": "пустое сообщение"}, status_code=400)

    # Проверка до записи вопроса: иначе при отказе вопрос остался бы в ленте
    # висеть без ответа, и выглядело бы это как потерянное сообщение.
    if runs.active("chat", chat_id):
        return JSONResponse({"error": "в этом чатике уже идёт ответ"}, status_code=409)

    db.execute(
        "INSERT INTO messages (conversation_id, role, content) VALUES (%s, 'user', %s)",
        (chat_id, prompt),
    )
    db.execute("UPDATE conversations SET updated_at = now() WHERE id = %s", (chat_id,))

    settings = db.get_settings()
    model = settings.get("model", "opus")
    first_message = conv["title"] == "Новый чат"

    async def producer(run):
        """Работа движка. Идёт в задаче приложения и о браузере не знает."""
        async for event in claude_driver.run(
            prompt,
            model=model,
            session_id=conv["claude_session_id"],
            with_tools=False,
        ):
            if event["type"] == "result":
                _save_answer(chat_id, event)
            elif event["type"] == "error":
                db.execute(
                    "INSERT INTO messages (conversation_id, role, content) "
                    "VALUES (%s, 'error', %s)",
                    (chat_id, event["message"]),
                )
            await run.append(event)

        # Название по первой реплике: «Новый чат» через неделю ничего не скажет
        if first_message:
            title = await claude_driver.make_title(prompt)
            db.execute(
                "UPDATE conversations SET title = %s WHERE id = %s", (title, chat_id)
            )
            await run.append({"type": "title", "title": title})

    runs.start("chat", chat_id, producer)
    # Ответ отдаётся сразу: за событиями страница приходит отдельно, и уход
    # с неё работу больше не обрывает.
    return JSONResponse({"ok": True})


@router.get("/chats/{chat_id}/stream", name="chat_stream")
async def chat_stream(request: Request, chat_id: int, start: int = 0, active: int = 0):
    """События идущего ответа, начиная с позиции `start`."""
    user = current_user(request)
    if not user or user["must_change"]:
        return JSONResponse({"error": "нет доступа"}, status_code=401)

    return StreamingResponse(
        runs.sse(runs.get("chat", chat_id), start, only_active=bool(active)),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _save_answer(conversation_id: int, event: dict) -> None:
    """Сохраняет ответ вместе с расходом — из этого потом собирается дашборд."""
    db.execute(
        """
        INSERT INTO messages (conversation_id, role, content, model,
                              input_tokens, output_tokens, cache_read, cache_write,
                              cost_usd, duration_ms, num_turns)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            conversation_id,
            "error" if event.get("is_error") else "assistant",
            event.get("text") or event.get("error_message") or "(пустой ответ)",
            event.get("model"),
            event.get("input_tokens", 0),
            event.get("output_tokens", 0),
            event.get("cache_read", 0),
            event.get("cache_write", 0),
            event.get("cost_usd", 0),
            event.get("duration_ms", 0),
            event.get("num_turns", 0),
        ),
    )
    if event.get("session_id"):
        db.execute(
            "UPDATE conversations SET claude_session_id = %s, updated_at = now() "
            "WHERE id = %s",
            (event["session_id"], conversation_id),
        )


@router.get("/search", name="search")
def search(request: Request, q: str = ""):
    """Полнотекстовый поиск по всем диалогам."""
    user, redirect = _guard(request)
    if redirect:
        return redirect

    results: list[dict] = []
    query = q.strip()
    if query:
        results = db.query(
            """
            SELECT m.id, m.role, m.created_at, c.id AS conv_id, c.kind, c.title,
                   p.name AS project_name,
                   ts_headline('russian', m.content, websearch_to_tsquery('russian', %s),
                               'MaxFragments=2, MaxWords=22, MinWords=6') AS excerpt
            FROM messages m
            JOIN conversations c ON c.id = m.conversation_id
            LEFT JOIN projects p ON p.id = c.project_id
            WHERE m.content_tsv @@ websearch_to_tsquery('russian', %s)
            ORDER BY ts_rank(m.content_tsv, websearch_to_tsquery('russian', %s)) DESC,
                     m.created_at DESC
            LIMIT 60
            """,
            (query, query, query),
        )

    return render(
        request,
        "search.html",
        {"user": user, "active": "search", "q": query, "results": results},
    )
