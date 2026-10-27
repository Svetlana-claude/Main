"""Сквозная проверка рабочего места v2 в браузере.

Поднимает второй экземпляр приложения с подставным `claude` (рабочую службу не
трогает), заводит чатик и нажимает в headless Chromium:

* `/v2` открывает последний разговор;
* Enter отправляет, ответ приходит и рисуется Markdown'ом, ход работы не виден,
  название разговора приходит по первой реплике;
* «Стоп» обрывает долгий ответ, в ленте и в базе — «Остановлено»;
* телефон 390 px: список спрятан и выезжает по кнопке, страница не едет вбок;
* консоль без ошибок.

Браузер — Playwright из `exchange/pwenv`.
Запуск:  .venv/bin/python tests/check_v2.py
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from app import config, db, security                  # noqa: E402
from tests.check_compact_ui import free_port, wait_ready  # noqa: E402

PW_PYTHON = config.REPO_ROOT / "exchange/pwenv/bin/python"
SHOTS = config.REPO_ROOT / "exchange/shots"

FAKE_ENGINE = '''#!{python}
import json, sys, time
args = sys.argv[1:]
prompt = args[args.index("-p") + 1]

def emit(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\\n")
    sys.stdout.flush()

emit({{"type": "system", "subtype": "init", "session_id": "fake-v2", "model": "opus"}})
if prompt == "привет":
    emit({{"type": "assistant", "message": {{"content": [
        {{"type": "tool_use", "name": "Read", "input": {{"file_path": "/tmp/sekret-hoda.md"}}}}]}}}})
    text = "Ответ **жирный** и `код`"
    emit({{"type": "assistant", "message": {{"content": [{{"type": "text", "text": text}}]}}}})
    emit({{"type": "result", "session_id": "fake-v2", "result": text,
          "total_cost_usd": 0.01, "usage": {{"input_tokens": 1, "output_tokens": 1}}}})
elif prompt == "долго":
    time.sleep(60)
else:
    emit({{"type": "result", "session_id": "fake-title", "result": "Заголовок проверки",
          "total_cost_usd": 0, "usage": {{"input_tokens": 1, "output_tokens": 1}}}})
'''

BROWSER = r'''
import sys
from playwright.sync_api import sync_playwright

base, cookie, chat_id, shots = sys.argv[1:5]
fails = []
def check(ok, what):
    print(("OK   " if ok else "FAIL ") + what, flush=True)
    if not ok: fails.append(what)

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1440, "height": 900})
    ctx.add_cookies([{"name": "webui_session", "value": cookie, "url": base}])
    page = ctx.new_page()
    errors = []
    page.on("console", lambda m: m.type == "error" and errors.append(m.text))
    page.on("pageerror", lambda e: errors.append(str(e)))

    page.goto(f"{base}/v2")
    check(page.url.endswith(f"/v2/c/{chat_id}"), f"/v2 открыл последний разговор ({page.url})")

    page.fill("#text", "привет")
    page.press("#text", "Enter")
    page.wait_for_selector(".feed .msg-assistant strong", timeout=15000)
    check(page.locator(".feed .msg-assistant strong").inner_text() == "жирный", "ответ нарисован Markdown'ом")
    check(page.locator(".feed .msg-user").last.inner_text() == "привет", "вопрос в ленте")
    check("sekret-hoda" not in page.locator("body").inner_text(), "ход работы не показан")
    page.wait_for_function("document.querySelector('.head-title').textContent === 'Заголовок проверки'", timeout=15000)
    check(True, "название пришло по первой реплике")
    page.wait_for_function("!document.getElementById('send').disabled", timeout=10000)
    page.screenshot(path=f"{shots}/v2-desktop.png")

    page.fill("#text", "долго")
    page.click("#send")
    page.wait_for_selector("#stop:not([hidden])", timeout=10000)
    check(True, "во время ответа видна кнопка «Стоп»")
    page.click("#stop")
    page.wait_for_selector("#stop[hidden]", state="attached", timeout=15000)
    check(page.locator("#send").is_enabled(), "после «Стоп» можно писать снова")
    page.reload()
    check("Остановлено" in page.locator(".feed").inner_text(), "после перезагрузки в ленте «Остановлено»")

    phone = b.new_context(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True)
    phone.add_cookies([{"name": "webui_session", "value": cookie, "url": base}])
    m = phone.new_page()
    m.on("pageerror", lambda e: errors.append(str(e)))
    m.goto(f"{base}/v2/c/{chat_id}")
    side_x = m.locator("#side").bounding_box()["x"]
    check(side_x < 0, f"на телефоне список спрятан (x={side_x})")
    m.click("#side-toggle")
    m.wait_for_timeout(400)
    check(m.locator("#side").bounding_box()["x"] >= 0, "кнопка ☰ открывает список")
    m.screenshot(path=f"{shots}/v2-phone-side.png")
    m.mouse.click(370, 400)
    m.wait_for_timeout(400)
    check(m.locator("#side").bounding_box()["x"] < 0, "нажатие мимо закрывает список")
    wide = m.evaluate("document.documentElement.scrollWidth")
    check(wide <= 390, f"страница не едет вбок ({wide} px)")
    m.screenshot(path=f"{shots}/v2-phone.png")

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


def main() -> int:
    if not PW_PYTHON.is_file():
        print(f"FAIL нет Playwright: {PW_PYTHON}")
        return 1
    db.init_pool()
    user = db.query_one("SELECT id FROM users ORDER BY id LIMIT 1")
    tmp = Path(tempfile.mkdtemp(prefix="check-v2-"))
    engine = tmp / "fake-claude"
    engine.write_text(FAKE_ENGINE.format(python=sys.executable), encoding="utf-8")
    engine.chmod(0o755)

    session_id = security.new_session_id()
    db.execute(
        "INSERT INTO sessions (id, user_id, expires_at, ip, user_agent) VALUES (%s, %s, %s, %s, %s)",
        (session_id, user["id"], security.session_expiry(), "127.0.0.1", "check_v2"),
    )
    # Завтрашнее время — чтобы разговор точно был последним
    chat = db.query_one(
        "INSERT INTO conversations (kind, title, updated_at) "
        "VALUES ('chat', 'Новый чат', now() + interval '1 day') RETURNING id"
    )

    port = free_port()
    proc = subprocess.Popen(
        [str(PROJECT_DIR / ".venv/bin/python"), "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=str(PROJECT_DIR), env=dict(os.environ, CLAUDE_BIN=str(engine), ROOT_PATH=""),
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
             security.sign_session_id(session_id), str(chat["id"]), str(SHOTS)],
            capture_output=True, text=True, timeout=240,
        )
        print(res.stdout.rstrip())
        if res.returncode:
            failures.append("браузер")
            print(res.stderr[-2000:])
        stopped = db.query_one(
            "SELECT 1 AS ok FROM messages WHERE conversation_id = %s AND content = 'Остановлено'",
            (chat["id"],),
        )
        check(bool(stopped), "«Остановлено» записано в базу")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        db.execute("DELETE FROM conversations WHERE id = %s", (chat["id"],))
        db.execute("DELETE FROM sessions WHERE id = %s", (session_id,))
        shutil.rmtree(tmp, ignore_errors=True)

    print("ПРОВАЛОВ:", len(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
