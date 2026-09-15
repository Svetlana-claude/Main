"""Снимки экрана для «Руководства пользователя».

Поднимает отдельный экземпляр приложения на свободном порту — с временной базой
`webui_demo`, одноразовым SECRET_KEY, подставным `claude` и заглушками обёрток
VPN и аудита. Рабочую службу, её базу и ключи не трогает: в руководство не
попадает ни одной настоящей темы, чатика, адреса или отчёта.

Данные вымышленные: проект «Сайт-визитка», две темы, чатик, клиенты VPN,
отчёт аудита. Проходит настоящим путём: первый вход с паролем по умолчанию,
смена пароля, работа, подключение второго фактора, вход с кодом.

Браузер — Playwright из `exchange/pwenv`. Запуск:
    .venv/bin/python manual/make_shots.py
Снимки — в `manual/shots/` (вне версий). После прогона временная база
и роль удаляются.
"""
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_DIR = HERE.parent
REPO_ROOT = PROJECT_DIR.parent
PW_PYTHON = REPO_ROOT / "exchange/pwenv/bin/python"
SHOTS = HERE / "shots"

DEMO_DB = "webui_demo"
DEMO_PASSWORD = "Руководство-2026"

FAKE_ENGINE = '''#!/usr/bin/env python3
import json, sys, time
args = sys.argv[1:]
prompt = args[args.index("-p") + 1]

def emit(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\\n")
    sys.stdout.flush()

def start(ctx):
    emit({"type": "stream_event", "parent_tool_use_id": None, "event": {"type": "message_start",
          "message": {"usage": {"input_tokens": 12, "cache_read_input_tokens": ctx,
                                "cache_creation_input_tokens": 900, "output_tokens": 0}}}})

emit({"type": "system", "subtype": "init", "session_id": "demo-session", "model": "claude-opus-5"})
if prompt.startswith("Придумай короткое название"):
    emit({"type": "result", "session_id": "demo-session", "result": "Подбор шрифта для сайта",
          "total_cost_usd": 0.001, "usage": {"input_tokens": 40, "output_tokens": 6}})
    sys.exit(0)
if prompt == "/compact":
    emit({"type": "system", "subtype": "status", "status": "compacting"})
    time.sleep(1)
    emit({"type": "system", "subtype": "compact_boundary",
          "compact_metadata": {"trigger": "manual", "pre_tokens": 184000, "post_tokens": 9800}})
    emit({"type": "result", "session_id": "demo-session", "total_cost_usd": 0.31,
          "usage": {"input_tokens": 0, "output_tokens": 0}})
    sys.exit(0)
start(48000)
for name, inp in [("Read", {"file_path": "index.html"}), ("Grep", {"pattern": "form"}),
                  ("Edit", {"file_path": "css/style.css"}), ("Write", {"file_path": "downloads/otchet.md"})]:
    emit({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": name, "input": inp}]}})
    time.sleep(1.2)
    start(48000 + 3000)
text = "Готово: форма обратной связи свёрстана, стили вынесены в css/style.css, краткий отчёт — в downloads/otchet.md."
for word in text.split(" "):
    emit({"type": "stream_event", "parent_tool_use_id": None, "event": {"type": "content_block_delta",
          "delta": {"type": "text_delta", "text": word + " "}}})
    time.sleep(0.15)
emit({"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}})
emit({"type": "result", "session_id": "demo-session", "result": text, "total_cost_usd": 0.42,
      "duration_ms": 14200, "num_turns": 5,
      "usage": {"input_tokens": 60, "output_tokens": 820, "cache_read_input_tokens": 51000,
                "cache_creation_input_tokens": 900},
      "modelUsage": {"claude-opus-5": {"outputTokens": 820}}})
'''

VPN_STUB = """#!/bin/bash
case "$1" in
    status) echo "interface: wg0"; echo "  public key: DEMOKEY="; echo "  listening port: 51820" ;;
    peers)
        printf 'noutbuk\\t10.8.0.2/32\\tKEYA\\t734003200\\t52428800\\t%s\\t198.51.100.20:51034\\n' "$(date +%s)"
        printf 'telefon\\t10.8.0.3/32\\tKEYB\\t20971520\\t4194304\\t%s\\t203.0.113.7:40112\\n' "$(( $(date +%s) - 7200 ))"
        ;;
    *) exit 1 ;;
esac
"""

