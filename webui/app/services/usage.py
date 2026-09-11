"""Расход токенов и состояние окон тарифного плана.

Почему тут токены, а не деньги. Подписка Pro не тарифицируется по запросам:
за отдельный ответ денег не списывают, ограничивают частоту — окном на пять
часов и окном на неделю. Поле `total_cost_usd`, которое возвращает CLI, —
это пересчёт по тарифам API, то есть «сколько стоило бы то же самое без
подписки». К остатку по плану оно отношения не имеет, поэтому вынесено
в справочную строку и убрано с видного места.

ЧЕГО ЭТИ ЧИСЛА НЕ ЗНАЮТ. Сколько именно осталось по плану, знает только сам
Anthropic: счёт ведётся на его стороне, программного способа спросить остаток
нет. Проверено по документации 11.09.2026: Admin и Analytics API личным
подпискам не выдаются вовсе («The Admin API is unavailable for individual
accounts») и отдают суточные итоги прошлого расхода, а не остаток;
у телеметрии OpenTelemetry метрики остатка нет ни одной. Остаток показывают
только `/status` и `/usage` внутри живой сессии. Поэтому предел окна задаётся
в настройках и подбирается наблюдением, а не берётся с потолка.

ОТКУДА РАСХОД. Окна считаются по стенограммам сессий (см. `transcripts.py`) —
в них попадают и запуски `claude` из терминала, которые окно расходуют так же,
как работа через интерфейс. Своя таблица `messages` знает только второе,
поэтому она оставлена запасным источником и разбивкой по разделам. Какой
источник сработал, написано на самой странице: дашборд, который врёт молча,
хуже отсутствующего.
"""
from datetime import datetime, timedelta, timezone

from .. import db
from . import transcripts

# Длина окон тарифного плана
WINDOW_5H = timedelta(hours=5)
WINDOW_WEEK = timedelta(days=7)


def _db_usage_since(since: datetime) -> dict:
    """Запасной источник: расход по своей базе, без запусков из терминала."""
    row = db.query_one(
        """
        SELECT min(created_at) AS started,
               coalesce(sum(input_tokens), 0) AS input_tokens,
               coalesce(sum(output_tokens), 0) AS output_tokens,
               coalesce(sum(cache_read), 0) AS cache_read,
               coalesce(sum(cache_write), 0) AS cache_write,
               count(*) AS requests
        FROM messages
        WHERE role = 'assistant' AND created_at >= %s
        """,
        (since,),
    ) or {}
    return {
        "started": row.get("started"),
        "input_tokens": int(row.get("input_tokens") or 0),
        "output_tokens": int(row.get("output_tokens") or 0),
        "cache_read": int(row.get("cache_read") or 0),
        "cache_write": int(row.get("cache_write") or 0),
        "requests": int(row.get("requests") or 0),
    }


def _window(data: dict, length: timedelta, limit_tokens: int) -> dict:
    """Состояние одного окна: расход с его начала и сколько осталось.

    Считает только арифметику, данные приходят готовыми, — так эту часть
    можно проверить без базы и без стенограмм.

    Окно скользящее и начинается с первого запроса, а не в круглый час:
    поэтому начало берётся как самый ранний ответ внутри `length`,
    а обнуление — это начало плюс `length`.
    """
    started = data.get("started")
    tokens = int(data["input_tokens"]) + int(data["output_tokens"])
    resets_at = (started + length) if started else None
    left_seconds = int((resets_at - datetime.now(timezone.utc)).total_seconds()) if resets_at else 0

    share = (tokens / limit_tokens * 100) if limit_tokens > 0 else 0.0
    return {
        "tokens": tokens,
        "input_tokens": int(data["input_tokens"]),
        "output_tokens": int(data["output_tokens"]),
        "cache_read": int(data["cache_read"]),
        "cache_write": int(data["cache_write"]),
        "requests": int(data["requests"]),
        "limit": limit_tokens,
        "left": max(0, limit_tokens - tokens) if limit_tokens > 0 else 0,
        "share": round(share, 1),
        "over": limit_tokens > 0 and tokens >= limit_tokens,
        "near": limit_tokens > 0 and 80 <= share < 100,
        "idle": started is None,
        "resets_at": resets_at.isoformat() if resets_at else None,
        "resets_in": _human_left(left_seconds) if resets_at else None,
    }


def _human_left(seconds: int) -> str:
    """«2 ч 15 мин» — сколько ждать до обнуления окна."""
    seconds = max(0, seconds)
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if days:
        return f"{days} дн {hours} ч"
    if hours:
        return f"{hours} ч {minutes} мин"
    return f"{minutes} мин"


def _int_setting(settings: dict, key: str) -> int:
    """Предел из настроек. Ноль и мусор одинаково означают «предел не задан»."""
    try:
        return max(0, int(float(settings.get(key) or 0)))
    except (TypeError, ValueError):
        return 0


def summary() -> dict:
    """Всё, что показывает раздел расхода на дашборде."""
    settings = db.get_settings()

    today = db.query_one(
        """
        SELECT coalesce(sum(input_tokens), 0) AS input_tokens,
               coalesce(sum(output_tokens), 0) AS output_tokens,
               coalesce(sum(cache_read), 0) AS cache_read,
               coalesce(sum(cache_write), 0) AS cache_write,
               coalesce(sum(cost_usd), 0) AS cost,
               count(*) AS requests
        FROM messages
        WHERE role = 'assistant' AND created_at >= date_trunc('day', now())
        """
    )
    by_kind = db.query(
        """
        SELECT c.kind,
               coalesce(sum(m.input_tokens + m.output_tokens), 0) AS tokens,
               count(m.id) AS requests
        FROM messages m JOIN conversations c ON c.id = m.conversation_id
        WHERE m.role = 'assistant' AND m.created_at >= now() - interval '7 days'
        GROUP BY c.kind
        """
    )

    # Источник для окон — стенограммы: в них есть и запуски из терминала.
    # Если их нет (каталог убрали, права закрыли), считаем по своей базе
    # и честно говорим об этом на странице: неполный счёт молча выдавать
    # за полный нельзя.
    now = datetime.now(timezone.utc)
    data_5h = transcripts.usage_since(now - WINDOW_5H)
    data_week = transcripts.usage_since(now - WINDOW_WEEK)
    source = "стенограммы"
    if data_5h is None or data_week is None:
        data_5h = _db_usage_since(now - WINDOW_5H)
        data_week = _db_usage_since(now - WINDOW_WEEK)
        source = "база"

    return {
        "source": source,
        "window_5h": _window(data_5h, WINDOW_5H, _int_setting(settings, "limit_5h_tokens")),
        "window_week": _window(data_week, WINDOW_WEEK, _int_setting(settings, "limit_week_tokens")),
        "today": {
            "input_tokens": int(today["input_tokens"]) if today else 0,
            "output_tokens": int(today["output_tokens"]) if today else 0,
            "cache_read": int(today["cache_read"]) if today else 0,
            "cache_write": int(today["cache_write"]) if today else 0,
            "requests": int(today["requests"]) if today else 0,
            # Справочно: пересчёт по тарифам API, не списание с подписки
            "cost_reference": round(float(today["cost"]), 2) if today else 0.0,
        },
        "by_kind": {
            r["kind"]: {"tokens": int(r["tokens"]), "requests": int(r["requests"])}
            for r in by_kind
        },
    }
