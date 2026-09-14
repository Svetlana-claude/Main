"""Сквозная проверка в браузере: размер контекста, кнопка «Сжать контекст», потолок.

Поднимает второй экземпляр приложения на свободном порту (рабочую службу не
трогает) с подставным `claude`, заводит временный проект с темой, у которой
контекст 692 тыс. и остывший кэш, и нажимает в headless Chromium:

* в простое «Ход работы» говорит размер контекста и что кэш остыл;
* «Сжать контекст» → подтверждение → в ленте итог сжатия, в ходе работы строки
  сжатия, в базе новый размер контекста; после перезагрузки предупреждения нет;
* отправка сообщения: по ходу виден контекст, автосжатие у потолка отмечено
  строкой, потолок из настроек дошёл до `claude`;
* «Настройки»: поле потолка есть, 60000 сохраняется как 100000.

Браузер — Playwright из `exchange/pwenv` (вне версий, ставится на машине).
Запуск:  .venv/bin/python tests/check_compact_ui.py
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from app import config, db, security                  # noqa: E402

PW_PYTHON = config.REPO_ROOT / "exchange/pwenv/bin/python"
SHOTS = config.REPO_ROOT / "exchange/shots"

# Подставной движок. Что получил — пишет в файл рядом с собой: по нему
# проверяется, дошёл ли потолок из настроек.
FAKE_ENGINE = '''#!{python}
import json, os, sys, time
from pathlib import Path

here = Path(__file__).parent
args = sys.argv[1:]
prompt = args[args.index("-p") + 1]
with open(here / "calls.jsonl", "a") as f:
    f.write(json.dumps({{"prompt": prompt, "resume": "--resume" in args,
        "window": os.environ.get("CLAUDE_CODE_AUTO_COMPACT_WINDOW")}}) + "\\n")

def emit(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\\n")
    sys.stdout.flush()

def start(ctx):
    emit({{"type": "stream_event", "parent_tool_use_id": None, "event": {{"type": "message_start",
          "message": {{"usage": {{"input_tokens": 10, "cache_read_input_tokens": ctx - 10,
                                "cache_creation_input_tokens": 0}}}}}}}})

def compact(trigger, pre, post):
    emit({{"type": "system", "subtype": "status", "status": "compacting"}})
    time.sleep(1.5)
    emit({{"type": "system", "subtype": "compact_boundary",
          "compact_metadata": {{"trigger": trigger, "pre_tokens": pre, "post_tokens": post}}}})

emit({{"type": "system", "subtype": "init", "session_id": "fake-session", "model": "opus"}})
if prompt == "/compact":
    compact("manual", 692000, 1900)
    emit({{"type": "result", "session_id": "fake-session", "total_cost_usd": 0.42,
          "usage": {{"input_tokens": 0, "output_tokens": 0}}}})
else:
    start(180000)
    emit({{"type": "assistant", "message": {{"content": [
        {{"type": "tool_use", "name": "Read", "input": {{"file_path": "/tmp/x.md"}}}}]}}}})
    time.sleep(2)
    compact("auto", 260000, 2000)
    start(21000)
    time.sleep(2)
    emit({{"type": "assistant", "message": {{"content": [{{"type": "text", "text": "ответ-проверки"}}]}}}})
    emit({{"type": "result", "session_id": "fake-session", "result": "ответ-проверки",
          "total_cost_usd": 0.05, "usage": {{"input_tokens": 20, "output_tokens": 30}}}})
'''

BROWSER = r'''
import json, re, sys
from playwright.sync_api import sync_playwright

base, cookie, pid, tid, shots = sys.argv[1:6]
fails = []
def check(ok, what):
    print(("OK   " if ok else "FAIL ") + what, flush=True)
    if not ok: fails.append(what)

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1500, "height": 900})
    ctx.add_cookies([{"name": "webui_session", "value": cookie, "url": base}])
    page = ctx.new_page()
    errors = []
    page.on("console", lambda m: m.type == "error" and errors.append(m.text))
    page.on("pageerror", lambda e: errors.append(str(e)))
    dialogs = []
    page.on("dialog", lambda d: (dialogs.append(d.message), d.accept()))

    page.goto(f"{base}/projects?id={pid}&topic={tid}")
    stat = page.locator("#run-stat").inner_text()
    print("  простой:", stat)
    check("контекст 692 тыс." in stat, "в простое виден размер контекста")
    check("кэш остыл" in stat, "в простое сказано, что кэш остыл")
    btn = page.locator("#compact-btn")
    check(btn.count() == 1 and btn.is_enabled(), "кнопка «Сжать контекст» есть и доступна")
    page.screenshot(path=f"{shots}/compact-idle.png")

    btn.click()
    check(bool(dialogs) and "Сжать контекст" in dialogs[0], "перед сжатием спрошено подтверждение")
    page.wait_for_function("document.getElementById('run-stat').textContent.includes('сжимаю контекст')", timeout=10000)
    check(page.locator("#compact-btn").is_disabled(), "пока идёт сжатие, кнопка недоступна")
    page.wait_for_function("document.querySelector('#scroll').innerText.includes('Контекст сжат: было 692 тыс.')", timeout=20000)
    last = page.locator("#scroll .msg").last.inner_text()
    body_line = next((l for l in last.splitlines() if l.startswith("Контекст сжат")), "")
    check(body_line.rstrip() == "Контекст сжат: было 692 тыс. токенов, сводка — 2 тыс.",
          f"итог сжатия в ленте ({body_line})")
    runlog = page.locator("#run-log").inner_text()
    check("Сжатие контекста" in runlog and "было 692 тыс. → сводка 2 тыс." in runlog, "строки сжатия в «Ходе работы»")
    page.wait_for_function("document.getElementById('run-stat').textContent.includes('готово')", timeout=10000)
    stat = page.locator("#run-stat").inner_text()
    check("контекст 2 тыс." in stat, f"после сжатия строка говорит новый контекст ({stat})")
    check(page.locator("#compact-btn").is_enabled(), "после сжатия кнопка снова доступна")
    page.screenshot(path=f"{shots}/compact-done.png")

    page.reload()
    stat = page.locator("#run-stat").inner_text()
    check("контекст 2 тыс." in stat and "остыл" not in stat, f"после перезагрузки: контекст из базы, без предупреждения ({stat})")

    page.fill("#text", "проверка потолка")
    page.click("#send-btn")
    page.wait_for_function("document.getElementById('run-stat').textContent.includes('контекст 180 тыс.')", timeout=10000)
    check(True, "по ходу ответа виден контекст шага (180 тыс.)")
    page.wait_for_function("document.getElementById('run-stat').textContent.includes('сжимаю контекст')", timeout=10000)
    check(True, "автосжатие у потолка видно в строке состояния")
    page.wait_for_function("document.getElementById('run-stat').textContent.includes('готово')", timeout=20000)
    runlog = page.locator("#run-log").inner_text()
    check("Контекст сжат у потолка" in runlog, "автосжатие отмечено строкой в «Ходе работы»")
    stat = page.locator("#run-stat").inner_text()
    check("контекст 21 тыс." in stat, f"итог ответа с контекстом после сжатия ({stat})")
    page.screenshot(path=f"{shots}/compact-auto.png")

    page.goto(f"{base}/settings")
    field = page.locator("#compact_window")
    check(field.count() == 1 and field.input_value() == "250000", f"в «Настройках» поле потолка, по умолчанию 250000")
    field.fill("60000")
    page.locator("#compact_window").evaluate("el => el.form.requestSubmit()")
    page.wait_for_load_state()
    check(page.locator("#compact_window").input_value() == "100000", "60000 сохранено как нижняя граница 100000")
    page.screenshot(path=f"{shots}/compact-settings.png", full_page=True)

    check(not errors, f"консоль без ошибок {errors}")
    b.close()
print("BROWSER_FAILS", len(fails))
sys.exit(1 if fails else 0)
'''

failures: list[str] = []


def check(ok: bool, what: str) -> None:
    print(("OK   " if ok else "FAIL ") + what)
    if not ok:
        failures.append(what)


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


def main() -> int:
    if not PW_PYTHON.is_file():
        print(f"FAIL нет Playwright: {PW_PYTHON} — браузерная проверка не проведена")
        return 1
    db.init_pool()
    db.apply_schema()          # поля контекста нужны до того, как их заполнять

    user = db.query_one("SELECT id FROM users ORDER BY id LIMIT 1")
    saved_window = db.query_one("SELECT value FROM settings WHERE key = 'compact_window'")
    tmp = Path(tempfile.mkdtemp(prefix="compact-ui-"))
    engine = tmp / "fake-claude"
    engine.write_text(FAKE_ENGINE.format(python=sys.executable), encoding="utf-8")
    engine.chmod(0o755)
    workdir = tmp / "project"
    workdir.mkdir()

    session_id = security.new_session_id()
    db.execute(
        "INSERT INTO sessions (id, user_id, expires_at, ip, user_agent) VALUES (%s, %s, %s, %s, %s)",
        (session_id, user["id"], security.session_expiry(), "127.0.0.1", "check_compact_ui"),
    )
    project = db.query_one(
        "INSERT INTO projects (name, slug, workdir) VALUES (%s, %s, %s) RETURNING id",
        ("Проверка сжатия", f"check-compact-{os.getpid()}", str(workdir)),
    )
    topic = db.query_one(
        "INSERT INTO conversations (kind, project_id, title, claude_session_id, context_tokens, context_at) "
        "VALUES ('topic', %s, 'Длинная тема', 'fake-session', 692000, now() - interval '2 hours') RETURNING id",
        (project["id"],),
    )
    db.execute("INSERT INTO messages (conversation_id, role, content) VALUES (%s, 'user', 'старый вопрос')", (topic["id"],))
    db.execute("INSERT INTO messages (conversation_id, role, content, cost_usd) VALUES (%s, 'assistant', 'старый ответ', 1)", (topic["id"],))
    if saved_window:
        db.execute("DELETE FROM settings WHERE key = 'compact_window'")    # проверяется значение по умолчанию

    port = free_port()
    proc = subprocess.Popen(
        [str(PROJECT_DIR / ".venv/bin/python"), "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=str(PROJECT_DIR), env=dict(os.environ, CLAUDE_BIN=str(engine)),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        if not wait_ready(port, proc):
            check(False, "второй экземпляр не поднялся")
            return 1
        SHOTS.mkdir(parents=True, exist_ok=True)
        script = tmp / "browser.py"
        script.write_text(BROWSER, encoding="utf-8")
        res = subprocess.run(
            [str(PW_PYTHON), str(script), f"http://127.0.0.1:{port}",
             security.sign_session_id(session_id), str(project["id"]), str(topic["id"]), str(SHOTS)],
            capture_output=True, text=True, timeout=240,
        )
        print(res.stdout.rstrip())
        if res.returncode:
            failures.append("браузер")
            print(res.stderr[-2000:])

        row = db.query_one("SELECT context_tokens FROM conversations WHERE id = %s", (topic["id"],))
        check(row["context_tokens"] == 21000, f"в базе контекст последнего ответа ({row['context_tokens']})")
        compact_msg = db.query_one(
            "SELECT cost_usd FROM messages WHERE conversation_id = %s AND content LIKE 'Контекст сжат%%'",
            (topic["id"],),
        )
        check(bool(compact_msg) and float(compact_msg["cost_usd"]) == 0.42,
              "стоимость сжатия записана в учёт расхода")
        calls = [json.loads(line) for line in (tmp / "calls.jsonl").read_text().splitlines()] \
            if (tmp / "calls.jsonl").exists() else []
        print("  вызовы claude:", calls)
        check([c["prompt"] for c in calls] == ["/compact", "проверка потолка"],
              "сжатие ушло командой /compact, затем сообщение")
        check(all(c["resume"] and c["window"] == "250000" for c in calls),
              "оба запуска — в ту же сессию, с потолком 250000 из настроек")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        db.execute("DELETE FROM projects WHERE id = %s", (project["id"],))
        db.execute("DELETE FROM sessions WHERE id = %s", (session_id,))
        db.execute("DELETE FROM settings WHERE key = 'compact_window'")
        if saved_window:
            db.set_setting("compact_window", saved_window["value"])
        shutil.rmtree(tmp, ignore_errors=True)

    print("ПРОВАЛОВ:", len(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