SEC_STUB = """#!/bin/bash
case "$1" in
    status)
        echo "baseline=2026-09-14T00:12:00+00:00"
        echo "last_report=$(date +%F)"
        echo "fail2ban=active"
        echo "v4_policy=-P INPUT DROP"
        echo "v6_policy=-P INPUT DROP"
        echo "firewall_applied=2026-09-14T00:10:00+00:00"
        echo "quarantine=0"
        ;;
    *) echo "ОТКАЗ: неизвестная команда" >&2; exit 1 ;;
esac
"""

REPORT = """# Отчёт безопасности — {date}

Сервер: пример. Аудит выполнен ночью в 00:00.

## Оценка
Ночь спокойная: расхождение одно, объяснимое.

## Расхождения с эталоном (машинная проверка)

### Расхождение с эталоном: PACKAGES
  ПОЯВИЛОСЬ: qrencode 4.1.1
"""

DEMO_CONF = """[Interface]
PrivateKey = ПРИМЕР-НЕ-НАСТОЯЩИЙ-КЛЮЧ
Address = 10.8.0.2/32
DNS = 1.1.1.1

[Peer]
PublicKey = ПРИМЕР
Endpoint = example.ru:51820
AllowedIPs = 0.0.0.0/0
"""


def psql(sql: str) -> None:
    subprocess.run(["sudo", "-n", "-u", "postgres", "psql", "-q", "-v", "ON_ERROR_STOP=1", "-c", sql],
                   check=True, capture_output=True, text=True)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_ready(port: int, proc: subprocess.Popen) -> bool:
    for _ in range(60):
        if proc.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=2) as r:
                if r.status == 200:
                    return True
        except OSError:
            time.sleep(0.5)
    return False


