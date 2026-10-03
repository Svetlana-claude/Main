"""Проверка выбора модели и потолка контекста на тему (и на чатик).

Зачем: шаг агента стоит одинаково, что бы он ни делал, — значит правки вёрстки
и прогон проверок незачем вести на старшей модели с потолком 250 тыс. Выбор
сделан на разговор: `NULL` в `conversations.model` и `.compact_window` означает
«как в „Настройках“» (замер — `optimizaciya/ekonomnaya-rabota.md`).

Проверяется:

* `claude_driver.rezhim` — своё значение темы главнее общего, негодное
  откатывается на «Настройки», потолок ниже 100 тыс. поднимается до границы;
* нажатие кнопки «Применить» в шапке темы — выбор ложится в базу и остаётся
  выбранным после перезагрузки страницы;
* отправка сообщения после этого доходит до движка **с тем самым** `--model`
  и тем самым потолком в окружении, а не с общим из «Настроек»;
* негодная модель в запросе записывается как «как в настройках», а не как есть.

Поднимается второй экземпляр приложения на свободном порту с подставным
`claude` — рабочая служба не трогается. Браузер — Playwright из
`exchange/pwenv`.

Запуск:  .venv/bin/python tests/check_rezhim_razgovora.py
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from app import config, db, security                  # noqa: E402
from app.services import claude_driver                # noqa: E402

PW_PYTHON = config.REPO_ROOT / "exchange/pwenv/bin/python"
SHOTS = config.REPO_ROOT / "exchange/shots"

# Подставной движок: пишет рядом с собой, с какой моделью и каким потолком
# его позвали. По этому файлу и видно, дошёл ли выбор темы до `claude`.
FAKE_ENGINE = '''#!{python}
import json, os, sys
from pathlib import Path

args = sys.argv[1:]
prompt = args[args.index("-p") + 1]
model = args[args.index("--model") + 1] if "--model" in args else None
with open(Path(__file__).parent / "calls.jsonl", "a") as f:
    f.write(json.dumps({{"prompt": prompt, "model": model,
        "window": os.environ.get("CLAUDE_CODE_AUTO_COMPACT_WINDOW")}}) + "\\n")

def emit(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\\n")
    sys.stdout.flush()

emit({{"type": "system", "subtype": "init", "session_id": "fake-session", "model": model}})
emit({{"type": "assistant", "message": {{"content": [{{"type": "text", "text": "ответ-проверки"}}]}}}})
emit({{"type": "result", "session_id": "fake-session", "result": "ответ-проверки",
      "total_cost_usd": 0.01, "usage": {{"input_tokens": 20, "output_tokens": 30}}}})
'''

BROWSER = r'''
import sys
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

    page.goto(f"{base}/projects?id={pid}&topic={tid}")
    model = page.locator("#rezhim-model")
    window = page.locator("#rezhim-window")
    check(model.count() == 1 and window.count() == 1, "в шапке темы есть выбор модели и потолка")
    check(model.input_value() == "" and window.input_value() == "",
          "у новой темы оба поля — «как в настройках»")

    # Выбор именно нажатием кнопки: правка обработчика проверяется нажатием.
    model.select_option("sonnet")
    window.select_option("100000")
    page.locator("#rezhim-btn").click()
    page.wait_for_load_state()
    page.screenshot(path=f"{shots}/rezhim-temy.png")
    check(page.locator("#rezhim-model").input_value() == "sonnet",
          "после нажатия модель осталась выбранной (sonnet)")
    check(page.locator("#rezhim-window").input_value() == "100000",
          "после нажатия потолок остался выбранным (100 тыс.)")

    page.reload()
    check(page.locator("#rezhim-model").input_value() == "sonnet"
          and page.locator("#rezhim-window").input_value() == "100000",
          "после перезагрузки выбор читается из базы")

    page.fill("#text", "проверка выбора модели")
    page.click("#send-btn")
    page.wait_for_function(
        "document.querySelector('#scroll').innerText.includes('ответ-проверки')", timeout=30000)
    check(True, "сообщение в теме отправлено и ответ пришёл")

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


def proverit_vybor() -> None:
    """Сам выбор, без сервера: что главнее и что делается с негодным."""
    obshchie = {"model": "opus", "compact_window": "250000"}

    check(claude_driver.rezhim({}, obshchie) == ("opus", 250000),
          "пустая тема — модель и потолок из «Настроек»")
    check(claude_driver.rezhim({"model": "sonnet", "compact_window": 100000}, obshchie)
          == ("sonnet", 100000), "своё значение темы главнее общего")
    check(claude_driver.rezhim({"model": "sonnet", "compact_window": None}, obshchie)
          == ("sonnet", 250000), "модель своя, потолок общий")
    check(claude_driver.rezhim({"model": None, "compact_window": 150000}, obshchie)
          == ("opus", 150000), "потолок свой, модель общая")
    check(claude_driver.rezhim({"model": "мусор"}, obshchie) == ("opus", 250000),
          "негодная модель темы откатывается на «Настройки»")
    check(claude_driver.rezhim({"compact_window": 60000}, obshchie) == ("opus", 100000),
          "потолок ниже 100 тыс. поднимается до нижней границы")
    check(claude_driver.rezhim(None, {}) == ("opus", 0),
          "без настроек вовсе — opus и потолок не задан")


def main() -> int:
    proverit_vybor()
    if not PW_PYTHON.is_file():
        print(f"FAIL нет Playwright: {PW_PYTHON} — браузерная проверка не проведена")
        return 1

    db.init_pool()
    db.apply_schema()          # поля model и compact_window нужны до записи

    user = db.query_one("SELECT id FROM users ORDER BY id LIMIT 1")
    tmp = Path(tempfile.mkdtemp(prefix="rezhim-"))
    engine = tmp / "fake-claude"
    engine.write_text(FAKE_ENGINE.format(python=sys.executable), encoding="utf-8")
    engine.chmod(0o755)
    workdir = tmp / "project"
    workdir.mkdir()

    session_id = security.new_session_id()
    db.execute(
        "INSERT INTO sessions (id, user_id, expires_at, ip, user_agent) VALUES (%s, %s, %s, %s, %s)",
        (session_id, user["id"], security.session_expiry(), "127.0.0.1", "check_rezhim"),
    )
    project = db.query_one(
        "INSERT INTO projects (name, slug, workdir) VALUES (%s, %s, %s) RETURNING id",
        ("Проверка выбора модели", f"check-rezhim-{os.getpid()}", str(workdir)),
    )
    topic = db.query_one(
        "INSERT INTO conversations (kind, project_id, title) "
        "VALUES ('topic', %s, 'Рутинная тема') RETURNING id",
        (project["id"],),
    )
    # Общая настройка нарочно другая: если выбор темы не доедет, в вызове
    # окажется opus с потолком 250 тыс., и это сразу видно.
    db.set_setting("model", "opus")
    db.set_setting("compact_window", "250000")

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
        cookie = security.sign_session_id(session_id)
        res = subprocess.run(
            [str(PW_PYTHON), str(script), f"http://127.0.0.1:{port}", cookie,
             str(project["id"]), str(topic["id"]), str(SHOTS)],
            capture_output=True, text=True, timeout=240,
        )
        print(res.stdout.rstrip())
        if res.returncode:
            failures.append("браузер")
            print(res.stderr[-2000:])

        row = db.query_one(
            "SELECT model, compact_window FROM conversations WHERE id = %s", (topic["id"],))
        check(row["model"] == "sonnet" and row["compact_window"] == 100000,
              f"выбор темы в базе ({row['model']}, {row['compact_window']})")

        calls = [json.loads(s) for s in (tmp / "calls.jsonl").read_text().splitlines()] \
            if (tmp / "calls.jsonl").exists() else []
        print("  вызовы claude:", calls)
        check(len(calls) == 1, f"движок позван один раз ({len(calls)})")
        check(bool(calls) and calls[0]["model"] == "sonnet",
              f"модель темы дошла до движка ({calls[0]['model'] if calls else '—'})")
        check(bool(calls) and calls[0]["window"] == "100000",
              f"потолок темы дошёл до движка ({calls[0]['window'] if calls else '—'})")

        # Негодное значение в запросе: записывается «как в настройках», а не как есть.
        telo = urllib.parse.urlencode({"model": "мусор", "compact_window": "ерунда"}).encode()
        zapros = urllib.request.Request(
            f"http://127.0.0.1:{port}/projects/topics/{topic['id']}/rezhim",
            data=telo, headers={"Cookie": f"webui_session={cookie}"})
        try:
            urllib.request.urlopen(zapros, timeout=10).read()
        except urllib.error.HTTPError as err:
            check(False, f"запрос с негодными значениями отказал: {err.code}")
        row = db.query_one(
            "SELECT model, compact_window FROM conversations WHERE id = %s", (topic["id"],))
        check(row["model"] is None and row["compact_window"] is None,
              f"негодные значения записаны как «как в настройках» ({row['model']}, {row['compact_window']})")
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
