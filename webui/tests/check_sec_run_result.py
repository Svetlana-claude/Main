"""Проверка: итог ручного прогона аудита виден, откуда бы ни вернулись на страницу.

Случай 15.09.2026: нажали «Прогнать с устранением», ушли на «Дашборд»,
вернулись — надпись «Идёт прогон» погасла, а больше страница ничего не
сказала. Прогон на деле закончился за 16 секунд и записал отчёт, но выглядело
это как обрыв из-за ухода со страницы.

Что проверяется:

* разбор журнала аудита: законченный, с ошибкой сбора, оборванный, идущий;
* сбой запуска, которого журнал не видит (аудит не стартовал), тоже виден;
* перезапуск службы из «Настроек» ждёт идущего прогона — иначе обрыв был бы
  настоящим: аудит живёт в контрольной группе `webui.service`;
* в браузере: нажать кнопку, уйти на «Дашборд», вернуться — итог на месте;
* остаться на странице — она сама обновится, и «Прогон запущен» не повиснет
  после конца прогона.

Стенд поднимает второй экземпляр приложения на свободном порту с заглушкой
обёртки и своим `audit.sh`, который пишет журнал как настоящий, но ничего не
проверяет. Рабочую службу и настоящий аудит не трогает.

Запуск:  .venv/bin/python tests/check_sec_run_result.py
"""
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db, security as auth                  # noqa: E402
from app.services import restart                      # noqa: E402
from app.services import security as sec              # noqa: E402

PROJECT_DIR = Path(__file__).resolve().parent.parent
FAILED: list[str] = []


def check(ok: bool, what: str) -> None:
    if ok:
        print(f"  ok: {what}")
    else:
        FAILED.append(what)
        print(f"  ПРОВАЛ: {what}")


def stamp(at: datetime) -> str:
    return "[" + at.isoformat(timespec="seconds") + "]"


# ── Разбор журнала ────────────────────────────────────────────────────

def check_parse(work: Path) -> None:
    log = work / "audit.log"
    saved = sec.AUDIT_LOG
    sec.AUDIT_LOG = log
    now = datetime.now(timezone.utc)
    try:
        t0 = now - timedelta(minutes=5)
        log.write_text(
            f"{stamp(t0 - timedelta(days=1))} === запуск аудита ===\n"
            f"{stamp(t0 - timedelta(days=1))} ОШИБКА: сбор фактов не выполнен — снимок пуст\n"
            f"{stamp(t0)} === запуск аудита ===\n"
            f"{stamp(t0 + timedelta(seconds=16))} готово: /var/lib/secaudit/reports/rep_2026-09-15.md\n",
            encoding="utf-8")
        run = sec.last_run(active=False)
        check(run.status == "готово", f"законченный прогон назван «готово» (получили «{run.status}»)")
        check(run.seconds == 16, f"длительность 16 с (получили {run.seconds})")
        check(run.report_date == "2026-09-15", "из строки «готово» взята дата отчёта")
        check(run.message == "", "ошибка прошлого прогона не перешла на новый")

        log.write_text(
            f"{stamp(t0)} === запуск аудита ===\n"
            f"{stamp(t0)} ОШИБКА: сбор фактов не выполнен — снимок пуст\n"
            f"{stamp(t0 + timedelta(seconds=3))} готово: /x/reports/rep_2026-09-15.md\n",
            encoding="utf-8")
        run = sec.last_run(active=False)
        check(run.status == "ошибка", "пустой снимок при «готово» — всё равно ошибка")
        check("снимок пуст" in run.message, "текст ошибки сбора показан")

        old = now - timedelta(hours=2)
        log.write_text(f"{stamp(old)} === запуск аудита ===\n", encoding="utf-8")
        run = sec.last_run(active=False)
        check(run.status == "оборван", "старт без «готово» старше срока — «оборван»")

        fresh = now - timedelta(seconds=5)
        log.write_text(f"{stamp(fresh)} === запуск аудита ===\n", encoding="utf-8")
        check(sec.last_run(active=False).status == "идёт",
              "свежий старт без «готово» (ночной прогон) — «идёт»")

        log.write_text("", encoding="utf-8")
        check(sec.last_run(active=False).status == "", "пустой журнал — прогонов не было")

        # Аудит не запустился вовсе: в журнале ничего, отметка в памяти — ошибка
        with sec._run_lock:
            sec._running.update(active=False, started=now.timestamp(),
                                error="не удалось запустить аудит: нет файла")
        run = sec.last_run(active=False)
        check(run.status == "ошибка" and "не удалось" in run.message,
              "сбой запуска мимо журнала виден как ошибка")
        with sec._run_lock:
            sec._running.update(active=False, started=0.0, error="")
    finally:
        sec.AUDIT_LOG = saved


def check_restart_waits() -> None:
    with sec._run_lock:
        sec._running["active"] = True
    try:
        check(restart._busy() >= 1, "перезапуск считает идущий прогон аудита незаконченной работой")
    finally:
        with sec._run_lock:
            sec._running["active"] = False


# ── Страница в браузере ───────────────────────────────────────────────

STUB = """#!/bin/bash
case "$1" in
    status)
        echo "baseline=2026-09-12T00:11:22+00:00"
        echo "fail2ban=active"
        echo "v4_policy=-P INPUT DROP"
        echo "v6_policy=-P INPUT DROP"
        echo "firewall_applied=нет"
        echo "quarantine=0"
        ;;
    *) echo "ОТКАЗ" >&2; exit 1 ;;
esac
"""

