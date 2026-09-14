"""Проверка: время сброса лимита Claude Code показывается в поясе из настроек.

Claude Code пишет «You've hit your session limit · resets 9:50am (UTC)» — время
в поясе сервера и без даты. Где это ломается незаметно:

* время переводится, но без учёта того, когда сообщение пришло: «12:10am (UTC)»,
  сказанное в 23:40, — это следующие сутки, а не прошедшая полночь;
* дата не пишется, когда сброс приходится на другой местный день — «в 03:10»
  читается как «сегодня», а это уже завтра;
* в базу уходит уже переведённая строка — оригинал потерян, а смена пояса в
  настройках старые сообщения не переводит;
* незнакомая строка «переводится» наугад и искажается.

Стенд проверяет функцию на примерах, затем поднимает второй экземпляр
приложения (рабочую службу не трогает), заводит свой чат с сообщением о лимите,
ставит на время прогона пояс Владивостока и смотрит ленту, выгрузку и живую
выдачу — с заглушкой вместо claude, отвечающей строкой о лимите в формате
настоящего CLI. Всё возвращается как было.

Запуск:  .venv/bin/python tests/check_limit_time.py
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db, security, timefmt                  # noqa: E402

PROJECT_DIR = Path(__file__).resolve().parent.parent
FAILED: list[str] = []
MSK = ZoneInfo("Europe/Moscow")
VLAD = ZoneInfo("Asia/Vladivostok")
SESSION = "You've hit your session limit · resets 9:50am (UTC)"

# Заглушка вместо claude: отвечает так, как настоящий Claude Code при исчерпанном
# лимите, — событием result с is_error. Этим путём пришли все пять сообщений о
# лимите, найденные в базе; путь события error их не рисует вовсе.
FAKE_CLAUDE = """#!/bin/bash
cat <<'JSON'
{"type":"result","subtype":"success","is_error":true,"result":"You've hit your session limit · resets 9:50am (UTC)","session_id":"stand-limit","usage":{"input_tokens":2,"output_tokens":3},"total_cost_usd":0,"duration_ms":5,"num_turns":1,"modelUsage":{"claude-opus-5":{"outputTokens":3}}}
JSON
"""


def check(ok: bool, what: str) -> None:
    if ok:
        print(f"  ok: {what}")
    else:
        FAILED.append(what)
        print(f"  ПРОВАЛ: {what}")


def at(h: int, m: int, day: int = 14) -> datetime:
    return datetime(2026, 9, day, h, m, tzinfo=timezone.utc)


def check_pure() -> None:
    L = timefmt.localize_limit
    check(L(SESSION, at(9, 21), MSK) == "Исчерпан лимит сессии · обнулится в 12:50 (Москва)",
          "9:50am UTC в 09:21 — «в 12:50 (Москва)»")
    check(L(SESSION, at(9, 21), VLAD) == "Исчерпан лимит сессии · обнулится в 19:50 (Владивосток)",
          "тот же сброс во Владивостоке — «в 19:50»")
    check(L(SESSION, at(10, 5), MSK) == "Исчерпан лимит сессии · обнулится 15.09 в 12:50 (Москва)",
          "9:50am, сказанное в 10:05, — это завтра, и дата указана")
    check(L("You've hit your session limit · resets 12:10am (UTC)", at(23, 40), MSK)
          == "Исчерпан лимит сессии · обнулится в 03:10 (Москва)",
          "полночь UTC, сказанная в 23:40, — следующие сутки (в Москве тот же день 15.09)")
    check(L("You've hit your session limit · resets 12:10am (UTC)", at(20, 30), MSK)
          == "Исчерпан лимит сессии · обнулится 15.09 в 03:10 (Москва)",
          "сброс на следующий местный день подписан датой")
    check(L("You've hit your session limit · resets 3pm (UTC)", at(9, 21), MSK)
          == "Исчерпан лимит сессии · обнулится в 18:00 (Москва)",
          "время без минут — «3pm» понят как 15:00")
    check(L("You've hit your session limit · resets 12pm (UTC)", at(9, 21), MSK)
          == "Исчерпан лимит сессии · обнулится в 15:00 (Москва)",
          "12pm — полдень, а не полночь")
    check(L("You've hit your weekly limit · resets Sep 16, 9am (UTC)", at(9, 21), MSK)
          == "Исчерпан недельный лимит · обнулится 16.09 в 12:00 (Москва)",
          "недельный лимит с датой")
    december = datetime(2026, 12, 30, 10, 0, tzinfo=timezone.utc)
    check(L("You've hit your weekly limit · resets Jan 2, 9am (UTC)", december, MSK)
          == "Исчерпан недельный лимит · обнулится 02.01 в 12:00 (Москва)"
          and timefmt.limit_reset("resets Jan 2, 9am (UTC)", december, MSK).year == 2027,
          "«Jan 2», сказанное в декабре, — следующий год")
    for text in ["Превышено время ожидания ответа", "resets 9:50am (Марс/Олимп)", "", "resets 25:00am (UTC)"]:
        check(L(text, at(9, 21), MSK) == text, f"незнакомое оставлено как есть: «{text}»")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_ready(port: int, proc: subprocess.Popen, tries: int = 60) -> bool:
    for _ in range(tries):
        if proc.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=1) as res:
                if res.status == 200:
                    return True
        except Exception:                              # noqa: BLE001
            time.sleep(0.5)
    return False


def check_live() -> None:
    user = db.query_one("SELECT id FROM users ORDER BY id LIMIT 1")
    before_tz = db.get_settings().get("timezone")
    chat = db.query_one(
        "INSERT INTO conversations (kind, title) VALUES ('chat', %s) RETURNING id",
        ("стенд времени лимита",),
    )["id"]
    db.execute(
        "INSERT INTO messages (conversation_id, role, content, created_at) VALUES (%s, 'error', %s, %s)",
        (chat, SESSION, at(9, 21)),
    )
    session_id = security.new_session_id()
    db.execute(
        "INSERT INTO sessions (id, user_id, expires_at, ip, user_agent) VALUES (%s, %s, %s, %s, %s)",
        (session_id, user["id"], security.session_expiry(), "127.0.0.1", "check_limit_time"),
    )
    cookie = f"webui_session={security.sign_session_id(session_id)}"
    db.execute(
        "INSERT INTO settings (key, value) VALUES ('timezone', 'Asia/Vladivostok') "
        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
    )

    fake = Path(tempfile.mkdtemp(prefix="limit-stand-")) / "claude"
    fake.write_text(FAKE_CLAUDE, encoding="utf-8")
    fake.chmod(0o755)

    port = free_port()
    proc = subprocess.Popen(
        [str(PROJECT_DIR / ".venv/bin/python"), "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=str(PROJECT_DIR), env=dict(os.environ, CLAUDE_BIN=str(fake)),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        if not wait_ready(port, proc):
            check(False, "второй экземпляр не поднялся")
            return

        def get(path: str) -> tuple[int, str]:
            req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers={"Cookie": cookie})
            try:
                with urllib.request.urlopen(req, timeout=15) as res:
                    return res.status, res.read().decode("utf-8", "replace")
            except urllib.error.HTTPError as exc:
                return exc.code, exc.read().decode("utf-8", "replace")

        status, body = get(f"/chats?id={chat}")
        check(status == 200, f"лента чата открывается (код {status})")
        check("обнулится в 19:50 (Владивосток)" in body,
              "в ленте время сброса — в поясе из настроек")
        check("resets 9:50am (UTC)" not in body, "строки с UTC в ленте больше нет")

        stored = db.query_one("SELECT content FROM messages WHERE conversation_id = %s", (chat,))["content"]
        check(stored == SESSION, "в базе осталась исходная строка Claude Code")

        status, body = get(f"/export/{chat}")
        check(status == 200 and "обнулится в 19:50 (Владивосток)" in body,
              "в выгрузке диалога — тоже в поясе из настроек")

        # Живая выдача: ровно тот путь, по которому сообщение видно во время ответа.
        data = "text=проба лимита".encode()
        req = urllib.request.Request(f"http://127.0.0.1:{port}/chats/{chat}/send", data=data,
                                     headers={"Cookie": cookie})
        with urllib.request.urlopen(req, timeout=15) as res:
            check(res.status == 200, f"сообщение отправлено (код {res.status})")
        req = urllib.request.Request(f"http://127.0.0.1:{port}/chats/{chat}/stream?start=0",
                                     headers={"Cookie": cookie})
        result = None
        with urllib.request.urlopen(req, timeout=30) as res:
            for raw in res:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                event = json.loads(line[5:])
                if event.get("type") == "result":
                    result = event
                if event.get("type") == "done":
                    break
        check(result is not None, "поток отдал событие результата")
        text = (result or {}).get("text", "")
        reset = timefmt.limit_reset(SESSION, datetime.now(timezone.utc), VLAD)
        want = reset.strftime("%H:%M") if reset else "?"
        check("Исчерпан лимит сессии" in text and want in text and "Владивосток" in text,
              f"в живой выдаче — «{text}» (ждём время {want} по Владивостоку)")
        check("(UTC)" not in text, "в живой выдаче строки с UTC нет")
        saved = db.query_one(
            "SELECT content FROM messages WHERE conversation_id = %s AND role = 'error' "
            "ORDER BY id DESC LIMIT 1", (chat,))
        check(saved and saved["content"] == SESSION,
              "в базу из живой выдачи ушла исходная строка, а не перевод")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        db.execute("DELETE FROM conversations WHERE id = %s", (chat,))
        db.execute("DELETE FROM sessions WHERE id = %s", (session_id,))
        if before_tz is None:
            db.execute("DELETE FROM settings WHERE key = 'timezone'")
        else:
            db.execute("UPDATE settings SET value = %s WHERE key = 'timezone'", (before_tz,))


def main() -> int:
    db.init_pool()
    print("Перевод строки:")
    check_pure()
    print("\nЖивая страница:")
    check_live()
    print()
    if FAILED:
        print(f"ПРОВАЛОВ: {len(FAILED)}")
        for item in FAILED:
            print(f"  - {item}")
        return 1
    print("Все проверки прошли.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
