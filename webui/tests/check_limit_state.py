"""Сквозная проверка: исчерпанный лимит и идущий запуск не выглядят «выполненным».

Что ломалось:
* Claude Code сообщает об исчерпанном лимите итогом `result` с `is_error`.
  Страница принимала его за обычный итог — «Ход работы» писал «готово», кружок
  темы зеленел, а работа на деле стояла до обнуления окна;
* кружок искал идущий запуск не под тем ключом (`project` вместо `topic`) и о
  нём не знал — при сжатии по кнопке, когда вопроса в ленте нет, тема горела
  зелёным, пока движок в ней работал.

Поднимает второй экземпляр приложения на свободном порту (рабочую службу не
трогает) с подставным `claude`, заводит временный проект и нажимает в headless
Chromium «Отправить» и «Сжать контекст».

Браузер — Playwright из `exchange/pwenv` (вне версий, ставится на машине).
Запуск:  .venv/bin/python tests/check_limit_state.py
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

# Подставной движок: на сообщение — шаг работы и исчерпанный лимит тем же
# путём, что у настоящего (итог с признаком ошибки); на /compact — долгое сжатие
FAKE_ENGINE = '''#!{python}
import json, sys, time

args = sys.argv[1:]
prompt = args[args.index("-p") + 1]

def emit(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\\n")
    sys.stdout.flush()

emit({{"type": "system", "subtype": "init", "session_id": "fake-session", "model": "opus"}})
if prompt == "/compact":
    emit({{"type": "system", "subtype": "status", "status": "compacting"}})
    time.sleep(8)
    emit({{"type": "system", "subtype": "compact_boundary",
          "compact_metadata": {{"trigger": "manual", "pre_tokens": 300000, "post_tokens": 2000}}}})
    emit({{"type": "result", "session_id": "fake-session", "total_cost_usd": 0.1,
          "usage": {{"input_tokens": 0, "output_tokens": 0}}}})
else:
    emit({{"type": "assistant", "message": {{"content": [
        {{"type": "tool_use", "name": "Bash", "input": {{"command": "ls"}}}}]}}}})
    time.sleep(1)
    emit({{"type": "assistant", "message": {{"content": [
        {{"type": "text", "text": "You've hit your session limit · resets 4:10pm (UTC)"}}]}}}})
    emit({{"type": "result", "subtype": "success", "is_error": True, "session_id": "fake-session",
          "result": "You've hit your session limit · resets 4:10pm (UTC)",
          "total_cost_usd": 0.9, "num_turns": 2, "usage": {{"input_tokens": 5, "output_tokens": 7}}}})
'''

BROWSER = r'''
import sys, time
from playwright.sync_api import sync_playwright

base, cookie, pid, t_limit, t_compact, shots = sys.argv[1:7]
fails = []
def check(ok, what):
    print(("OK   " if ok else "FAIL ") + what, flush=True)
    if not ok: fails.append(what)

def dot(page, tid):
    el = page.locator(f'[data-topic-dot="{tid}"]')
    return (el.get_attribute("class") or "", el.get_attribute("title") or "") if el.count() else ("", "")

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1500, "height": 900})
    ctx.add_cookies([{"name": "webui_session", "value": cookie, "url": base}])
    page = ctx.new_page()
    errors = []
    page.on("console", lambda m: m.type == "error" and errors.append(m.text))
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("dialog", lambda d: d.accept())

    # ── Исчерпанный лимит ──
    page.goto(f"{base}/projects?id={pid}&topic={t_limit}")
    page.fill("#text", "продолжаем")
    page.click("#send-btn")
    page.wait_for_function("!document.getElementById('run-stat').textContent.startsWith('● идёт')"
                           " && document.getElementById('run-stat').textContent !== 'простой'", timeout=20000)
    time.sleep(0.5)
    stat = page.locator("#run-stat")
    text, cls = stat.inner_text(), stat.get_attribute("class")
    print("  строка:", text, "|", cls)
    check("готово" not in text, "«Ход работы» не пишет «готово» при исчерпанном лимите")
    check("runstat--err" in cls, "строка «Хода работы» в оформлении ошибки")
    check("Исчерпан лимит" in text and "обнулится" in text, "в строке сказано, что лимит исчерпан и когда обнулится")
    last = page.locator("#scroll .msg").last
    check("msg--error" in (last.get_attribute("class") or ""), "сообщение о лимите в ленте оформлено как ошибка")
    c, _ = dot(page, t_limit)
    check("dot--work" in c, f"кружок темы сразу красный ({c})")
    page.screenshot(path=f"{shots}/limit-live.png")
    time.sleep(12)                                    # опрос кружков идёт раз в 10 с
    c, _ = dot(page, t_limit)
    check("dot--work" in c, f"кружок темы красный и после опроса ({c})")

    page.reload()
    c, title = dot(page, t_limit)
    check("dot--work" in c, f"после перезагрузки кружок красный ({c})")
    check("обнулится" in title, f"подсказка кружка говорит про лимит ({title})")
    idle = page.locator("#run-stat").inner_text()
    check("Исчерпан лимит" in idle and "обнулится" in idle, f"в простое «Ход работы» напоминает про лимит ({idle})")
    page.screenshot(path=f"{shots}/limit-reload.png")

    # ── Идущее сжатие: вопроса в ленте нет, а работа идёт ──
    page.goto(f"{base}/projects?id={pid}&topic={t_compact}")
    c, _ = dot(page, t_compact)
    check("dot--done" in c, f"до сжатия тема выполненная ({c})")
    page.click("#compact-btn")
    page.wait_for_function("document.getElementById('run-stat').textContent.includes('сжимаю')", timeout=10000)
    page.goto(f"{base}/projects?id={pid}&topic={t_compact}")   # страница заново — цвет только от сервера
    c, _ = dot(page, t_compact)
    check("dot--work" in c, f"пока идёт сжатие, сервер красит тему красным ({c})")
    page.wait_for_function("document.getElementById('run-stat').textContent.includes('готово')", timeout=20000)
    c, _ = dot(page, t_compact)
    check("dot--done" in c, f"после сжатия тема снова выполненная ({c})")

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
    db.apply_schema()

    user = db.query_one("SELECT id FROM users ORDER BY id LIMIT 1")
    tmp = Path(tempfile.mkdtemp(prefix="limit-state-"))
    engine = tmp / "fake-claude"
    engine.write_text(FAKE_ENGINE.format(python=sys.executable), encoding="utf-8")
    engine.chmod(0o755)
    workdir = tmp / "project"
    workdir.mkdir()

    session_id = security.new_session_id()
    db.execute(
        "INSERT INTO sessions (id, user_id, expires_at, ip, user_agent) VALUES (%s, %s, %s, %s, %s)",
        (session_id, user["id"], security.session_expiry(), "127.0.0.1", "check_limit_state"),
    )
    project = db.query_one(
        "INSERT INTO projects (name, slug, workdir) VALUES (%s, %s, %s) RETURNING id",
        ("Проверка лимита", f"check-limit-{os.getpid()}", str(workdir)),
    )
    topics = {}
    for title in ("Лимит", "Сжатие"):
        row = db.query_one(
            "INSERT INTO conversations (kind, project_id, title, claude_session_id) "
            "VALUES ('topic', %s, %s, 'fake-session') RETURNING id",
            (project["id"], title),
        )
        topics[title] = row["id"]
        db.execute("INSERT INTO messages (conversation_id, role, content) VALUES (%s, 'user', 'вопрос')", (row["id"],))
        db.execute("INSERT INTO messages (conversation_id, role, content) VALUES (%s, 'assistant', 'ответ')", (row["id"],))

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
            [str(PW_PYTHON), str(script), f"http://127.0.0.1:{port}", security.sign_session_id(session_id),
             str(project["id"]), str(topics["Лимит"]), str(topics["Сжатие"]), str(SHOTS)],
            capture_output=True, text=True, timeout=300,
        )
        print(res.stdout.rstrip())
        if res.returncode:
            failures.append("браузер")
            print(res.stderr[-2000:])

        row = db.query_one(
            "SELECT role FROM messages WHERE conversation_id = %s ORDER BY id DESC LIMIT 1", (topics["Лимит"],))
        check(row["role"] == "error", f"сообщение о лимите в базе записано ошибкой ({row['role']})")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        db.execute("DELETE FROM projects WHERE id = %s", (project["id"],))
        db.execute("DELETE FROM sessions WHERE id = %s", (session_id,))
        shutil.rmtree(tmp, ignore_errors=True)

    print("ПРОВАЛОВ:", len(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
