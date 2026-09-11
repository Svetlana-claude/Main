"""Расход по стенограммам сессий Claude Code.

ЗАЧЕМ. Своя таблица `messages` знает только то, что прошло через этот
веб-интерфейс. Запуски `claude` из терминала в неё не попадают, а окно
тарифного плана у Anthropic расходуют наравне. Стенограммы сессий —
`~/.claude/projects/<проект>/<сессия>.jsonl` — пишутся движком всегда,
и для запусков приложения тоже (проверено 11.09.2026: файлы нашлись
по всем `claude_session_id` из базы). Поэтому окна считаются по ним,
а база остаётся запасным источником.

ГЛАВНАЯ ЛОВУШКА — ДВОЙНОЙ СЧЁТ. Один ответ движка разложен в стенограмме
на несколько строк (рассуждение, текст, вызовы инструментов), и в каждой
строке лежит ОДИН И ТОТ ЖЕ блок `usage` — не доля, а полный расход ответа.
Построчное сложение завышает счёт больше чем вдвое: на здешних файлах
1 275 строк давали 1 229 685 выходных токенов вместо настоящих 554 316
по 632 ответам. Поэтому строки сводятся по ключу «запрос + сообщение»,
а `uuid` для этого не годится — он у каждой строки свой.
"""
import glob
import json
import os
from datetime import datetime, timedelta, timezone

# Дальше недельного окна считать нечего, а память ограничить надо
MAX_WINDOW = timedelta(days=7)

PROJECTS_DIR = os.path.expanduser("~/.claude/projects")

# Разобранное по файлам: путь -> {"offset": сколько байт уже прочитано,
# "entries": [(время, ключ, вход, выход, из кэша, в кэш)]}. Файл дочитывается
# с прошлого места: на автообновлении раз в 10 секунд перечитывать растущую
# стенограмму целиком незачем.
_cache: dict[str, dict] = {}


def _parse_line(raw: str) -> tuple | None:
    """Строка стенограммы -> запись о расходе, либо None если её там нет."""
    try:
        rec = json.loads(raw)
    except (ValueError, TypeError):
        return None
    message = rec.get("message") or {}
    usage = message.get("usage")
    if not isinstance(usage, dict):
        return None

    stamp = rec.get("timestamp")
    if not stamp:
        return None
    try:
        when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None

    # Ключ сведения повторов: у строк одного ответа он общий. requestId
    # изредка отсутствует (в здешних файлах — 5 строк из 1275), тогда хватает
    # идентификатора сообщения; если нет и его, строка считается сама по себе.
    key = rec.get("requestId") or ""
    key += "|" + str(message.get("id") or rec.get("uuid") or "")

    return (
        when,
        key,
        int(usage.get("input_tokens") or 0),
        int(usage.get("output_tokens") or 0),
        int(usage.get("cache_read_input_tokens") or 0),
        int(usage.get("cache_creation_input_tokens") or 0),
    )


def _refresh(path: str, oldest: datetime) -> list[tuple]:
    """Дочитывает файл с прошлого места и отдаёт его записи за последнюю неделю."""
    state = _cache.get(path)
    try:
        size = os.path.getsize(path)
    except OSError:
        _cache.pop(path, None)
        return []

    if state is None or size < state["offset"]:
        # Новый файл либо укоротился (перезаписан) — читаем с начала
        state = {"offset": 0, "entries": []}
        _cache[path] = state

    if size > state["offset"]:
        try:
            with open(path, "rb") as fh:
                fh.seek(state["offset"])
                blob = fh.read()
        except OSError:
            return state["entries"]

        # Файл могут дописывать прямо сейчас: последняя строка бывает обрезана
        # на середине. Берём только то, что закончилось переводом строки,
        # остальное дочитается в следующий раз.
        cut = blob.rfind(b"\n")
        if cut >= 0:
            state["offset"] += cut + 1
            for raw in blob[: cut + 1].decode("utf-8", "replace").splitlines():
                entry = _parse_line(raw)
                if entry is not None:
                    state["entries"].append(entry)

    if state["entries"]:
        state["entries"] = [e for e in state["entries"] if e[0] >= oldest]
    return state["entries"]


def usage_since(since: datetime) -> dict | None:
    """Расход по всем стенограммам с момента `since`.

    None означает «источник недоступен» — каталога нет или он не читается;
    вызывающий переходит на свою базу и говорит об этом на странице.
    """
    if not os.path.isdir(PROJECTS_DIR):
        return None

    oldest = datetime.now(timezone.utc) - MAX_WINDOW
    try:
        paths = glob.glob(os.path.join(PROJECTS_DIR, "*", "*.jsonl"))
    except OSError:
        return None

    seen: set[str] = set()
    started = None
    totals = [0, 0, 0, 0]   # вход, выход, из кэша, в кэш

    for path in paths:
        try:
            touched = datetime.fromtimestamp(os.path.getmtime(path), timezone.utc)
        except OSError:
            continue
        # Файл, не менявшийся с начала окна, записей в окне иметь не может.
        # Но если он уже разобран, его записи держим — они могли попасть в окно.
        if touched < since and path not in _cache:
            continue

        for when, key, tin, tout, cread, cwrite in _refresh(path, oldest):
            if when < since or key in seen:
                continue
            seen.add(key)
            if started is None or when < started:
                started = when
            totals[0] += tin
            totals[1] += tout
            totals[2] += cread
            totals[3] += cwrite

    return {
        "started": started,
        "input_tokens": totals[0],
        "output_tokens": totals[1],
        "cache_read": totals[2],
        "cache_write": totals[3],
        "requests": len(seen),
    }