# Пишет журнал и отчёт так же, как настоящий audit.sh, но ничего не проверяет
AUDIT = """#!/bin/bash
STATE=$WEBUI_SEC_STATE
LOG=$STATE/audit.log
echo "[$(date -Is)] === запуск аудита ===" >> "$LOG"
sleep 6
d=$(date +%F)
printf '# Отчёт безопасности — %s\\n\\nРасхождений с эталоном нет.\\n' "$d" > "$STATE/reports/rep_$d.md"
echo "[$(date -Is)] готово: $STATE/reports/rep_$d.md" >> "$LOG"
echo "$STATE/reports/rep_$d.md"
"""


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


def wait_finished(log: Path, runs: int, limit: float = 30) -> bool:
    """Ждём строки «готово» в журнале — по делу, а не по времени."""
    end = time.time() + limit
    while time.time() < end:
        text = log.read_text(encoding="utf-8") if log.exists() else ""
        if text.count("готово:") >= runs:
            return True
        time.sleep(0.3)
    return False


def check_browser(work: Path) -> None:
    from playwright.sync_api import sync_playwright

    user = db.query_one("SELECT id FROM users ORDER BY id LIMIT 1")
    if not user:
        check(False, "в базе нет пользователя — некому открыть панель")
        return
    session_id = auth.new_session_id()
    db.execute(
        "INSERT INTO sessions (id, user_id, expires_at, ip, user_agent) "
        "VALUES (%s, %s, %s, %s, %s)",
        (session_id, user["id"], auth.session_expiry(), "127.0.0.1", "check_sec_run_result"),
    )

    stub = work / "webui-sec-stub"
    stub.write_text(STUB, encoding="utf-8")
    stub.chmod(0o755)
    lib = work / "lib"
    lib.mkdir()
    (lib / "audit.sh").write_text(AUDIT, encoding="utf-8")
    state_dir = work / "state"
    (state_dir / "reports").mkdir(parents=True)
    log = state_dir / "audit.log"

    port = free_port()
    base = f"http://127.0.0.1:{port}"
    # ROOT_PATH пустой: стенд слушает без nginx, и опрос на «/Claude/sec/state»
    # получал бы 404 — страница молча не обновлялась бы, и провал лёг бы на продукт
    env = dict(os.environ, WEBUI_SEC_CMD=str(stub), WEBUI_SEC_STATE=str(state_dir),
               WEBUI_SEC_LIB=str(lib), ROOT_PATH="")
    proc = subprocess.Popen(
        [str(PROJECT_DIR / ".venv/bin/python"), "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=str(PROJECT_DIR), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        if not wait_ready(port, proc):
            check(False, "второй экземпляр не поднялся")
            return
        with sync_playwright() as p:
            browser = p.chromium.launch()
            ctx = browser.new_context()
            ctx.add_cookies([{"name": "webui_session",
                              "value": auth.sign_session_id(session_id), "url": base}])
            page = ctx.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda m: m.type == "error" and errors.append(m.text))

            # 1. Нажали, ушли на «Дашборд», вернулись
            page.goto(f"{base}/sec")
            page.get_by_role("button", name="Прогнать с устранением").click()
            page.wait_for_load_state()
            check(page.locator("#sec-running").is_visible(), "после нажатия видно «Идёт прогон»")
            page.goto(f"{base}/")
            check(wait_finished(log, 1), "прогон дошёл до «готово», хотя со страницы ушли")
            page.goto(f"{base}/sec")
            note = page.locator("#sec-last-run")
            check(note.count() == 1 and note.is_visible(),
                  "по возвращении виден итог прошлого прогона")
            text = note.inner_text() if note.count() else ""
            check("Последний прогон закончен" in text, f"итог назван законченным («{text.strip()}»)")
            check(note.locator("a").count() == 1, "в итоге есть ссылка на отчёт")
            check(not page.locator("#sec-running").is_visible(), "«Идёт прогон» погашено")

            # 2. Остались на странице: она обновится сама и без «Прогон запущен»
            page.get_by_role("button", name="Прогнать без вмешательства").click()
            page.wait_for_load_state()
            check("ok=" in page.url, "после нажатия показано «Прогон запущен»")
            reloaded = False
            for _ in range(80):
                if "ok=" not in page.url:
                    reloaded = True
                    break
                page.wait_for_timeout(500)
            check(reloaded, "по концу прогона страница обновилась без ?ok=")
            page.wait_for_load_state()
            check("Прогон запущен" not in page.content(),
                  "после конца прогона «Прогон запущен» не висит")
            check(page.locator("#sec-last-run").is_visible(), "итог второго прогона виден сразу")
            check(not errors, f"ошибок скрипта нет ({errors})")
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        db.execute("DELETE FROM sessions WHERE id = %s", (session_id,))


def main() -> int:
    db.init_pool()
    work = Path(tempfile.mkdtemp(prefix="sec-run-stand-"))
    try:
        print("Разбор журнала:")
        check_parse(work)
        print("\nПерезапуск службы:")
        check_restart_waits()
        print("\nСтраница в браузере:")
        check_browser(work)
    finally:
        # Заглушки исполняемые: забытые в /tmp, они попадают в ночной отчёт
        # как признак майнера (раздел MINER_IOC)
        shutil.rmtree(work, ignore_errors=True)
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
