"""Проверка: вкладка «Безопасность» показывает состояние и не отдаёт лишнего.

Пять мест, где это ломается незаметно или опасно:

* дата отчёта из браузера уезжает в путь к файлу: `/sec/reports/../../...`
  отдал бы `webui.env` с `SECRET_KEY` — и именно через маршрут, который по
  замыслу раздаёт файлы с чувствительным содержимым;
* молчание аудита показывается как спокойствие: отчёта нет — значит «всё
  хорошо». На деле это значит, что смотреть было некому, и это тревога;
* находки считаются вместе со справочными строками, и тревога горит на
  пустом месте — а отчёт, который каждый день красный, перестают читать;
* пустой эталон принимается за принятый, и панель обещает сверку, которой нет;
* страница не открывается вовсе: маршрут есть, а шаблон падает на живых данных.

Стенд поднимает второй экземпляр приложения на свободном порту (рабочую службу
не трогает), подставляет заглушку обёртки и свой каталог отчётов, заводит себе
сессию в базе и убирает её за собой.

Запуск:  .venv/bin/python tests/check_sec_panel.py
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
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db, security as auth                  # noqa: E402
from app.services import security as sec              # noqa: E402

PROJECT_DIR = Path(__file__).resolve().parent.parent
FAILED: list[str] = []


def check(ok: bool, what: str) -> None:
    if ok:
        print(f"  ok: {what}")
    else:
        FAILED.append(what)
        print(f"  ПРОВАЛ: {what}")


# ── Разбор и счёт ─────────────────────────────────────────────────────

def check_pure() -> None:
    # Дата приходит из браузера и уезжает в путь к файлу
    for bad in ["../../etc/passwd", "2026-9-1", "2026-09-1x", "", "..",
                "2026-09-12/../../x", "x" * 10]:
        try:
            sec.check_date(bad)
            check(False, f"негодная дата «{bad}» принята")
        except sec.SecError:
            check(True, f"негодная дата «{bad}» отвергнута")
    try:
        sec.check_date("2026-09-12")
        check(True, "годная дата принята")
    except sec.SecError:
        check(False, "годная дата отвергнута")

    # Счёт находок: справочные строки находками не являются
    report = "\n".join([
        "# Отчёт безопасности — 2026-09-12",
        "### Расхождение с эталоном: USERS",
        "  ПОЯВИЛОСЬ: audit-probe uid=1001",
        "### Сработал индикатор: MINER_IOC",
        "### Справочно: аккаунты с интерактивной оболочкой",
        "### Справочно: сверка сокетов с правилами не проводилась",
        "обычная строка",
    ])
    check(sec.count_findings(report) == 2,
          "справочные строки в счёт находок не попадают")
    check(sec.count_findings("Расхождений с эталоном нет.") == 0,
          "чистый отчёт даёт ноль находок")


def check_silence() -> None:
    """Молчание аудита — тревога, а не спокойствие."""
    st = sec.State(installed=True, baseline="2026-09-12T00:00:00")
    check(st.silent is True, "без единого отчёта аудит считается молчащим")
    check(st.alarm is True, "молчание зажигает тревогу")

    fresh = datetime.now().timestamp()
    st = sec.State(installed=True, baseline="ok", last_report="2026-09-12",
                   last_report_at=fresh, findings=0)
    check(st.silent is False, "свежий отчёт молчанием не считается")
    check(st.alarm is False, "свежий отчёт без находок тревоги не зажигает")
    check(st.verdict == "спокойно", "итог чистого прогона — «спокойно»")

    old = (datetime.now() - timedelta(hours=sec.SILENCE_HOURS + 1)).timestamp()
    st = sec.State(installed=True, baseline="ok", last_report="2026-09-10",
                   last_report_at=old)
    check(st.silent is True, f"отчёт старше {sec.SILENCE_HOURS} ч — молчание")
    check(st.verdict == "аудит не отрабатывал", "итог молчания назван прямо")

    st = sec.State(installed=True, baseline="", last_report="2026-09-12",
                   last_report_at=fresh, findings=0)
    check(st.alarm is True, "непринятый эталон зажигает тревогу")

    st = sec.State(installed=True, baseline="ok", last_report="2026-09-12",
                   last_report_at=fresh, findings=3)
    check(st.alarm is True, "находки зажигают тревогу")
    check(st.verdict == "находок: 3", "число находок попадает в итог")


# ── Живая страница ────────────────────────────────────────────────────

def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_ready(port: int, proc: subprocess.Popen, tries: int = 60) -> bool:
    """Ждём ответа порта, а не «процесс ещё жив»: живой процесс не значит,
    что приложение поднялось."""
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


STUB = """#!/bin/bash
# Заглушка обёртки webui-sec: отдаёт заранее заданное состояние. Нужна, чтобы
# панель проверялась на непустых данных: на машине без аудита всё было бы
# пустым и прошло бы зелёным, ничего не проверив.
case "$1" in
    status)
        echo "baseline=2026-09-12T00:11:22+00:00"
        echo "last_report=нет"
        echo "fail2ban=active"
        echo "v4_policy=-P INPUT DROP"
        echo "v6_policy=-P INPUT DROP"
        echo "firewall_applied=2026-09-12T00:10:00+00:00"
        echo "quarantine=2"
        ;;
    *) echo "ОТКАЗ: неизвестная команда" >&2; exit 1 ;;
