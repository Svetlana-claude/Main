"""Работа с базой: тот же PostgreSQL, что у веб-интерфейса.

Пул асинхронный, в отличие от `webui/app/db.py`: у бота один процесс и один
цикл событий, и синхронный запрос в нём остановил бы и опрос очереди, и живую
правку «Хода работы».

Запросы к общим таблицам (`conversations`, `messages`, `projects`, `files`)
намеренно повторяют те же поля, что пишет веб-интерфейс: диалог, начатый в
Телеграме, должен открываться в браузере как свой.
"""
import logging

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from . import config

log = logging.getLogger("bot.db")

_pool: AsyncConnectionPool | None = None

# Названия состояний задачи для человека. В базе хранятся латиницей — это код,
# по которому строятся кнопки; в глаза попадает только то, что справа.
STATUSY = {
    "waiting": "ожидает решения",
    "approved": "утверждена",
    "rejected": "отклонена",
    "running": "в работе",
    "done": "выполнена",
    "failed": "сбой",
}

ZNACHKI = {
    "waiting": "❓",
    "approved": "✅",
    "rejected": "❌",
    "running": "⚙️",
    "done": "🏁",
    "failed": "⚠️",
}


async def init() -> None:
    global _pool
    if _pool is not None:
        return
    _pool = AsyncConnectionPool(
        config.DATABASE_URL,
        min_size=1,
        max_size=4,          # 2.9 ГБ ОЗУ и рядом живёт webui со своим пулом
        kwargs={"row_factory": dict_row},
        open=False,
    )
    await _pool.open()
    await apply_schema()


async def close() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def apply_schema() -> None:
    """Применяет schema.sql. Все операторы идемпотентны."""
    sql = (config.BASE_DIR / "schema.sql").read_text(encoding="utf-8")
    async with _pool.connection() as c:
        await c.execute(sql)


async def query(sql: str, params: tuple = ()) -> list[dict]:
    async with _pool.connection() as c:
        cur = await c.execute(sql, params)
        return await cur.fetchall()


async def query_one(sql: str, params: tuple = ()) -> dict | None:
    async with _pool.connection() as c:
        cur = await c.execute(sql, params)
        return await cur.fetchone()


async def execute(sql: str, params: tuple = ()) -> None:
    async with _pool.connection() as c:
        await c.execute(sql, params)


# ---------------------------------------------------------------------------
# Настройки веб-интерфейса: модель и потолок контекста общие с браузером


async def nastroyki() -> dict[str, str]:
    from app import config as webui_config

    rows = await query("SELECT key, value FROM settings")
    values = dict(webui_config.DEFAULT_SETTINGS)
    values.update({r["key"]: r["value"] for r in rows})
    return values


# ---------------------------------------------------------------------------
# Кто пишет боту


async def polzovatel(tg: dict, *, allowed: bool) -> dict:
    """Отмечает обращение и возвращает запись. Права берутся из настроек, не из базы.

    Признак `allowed` пишется из списка в файле настроек при каждом обращении:
    иначе вычеркнутый из списка остался бы с правом, выданным когда-то раньше.

    `denied_at` здесь **не трогается** — его ставит `otkaz_otmetit` в тот момент,
    когда боту пришлось ответить чужому. Если писать его при каждом обращении, по
    нему нельзя будет сказать, давно ли мы отвечали: время обращения и время
    отказа сравнивались бы сами с собой.
    """
    return await query_one(
        """
        INSERT INTO tg_users (tg_id, username, first_name, allowed, requests)
        VALUES (%s, %s, %s, %s, 1)
        ON CONFLICT (tg_id) DO UPDATE SET
            username   = EXCLUDED.username,
            first_name = EXCLUDED.first_name,
            allowed    = EXCLUDED.allowed,
            last_seen  = now(),
            requests   = tg_users.requests + 1
        RETURNING *, now() AS seychas
        """,
        (tg.get("id"), tg.get("username"), tg.get("first_name"), allowed),
    )


async def otkaz_otmetit(tg_id: int) -> None:
    """Запомнить, что чужому уже отвечено: следующий раз — не раньше чем через час."""
    await execute("UPDATE tg_users SET denied_at = now() WHERE tg_id = %s", (tg_id,))


# ---------------------------------------------------------------------------
# Привязка чата к диалогу