def seed(env: dict, work: Path) -> dict:
    """Заводит вымышленные данные прямо в демо-базе."""
    import psycopg
    from psycopg.rows import dict_row

    now = datetime.now(timezone.utc)
    ids: dict = {}
    workdir = work / "main" / "sait-vizitka"
    (workdir / "downloads" / "maket").mkdir(parents=True)
    (workdir / "downloads" / "plan-raboty.md").write_text("# План работ\n", encoding="utf-8")
    (workdir / "downloads" / "maket" / "glavnaya.html").write_text("<!doctype html>\n", encoding="utf-8")
    (workdir / "downloads" / "tekst-dlya-sayta.docx").write_bytes(b"0" * 18_000)

    with psycopg.connect(env["DATABASE_URL"], row_factory=dict_row, autocommit=True) as c:
        p = c.execute("INSERT INTO projects (name, slug, workdir) VALUES ('Сайт-визитка', 'sait-vizitka', %s) "
                      "RETURNING id", (str(workdir),)).fetchone()
        ids["project"] = p["id"]

        def topic(title, ctx, hours_ago):
            return c.execute(
                "INSERT INTO conversations (kind, project_id, title, claude_session_id, context_tokens, context_at, updated_at) "
                "VALUES ('topic', %s, %s, 'demo-session', %s, %s, %s) RETURNING id",
                (p["id"], title, ctx, now - timedelta(hours=hours_ago), now - timedelta(hours=hours_ago)),
            ).fetchone()["id"]

        def msg(conv, role, text, minutes_ago, cost=0, inp=0, out=0, dur=0):
            c.execute(
                "INSERT INTO messages (conversation_id, role, content, created_at, model, input_tokens, "
                "output_tokens, cost_usd, duration_ms, num_turns) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (conv, role, text, now - timedelta(minutes=minutes_ago),
                 "claude-opus-5" if role == "assistant" else None, inp, out, cost, dur, 3 if role == "assistant" else 0),
            )

        t1 = topic("Вёрстка главной страницы", 36000, 3)
        msg(t1, "user", "Сверстай главную страницу по плану из downloads/plan-raboty.md: шапка, "
                        "блок услуг, контакты. Адаптивно, без сторонних библиотек.", 190)
        msg(t1, "assistant", "Главная страница готова: index.html и css/style.css. Шапка с меню, три "
                             "карточки услуг, блок контактов; на узком экране карточки встают в столбик. "
                             "Макет для просмотра положил в downloads/maket/glavnaya.html.", 185,
            cost=0.38, inp=2400, out=1650, dur=41000)
        t2 = topic("Форма обратной связи", 184000, 2)
        msg(t2, "user", "Добавь форму обратной связи: имя, телефон, сообщение.", 130)
        msg(t2, "assistant", "Форма добавлена в раздел контактов, поля проверяются в браузере.", 125,
            cost=0.21, inp=900, out=640, dur=18000)
        topic("Тексты для сайта", 0, 1)
        t3 = topic("Страница с ценами", 92000, 0.5)
        msg(t3, "user", "Сделай страницу с ценами: три тарифа карточками.", 40)
        msg(t3, "error", "You've hit your limit · resets 9:50am (UTC)", 39)
        ids["limit_topic"] = t3
        ids["topic"] = t2

        ch = c.execute("INSERT INTO conversations (kind, title, updated_at) VALUES ('chat', 'Подбор шрифта для сайта', %s) "
                       "RETURNING id", (now - timedelta(minutes=50),)).fetchone()["id"]
        msg(ch, "user", "Какой шрифт выбрать для сайта-визитки психолога, чтобы было спокойно и читаемо?", 55)
        msg(ch, "assistant", "Для спокойного и читаемого текста подойдут шрифты с мягкими формами:\n\n"
                             "* PT Sans или Source Sans 3 — для основного текста;\n"
                             "* Lora или PT Serif — для заголовков, если хочется тепла.\n\n"
                             "Размер основного текста — от 16 px, межстрочный интервал 1,5.", 54,
            cost=0.02, inp=180, out=210, dur=6000)
        c.execute("INSERT INTO conversations (kind, title, updated_at) VALUES ('chat', 'Письмо заказчику', %s)",
                  (now - timedelta(days=1),))
        ids["chat"] = ch

        c.execute("INSERT INTO files (project_id, filename, stored_name, size_bytes, mime, created_at) VALUES "
                  "(%s, 'логотип.svg', 'demo-logo.svg', 4200, 'image/svg+xml', %s), "
                  "(%s, 'фото-кабинета.jpg', 'demo-photo.jpg', 842000, 'image/jpeg', %s)",
                  (p["id"], now - timedelta(hours=5), p["id"], now - timedelta(hours=4)))

        for i in range(24 * 12):
            at = now - timedelta(minutes=5 * i)
            wave = (i % 36) / 36
            c.execute("INSERT INTO metrics_history (at, cpu_pct, mem_pct, disk_pct, load1) VALUES (%s,%s,%s,%s,%s) "
                      "ON CONFLICT DO NOTHING",
                      (at, 6 + 30 * wave * wave, 41 + 8 * wave, 23, 0.2 + wave))
    return ids