esac
"""

REPORT = """# Отчёт безопасности — {date}

Сервер: проба. Аудит выполнен 12.09.2026 в 00:11 UTC.

## Оценка
Ночь спокойная.

## Расхождения с эталоном (машинная проверка)

### Расхождение с эталоном: USERS
  ПОЯВИЛОСЬ: audit-probe uid=1001 shell=/bin/bash
### Справочно: аккаунты с интерактивной оболочкой
  mokeeva uid=1000 shell=/bin/bash
"""


def check_live() -> None:
    user = db.query_one("SELECT id FROM users ORDER BY id LIMIT 1")
    if not user:
        check(False, "в базе нет ни одного пользователя — некому открыть панель")
        return

    session_id = auth.new_session_id()
    db.execute(
        "INSERT INTO sessions (id, user_id, expires_at, ip, user_agent) "
        "VALUES (%s, %s, %s, %s, %s)",
        (session_id, user["id"], auth.session_expiry(), "127.0.0.1", "check_sec_panel"),
    )
    cookie = f"webui_session={auth.sign_session_id(session_id)}"

    work = Path(tempfile.mkdtemp(prefix="sec-stand-"))
    stub = work / "webui-sec-stub"
    stub.write_text(STUB, encoding="utf-8")
    stub.chmod(0o755)

    state_dir = work / "state"
    (state_dir / "reports").mkdir(parents=True)
    today = datetime.now().strftime("%Y-%m-%d")
    (state_dir / "reports" / f"rep_{today}.md").write_text(
        REPORT.format(date=today), encoding="utf-8")

    # Приманка рядом с каталогом отчётов: если сверки даты нет, её отдадут.
    (work / "secret.txt").write_text("SECRET_KEY=poddelka", encoding="utf-8")

    port = free_port()
    env = dict(
        os.environ,
        WEBUI_SEC_CMD=str(stub),
        WEBUI_SEC_STATE=str(state_dir),
        WEBUI_SEC_LIB=str(work),
    )
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

        def get(path: str) -> tuple[int, str]:
            req = urllib.request.Request(f"http://127.0.0.1:{port}{path}",
                                         headers={"Cookie": cookie})
            try:
                with urllib.request.urlopen(req, timeout=15) as res:
                    return res.status, res.read().decode("utf-8", "replace")
            except urllib.error.HTTPError as exc:
                return exc.code, exc.read().decode("utf-8", "replace")

        status, body = get("/sec")
        check(status == 200, f"страница /sec отвечает 200 (получили {status})")
        check("Прогнать с устранением" in body, "кнопка ручного прогона на месте")
        check("Прогнать без вмешательства" in body, "кнопка прогона без правок на месте")
        check("Принять эталон" in body, "кнопка приёма эталона на месте")
        check(today in body, "отчёт за сегодня попал в список")
        # Находка одна: справочная строка в счёт не идёт.
        check('id="sec-verdict">находок: 1<' in body,
              "в итоге ровно одна находка, справочная строка не в счёт")
        check("работает" in body, "состояние fail2ban показано")
        check("-P INPUT DROP" in body, "политика файрвола показана")

        # Вкладка есть в шапке — иначе до панели просто не дойти
        check("Безопасность" in body, "вкладка «Безопасность» есть в шапке")

        status, body = get("/sec/state")
        check(status == 200, f"опрос состояния отвечает 200 (получили {status})")
        data = json.loads(body)
        check(data.get("findings") == 1, "опрос отдаёт то же число находок")
        check(data.get("running") is False, "опрос знает, что прогон не идёт")
        check(data.get("alarm") is True, "при находке опрос зажигает тревогу")

        status, body = get(f"/sec/reports/{today}")
        check(status == 200, f"отчёт открывается (получили {status})")
        check("audit-probe" in body, "содержимое отчёта на странице")
        check("<h2" in body or "<h1" in body, "markdown отрисован, а не показан как текст")

        status, body = get(f"/sec/reports/{today}/raw")
        check(status == 200, "отчёт скачивается")
        check(body.startswith("# Отчёт безопасности"), "скачивается исходный markdown")

        # Главное: дата из адреса в путь к файлу не уезжает
        for bad in ["../secret", "..%2f..%2fsecret", "2026-09-12/../../secret",
                    "....//secret", "%2e%2e%2fsecret", "../../secret.txt"]:
            status, body = get(f"/sec/reports/{bad}")
            check(status in (404, 400) and "SECRET_KEY" not in body,
                  f"путь наружу «{bad}» ничего не отдал (код {status})")

        status, body = get("/sec/reports/2026-01-01")
        check(status == 404, "несуществующий отчёт даёт 404, а не пустую страницу")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        db.execute("DELETE FROM sessions WHERE id = %s", (session_id,))
        shutil.rmtree(work, ignore_errors=True)


def main() -> int:
    db.init_pool()
    print("Разбор и счёт:")
    check_pure()
    print("\nМолчание и тревога:")
    check_silence()
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