async def privyazka(chat_id: int) -> dict:
    """Текущая привязка чата. Создаётся при первом обращении."""
    row = await query_one("SELECT * FROM tg_binding WHERE chat_id = %s", (chat_id,))
    if row:
        return row
    # ON CONFLICT, а не просто INSERT: два сообщения подряд разбираются двумя
    # задачами, и обе доходят сюда до того, как запись появится
    return await query_one(
        "INSERT INTO tg_binding (chat_id) VALUES (%s) "
        "ON CONFLICT (chat_id) DO UPDATE SET chat_id = EXCLUDED.chat_id RETURNING *",
        (chat_id,),
    )


async def privyazat(chat_id: int, conversation_id: int | None) -> None:
    await execute(
        "INSERT INTO tg_binding (chat_id, conversation_id) VALUES (%s, %s) "
        "ON CONFLICT (chat_id) DO UPDATE SET conversation_id = EXCLUDED.conversation_id, "
        "updated_at = now()",
        (chat_id, conversation_id),
    )


async def rezhim(chat_id: int, mode: str) -> None:
    await execute(
        "INSERT INTO tg_binding (chat_id, mode) VALUES (%s, %s) "
        "ON CONFLICT (chat_id) DO UPDATE SET mode = EXCLUDED.mode, updated_at = now()",
        (chat_id, mode),
    )


# ---------------------------------------------------------------------------
# Диалоги и сообщения — общие с веб-интерфейсом


async def dialog(conversation_id: int) -> dict | None:
    return await query_one(
        """
        SELECT c.*, p.name AS project_name, p.workdir, p.allow_bash
          FROM conversations c
          LEFT JOIN projects p ON p.id = c.project_id
         WHERE c.id = %s
        """,
        (conversation_id,),
    )


async def novyy_dialog(title: str, project_id: int | None = None) -> dict:
    """Новый диалог: без проекта — чатик, с проектом — тема со доступом к каталогу."""
    kind = "topic" if project_id else "chat"
    return await query_one(
        "INSERT INTO conversations (kind, project_id, title) VALUES (%s, %s, %s) "
        "RETURNING *",
        (kind, project_id, title[:200]),
    )


async def pereimenovat(conversation_id: int, title: str) -> None:
    await execute(
        "UPDATE conversations SET title = %s WHERE id = %s", (title[:200], conversation_id)
    )


async def posledniy_dialog(project_id: int) -> dict | None:
    """Самая свежая тема проекта — чтобы переключение не плодило пустых тем."""
    return await query_one(
        "SELECT * FROM conversations WHERE kind = 'topic' AND project_id = %s "
        "ORDER BY updated_at DESC LIMIT 1",
        (project_id,),
    )


async def soobshchenie_polzovatelya(conversation_id: int, text: str) -> None:
    await execute(
        "INSERT INTO messages (conversation_id, role, content) VALUES (%s, 'user', %s)",
        (conversation_id, text),
    )