BROWSER = r'''
import json, sys, time
from playwright.sync_api import sync_playwright

base, shots, password, ids_json = sys.argv[1:5]

import base64, hashlib, hmac, struct
def totp_now(secret):
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    digest = hmac.new(key, struct.pack(">Q", int(time.time()) // 30), hashlib.sha1).digest()
    off = digest[-1] & 15
    return "%06d" % ((struct.unpack(">I", digest[off:off + 4])[0] & 0x7FFFFFFF) % 1000000)
ids = json.loads(ids_json)
errors = []

def shot(page, name, full=False):
    page.wait_for_timeout(400)
    page.screenshot(path=f"{shots}/{name}.png", full_page=full)
    print("снимок", name, flush=True)

with sync_playwright() as p:
    b = p.chromium.launch(args=["--lang=ru-RU"])
    ctx = b.new_context(viewport={"width": 1440, "height": 860}, locale="ru-RU", device_scale_factor=1)
    page = ctx.new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: m.type == "error" and errors.append(m.text))
    page.on("dialog", lambda d: d.accept())
    page.on("response", lambda r: r.status >= 400 and print("  ответ", r.status, r.url, flush=True))

    # Первый вход: пароль по умолчанию, обязательная смена
    page.goto(base + "/login")
    page.fill("#login", "Svetlana")
    shot(page, "01-login")
    page.fill("#password", "admin")
    page.click("form[action$='/login'] button[type=submit]")
    page.wait_for_url("**/password**")
    page.fill("#current", "admin")
    page.fill("#password", password)
    page.fill("#confirm", password)
    shot(page, "02-password")
    page.click("form[action$='/password'] button[type=submit]")
    page.wait_for_load_state("networkidle")

    page.goto(base + "/")
    page.wait_for_timeout(2500)
    shot(page, "03-dashboard", full=True)

    page.goto(base + f"/chats?id={ids['chat']}")
    shot(page, "04-chats")
    if "/login" in page.url:
        raise SystemExit("сессия потеряна после смены пароля")

    page.goto(base + f"/projects?id={ids['project']}&topic={ids['topic']}")
    page.wait_for_timeout(800)
    shot(page, "05-project")
    page.click("#tab-tree")
    page.wait_for_timeout(800)
    shot(page, "06-project-files")
    page.click("#tab-upload")

    page.fill("#text", "Сделай форму отправляемой на почту и опиши, что поменялось, в downloads/otchet.md")
    page.click("#send-btn")
    page.wait_for_timeout(4200)
    shot(page, "07-project-running")
    page.wait_for_timeout(9000)
    shot(page, "08-project-done")

    page.click("#compact-btn")
    page.wait_for_timeout(3500)
    shot(page, "09-project-compact")

    page.goto(base + "/vpn")
    page.wait_for_timeout(800)
    shot(page, "10-vpn", full=True)

    page.goto(base + "/sec")
    shot(page, "11-security", full=True)

    page.goto(base + "/settings")
    shot(page, "12-settings", full=True)

    page.goto(base + f"/projects?id={ids['project']}&topic={ids['limit_topic']}")
    shot(page, "17-limit")

    page.goto(base + "/search?q=форма")
    shot(page, "14-search")

    page.goto(base + "/journal")
    shot(page, "15-journal")

    # Тёмная тема — для раздела о настройках
    page.goto(base + "/settings")
    page.select_option("#theme", "dark")
    page.click("form[action$='/settings/save'] button[type=submit]")
    page.wait_for_load_state("networkidle")
    page.goto(base + f"/projects?id={ids['project']}&topic={ids['topic']}")
    shot(page, "16-dark")
    page.goto(base + "/settings")
    page.select_option("#theme", "light")
    page.click("form[action$='/settings/save'] button[type=submit]")
    page.wait_for_load_state("networkidle")
    page.goto(base + "/settings/totp")
    page.click("form[action$='/totp/start'] button")
    page.wait_for_load_state("networkidle")
    secret = page.locator(".mono.breakable").inner_text().replace(" ", "")
    # Ключ на снимке размывается: страница сама просит не снимать его, и
    # руководство не должно учить обратному, даже на одноразовом примере.
    page.add_style_tag(content="[role=img][aria-label^='QR'], .mono.breakable { filter: blur(7px); }")
    shot(page, "13-totp-setup", full=True)
    page.fill("#en-code", totp_now(secret))
    page.click("form[action$='/totp/enable'] button[type=submit]")
    page.wait_for_load_state("networkidle")
    page.click("form[action$='/logout'] button")
    page.wait_for_load_state("networkidle")
    page.fill("#login", "Svetlana")
    page.fill("#password", password)
    page.click("form[action$='/login'] button[type=submit]")
    page.wait_for_load_state("networkidle")
    shot(page, "18-login-code")

    b.close()

print("ошибки консоли:", errors)
'''


def main() -> int:
    if not PW_PYTHON.is_file():
        print(f"нет Playwright: {PW_PYTHON}")
        return 1
    work = Path("/tmp/primer")
    shutil.rmtree(work, ignore_errors=True)       # остаток прошлого прогона этого же сценария
    work.mkdir()
    db_password = secrets.token_hex(16)
    env = dict(
        os.environ,
        DATABASE_URL=f"postgresql://{DEMO_DB}:{db_password}@127.0.0.1:5432/{DEMO_DB}",
        SECRET_KEY=secrets.token_hex(32),
        WEBUI_ENV=str(work / "none.env"),
        REPO_ROOT=str(work / "main"),
        ROOT_PATH="",                     # экземпляр без nginx: адреса опроса без префикса
        CLAUDE_BIN=str(work / "fake-claude"),
        WEBUI_VPN_CMD=str(work / "vpn-stub"),
        WEBUI_SEC_CMD=str(work / "sec-stub"),
        WEBUI_SEC_STATE=str(work / "sec-state"),
        WEBUI_SEC_LIB=str(work / "sec-lib"),
    )
    for name, text in (("fake-claude", FAKE_ENGINE), ("vpn-stub", VPN_STUB), ("sec-stub", SEC_STUB)):
        (work / name).write_text(text, encoding="utf-8")
        (work / name).chmod(0o755)
    (work / "main" / "exchange" / "vpn").mkdir(parents=True)
    (work / "main" / "exchange" / "vpn" / "noutbuk.conf").write_text(DEMO_CONF, encoding="utf-8")
    (work / "main" / "exchange" / "vpn" / "telefon.conf").write_text(DEMO_CONF, encoding="utf-8")
    for f in ("CLAUDE.md", "architect.md", "result.md", "current_questions.md", "tech_debt.md", "log.md"):
        (work / "main" / f).write_text(f"# {f}\n\nПример файла сопровождения.\n", encoding="utf-8")
    today = datetime.now().strftime("%Y-%m-%d")
    (work / "sec-state" / "reports").mkdir(parents=True)
    (work / "sec-state" / "reports" / f"rep_{today}.md").write_text(REPORT.format(date=today), encoding="utf-8")
    stamp = datetime.now(timezone.utc).replace(hour=0, minute=0, second=1, microsecond=0)
    (work / "sec-state" / "audit.log").write_text(
        f"[{stamp.isoformat()}] === запуск аудита ===\n"
        f"[{(stamp + timedelta(seconds=23)).isoformat()}] готово: {work}/sec-state/reports/rep_{today}.md\n",
        encoding="utf-8")
    (work / "sec-lib").mkdir()
    (work / "sec-lib" / "audit.sh").write_text("#!/bin/bash\nsleep 1\necho 'готово: 1 находка'\n", encoding="utf-8")

    psql(f"DROP DATABASE IF EXISTS {DEMO_DB}")
    psql(f"DROP ROLE IF EXISTS {DEMO_DB}")
    psql(f"CREATE ROLE {DEMO_DB} LOGIN PASSWORD '{db_password}'")
    psql(f"CREATE DATABASE {DEMO_DB} OWNER {DEMO_DB}")
    proc = None
    try:
        port = free_port()
        proc = subprocess.Popen(
            [str(PROJECT_DIR / ".venv/bin/python"), "-m", "uvicorn", "app.main:app",
             "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
            cwd=str(PROJECT_DIR), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        if not wait_ready(port, proc):
            print("демо-экземпляр не поднялся:", proc.stderr.read().decode()[-2000:] if proc.stderr else "")
            return 1
        ids = seed(env, work)
        SHOTS.mkdir(exist_ok=True)
        script = work / "browser.py"
        script.write_text(BROWSER, encoding="utf-8")
        res = subprocess.run([str(PW_PYTHON), str(script), f"http://127.0.0.1:{port}", str(SHOTS),
                              DEMO_PASSWORD, json.dumps(ids)], capture_output=True, text=True, timeout=300)
        print(res.stdout.rstrip())
        if res.returncode:
            print(res.stderr[-3000:])
            return 1
        return 0
    finally:
        if proc:
            proc.terminate()
            proc.wait(timeout=10)
        psql(f"DROP DATABASE IF EXISTS {DEMO_DB} WITH (FORCE)")
        psql(f"DROP ROLE IF EXISTS {DEMO_DB}")
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