async def soobshchenie_otveta(conversation_id: int, itog: dict) -> None:
    """Ответ движка и расход по нему. Поля — те же, что пишет веб-интерфейс."""
    await execute(
        """
        INSERT INTO messages (conversation_id, role, content, model, input_tokens,
                              output_tokens, cache_read, cache_write, cost_usd,
                              duration_ms, num_turns)
        VALUES (%s, 'assistant', %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            conversation_id,
            itog.get("text") or "",
            itog.get("model"),
            itog.get("input_tokens") or 0,
            itog.get("output_tokens") or 0,
            itog.get("cache_read") or 0,
            itog.get("cache_write") or 0,
            itog.get("cost_usd") or 0,
            itog.get("duration_ms") or 0,
            itog.get("num_turns") or 0,
        ),
    )
    await execute(
        "UPDATE conversations SET updated_at = now(), claude_session_id = COALESCE(%s, claude_session_id), "
        "context_tokens = %s, context_at = now() WHERE id = %s",
        (itog.get("session_id"), itog.get("context_tokens") or 0, conversation_id),
    )


async def soobshchenie_oshibki(conversation_id: int, text: str) -> None:
    await execute(
        "INSERT INTO messages (conversation_id, role, content) VALUES (%s, 'error', %s)",
        (conversation_id, text),
    )
    await execute("UPDATE conversations SET updated_at = now() WHERE id = %s",
                  (conversation_id,))


# ---------------------------------------------------------------------------
# Проекты


async def proekty() -> list[dict]:
    return await query(
        "SELECT * FROM projects WHERE NOT archived ORDER BY name"
    )


async def proekt(project_id: int) -> dict | None:
    return await query_one("SELECT * FROM projects WHERE id = %s", (project_id,))


# ---------------------------------------------------------------------------
# Файлы


async def fayl_dobavit(
    project_id: int, conversation_id: int | None, filename: str,
    stored_name: str, size: int, mime: str | None,
) -> int:
    row = await query_one(
        "INSERT INTO files (project_id, conversation_id, filename, stored_name, "
        "size_bytes, mime) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
        (project_id, conversation_id, filename, stored_name, size, mime),
    )
    return row["id"]


async def fayly_posledniye(project_id: int, limit: int = 10) -> list[dict]:
    return await query(
        "SELECT * FROM files WHERE project_id = %s ORDER BY created_at DESC LIMIT %s",
        (project_id, limit),
    )


# ---------------------------------------------------------------------------
# Задачи


async def zadacha_sozdat(
    *, title: str, body: str, project_id: int | None, conversation_id: int | None,
    created_by: int | None, chat_id: int | None,
) -> dict:
    return await query_one(
        "INSERT INTO tasks (title, body, project_id, conversation_id, created_by, chat_id) "
        "VALUES (%s, %s, %s, %s, %s, %s) RETURNING *",
        (title[:200], body, project_id, conversation_id, created_by, chat_id),
    )


async def zadacha(task_id: int) -> dict | None:
    return await query_one(
        "SELECT t.*, p.name AS project_name, p.workdir, p.allow_bash "
        "FROM tasks t LEFT JOIN projects p ON p.id = t.project_id WHERE t.id = %s",
        (task_id,),
    )


async def zadacha_plan(task_id: int, plan: str) -> None:
    await execute("UPDATE tasks SET plan = %s WHERE id = %s", (plan, task_id))


async def zadacha_soobshchenie(task_id: int, message_id: int) -> None:
    await execute("UPDATE tasks SET message_id = %s WHERE id = %s", (message_id, task_id))


async def zadacha_status(
    task_id: int, status: str, *, note: str | None = None, result_text: str | None = None
) -> None:
    await execute(
        """
        UPDATE tasks SET
            status      = %s,
            note        = COALESCE(%s, note),
            result_text = COALESCE(%s, result_text),
            decided_at  = CASE WHEN %s IN ('approved', 'rejected') THEN now() ELSE decided_at END,
            done_at     = CASE WHEN %s IN ('done', 'failed') THEN now() ELSE done_at END
         WHERE id = %s
        """,
        (status, note, result_text, status, status, task_id),
    )


async def zadachi(limit: int = 10, status: str | None = None) -> list[dict]:
    if status:
        return await query(
            "SELECT t.*, p.name AS project_name FROM tasks t "
            "LEFT JOIN projects p ON p.id = t.project_id "
            "WHERE t.status = %s ORDER BY t.created_at DESC LIMIT %s",
            (status, limit),
        )
    # Незакрытые сверху: ожидающие решения нужны раньше истории
    return await query(
        "SELECT t.*, p.name AS project_name FROM tasks t "
        "LEFT JOIN projects p ON p.id = t.project_id "
        "ORDER BY (t.status IN ('waiting', 'approved', 'running')) DESC, "
        "t.created_at DESC LIMIT %s",
        (limit,),
    )


# ---------------------------------------------------------------------------
# Смещение очереди обновлений


async def smeshchenie() -> int:
    row = await query_one("SELECT value FROM tg_offset WHERE id = 1")
    return int(row["value"]) if row else 0


async def smeshchenie_zapisat(value: int) -> None:
    await execute("UPDATE tg_offset SET value = %s WHERE id = 1", (value,))


# ---------------------------------------------------------------------------
# Сводка для /status


async def rashod_za_sutki() -> dict:
    row = await query_one(
        """
        SELECT count(*) AS otvetov,
               COALESCE(sum(input_tokens + output_tokens), 0) AS tokenov,
               COALESCE(sum(cost_usd), 0) AS stoimost
          FROM messages
         WHERE role = 'assistant' AND created_at > now() - interval '24 hours'
        """
    )
    return row or {"otvetov": 0, "tokenov": 0, "stoimost": 0}
