"""Ночной аудит безопасности: состояние, отчёты, ручной прогон.

Приложение не ходит в `/opt/secaudit` и не вызывает `iptables`: доступа туда
у него нет и быть не должно. Единственная дверь к root — обёртка `webui-sec`
с закрытым набором команд (`infra/webui-sec.sh`), ей и только ей разрешён
беспарольный `sudo`. Здесь — вызов обёртки, чтение отчётов из каталога
состояния и запуск `audit.sh` от имени приложения (root ему не нужен).

Отчёт содержит имена учёток, адреса входов и отпечатки ключей. Поэтому дата
в адресе сверяется с образцом ДО обращения к диску: без этого
`/sec/reports/../../.config/webui/webui.env` отдал бы через панель `SECRET_KEY`.
"""
from __future__ import annotations

import os
import re
import subprocess
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

SUDO = "/usr/bin/sudo"
WRAPPER = "webui-sec"

# Чем вызывается обёртка. Переопределяется только проверками из `tests/`:
# подставив заглушку, стенд показывает панель с вымышленным состоянием и не
# трогает работающий аудит. На безопасность не влияет — кто может задать
# окружение службы, тот и так распоряжается приложением.
CMD = os.environ.get("WEBUI_SEC_CMD", "").split() or [SUDO, "-n", WRAPPER]

LIB = Path(os.environ.get("WEBUI_SEC_LIB", "/opt/secaudit"))
STATE = Path(os.environ.get("WEBUI_SEC_STATE", "/var/lib/secaudit"))
REPORTS = STATE / "reports"

# Имя отчёта: rep_ГГГГ-ММ-ДД.md. Образец привязан к началу и концу — иначе
# «..» и слеш уехали бы в путь к файлу.
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Сколько часов без прогона считаем молчанием. Сутки плюс запас на то, что
# ночной запуск сдвинулся: молчащий аудит выглядит как тишина и опаснее находки.
SILENCE_HOURS = 26


class SecError(RuntimeError):
    """Обёртка отказала. Текст берётся из её вывода и показывается как есть."""


@dataclass
class Report:
    date: str
    path: Path
    size: int
    mtime: float
    findings: int = 0          # число строк «###» в машинной части

    @property
    def when(self) -> str:
        return datetime.fromtimestamp(self.mtime).strftime("%d.%m.%Y %H:%M")


@dataclass
class State:
    installed: bool = False
    baseline: str = ""         # когда принят эталон, пусто — не принят
    last_report: str = ""      # дата последнего отчёта
    last_report_at: float = 0.0
    fail2ban: str = ""
    v4_policy: str = ""
    v6_policy: str = ""
    firewall_applied: str = ""
    quarantine: int = 0
    findings: int = 0
    note: str = ""             # почему данных нет, если их нет
    reports: list[Report] = field(default_factory=list)

    @property
    def silent(self) -> bool:
        """Аудит не отрабатывал дольше срока. Отдельный признак: отсутствие
        отчёта — это не «всё спокойно», это «мы не знаем»."""
        if not self.last_report_at:
            return True
        age = datetime.now() - datetime.fromtimestamp(self.last_report_at)
        return age > timedelta(hours=SILENCE_HOURS)

    @property
    def alarm(self) -> bool:
        """Нужна ли красная точка на вкладке."""
        return bool(self.silent or self.findings or not self.baseline)

    @property
    def verdict(self) -> str:
        if not self.installed:
            return "не установлен"
        if self.silent:
            return "аудит не отрабатывал"
        if self.findings:
            return f"находок: {self.findings}"
        return "спокойно"


def _run(*args: str, timeout: int = 60) -> tuple[int, str, str]:
    try:
        done = subprocess.run(
            [*CMD, *args],
            capture_output=True, text=True, timeout=timeout, check=False,
        )
    except FileNotFoundError:
        return 127, "", "не найден sudo"
    except subprocess.TimeoutExpired:
        return 124, "", "обёртка не ответила вовремя"
    return done.returncode, done.stdout, done.stderr


def check_date(value: str) -> str:
    if not DATE_RE.match(value or ""):
        raise SecError("Дата отчёта задаётся как ГГГГ-ММ-ДД.")
    return value


def report_path(date: str) -> Path | None:
    """Путь к отчёту или None. Дата сверена с образцом, поэтому в путь
    не уедет ни «..», ни слеш."""
    check_date(date)
    path = REPORTS / f"rep_{date}.md"
    return path if path.is_file() else None


def count_findings(text: str) -> int:
    """Сколько находок в машинной части отчёта.

    Считаются строки «### », кроме справочных: «Справочно» — это не находка,
    а пояснение, и попав в счётчик оно зажигало бы тревогу на пустом месте.
    """
    n = 0
    for line in text.splitlines():
        if line.startswith("### ") and "Справочно" not in line:
            n += 1
    return n


def reports() -> list[Report]:
    """Отчёты, свежие сверху. Каталог может не существовать — это не ошибка,
    а «аудит ещё не отрабатывал»."""
    out: list[Report] = []
    if not REPORTS.is_dir():
        return out
    for path in REPORTS.glob("rep_*.md"):
        date = path.stem[4:]
        if not DATE_RE.match(date):
            continue
        try:
            info = path.stat()
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        out.append(
            Report(date=date, path=path, size=info.st_size,
                   mtime=info.st_mtime, findings=count_findings(text))
        )
    out.sort(key=lambda r: r.date, reverse=True)
    return out


def _parse_status(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    return values


def state() -> State:
    """Состояние аудита. Ошибки не поднимает: панель должна открыться и тогда,
    когда аудита нет, — и сказать, чего не хватает."""
    st = State()
    rc, out, err = _run("status")
    if rc != 0:
        st.note = (err or out).strip() or "обёртка webui-sec недоступна"
    else:
        st.installed = True
        values = _parse_status(out)
        baseline = values.get("baseline", "нет")
        st.baseline = "" if baseline == "нет" else baseline
        st.fail2ban = values.get("fail2ban", "")
        st.v4_policy = values.get("v4_policy", "")
        st.v6_policy = values.get("v6_policy", "")
        applied = values.get("firewall_applied", "нет")
        st.firewall_applied = "" if applied == "нет" else applied
        st.quarantine = int(values.get("quarantine", "0") or 0)

    st.reports = reports()
    if st.reports:
        st.last_report = st.reports[0].date
        st.last_report_at = st.reports[0].mtime
        st.findings = st.reports[0].findings
    return st


def report_text(date: str) -> str:
    path = report_path(date)
    if path is None:
        raise SecError(f"Отчёта за {date} нет.")
    return path.read_text(encoding="utf-8", errors="replace")


# ── Ручной прогон ────────────────────────────────────────────────────────
# Прогон долгий: `find / -perm -4000` плюс сбор фактов. Держать его в
# обработчике нельзя, поэтому запускается фоном, а страница опрашивает
# состояние. Отметка живёт в памяти процесса: переживать перезапуск ей незачем,
# после него прогон всё равно оборван вместе со службой — поэтому перезапуск из
# «Настроек» ждёт конца прогона (`services/restart.py`). Уход со страницы прогон
# не обрывает: он идёт на сервере, страница только опрашивает состояние.
_run_lock = threading.Lock()
_running: dict[str, object] = {"active": False, "started": 0.0, "mode": "", "tail": "", "error": ""}


def run_active() -> bool:
    with _run_lock:
        return bool(_running["active"])


def run_info() -> dict:
    with _run_lock:
        return dict(_running)


def start_run(remediate: bool = True) -> None:
    """Запустить аудит фоном. Второй запуск при работающем — отказ."""
    with _run_lock:
        if _running["active"]:
            raise SecError("Прогон уже идёт.")
        _running.update(
            active=True,
            started=datetime.now().timestamp(),
            mode="полный" if remediate else "без вмешательства",
            tail="",
            error="",
        )

    def worker() -> None:
        env = dict(os.environ)
        env["REMEDIATE"] = "1" if remediate else "0"
        try:
            done = subprocess.run(
                ["/bin/bash", str(LIB / "audit.sh")],
                capture_output=True, text=True, timeout=1800, check=False, env=env,
            )
            tail = (done.stdout or done.stderr or "").strip().splitlines()
            message, error = (tail[-1] if tail else "прогон завершён без вывода"), ""
        except subprocess.TimeoutExpired:
            message = error = "прогон не уложился в 30 минут и был прерван"
        except OSError as exc:
            message = error = f"не удалось запустить аудит: {exc}"
        with _run_lock:
            _running.update(active=False, tail=message, error=error)

    threading.Thread(target=worker, daemon=True, name="secaudit").start()


# ── Последний прогон ─────────────────────────────────────────────────────
# Итог берётся из журнала аудита, а не из отметки в памяти: журнал пишут все
# прогоны — и с панели, и ночной из cron, — и он переживает перезапуск службы.
# Без этого вернувшийся на страницу видел только погасшую надпись «Идёт прогон»
# и не мог отличить законченный прогон от оборванного.
AUDIT_LOG = STATE / "audit.log"
_LOG_LINE = re.compile(r"^\[([^\]]+)\]\s+(.*)$")
# Сколько ждать строки «готово», прежде чем назвать прогон оборванным.
# Столько же даёт прогону `start_run`.
RUN_LIMIT_SEC = 1800


@dataclass
class LastRun:
    started: float = 0.0
    finished: float = 0.0
    status: str = ""           # «идёт», «готово», «ошибка», «оборван»; пусто — прогонов не было
    message: str = ""
    report_date: str = ""      # дата отчёта, если прогон его записал

    @property
    def seconds(self) -> int:
        return int(self.finished - self.started) if self.finished else 0


def _read_log_tail(limit: int = 64 * 1024) -> list[str]:
    try:
        with AUDIT_LOG.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - limit))
            data = fh.read()
    except OSError:
        return []
    return data.decode("utf-8", errors="replace").splitlines()


def last_run(now: float | None = None, active: bool | None = None) -> LastRun:
    """Последний прогон по журналу аудита."""
    now = datetime.now().timestamp() if now is None else now
    active = run_active() if active is None else active
    run = LastRun()
    for line in _read_log_tail():
        m = _LOG_LINE.match(line)
        if not m:
            continue
        try:
            at = datetime.fromisoformat(m.group(1)).timestamp()
        except ValueError:
            continue
        text = m.group(2).strip()
        if text == "=== запуск аудита ===":
            run = LastRun(started=at, status="идёт")
        elif not run.started:
            continue
        elif text.startswith("готово:"):
            run.finished, run.status = at, "готово"
            name = Path(text.partition(":")[2].strip()).name
            date = name[4:-3] if name.startswith("rep_") and name.endswith(".md") else ""
            run.report_date = date if DATE_RE.match(date) else ""
        elif text.startswith("ОШИБКА"):
            # Ошибка сбора не обрывает аудит: отчёт всё равно пишется, но
            # недостоверный — это и надо показать, даже если «готово» придёт.
            run.message = text
    if run.status == "готово" and run.message:
        run.status = "ошибка"
    # Сбой, которого журнал не видит: аудит не запустился или был убит по
    # сроку. Отметка в памяти свежее последнего запуска в журнале — верим ей.
    info = run_info()
    if not active and info["error"] and float(info["started"]) >= run.started - 1:
        run = LastRun(started=float(info["started"]), status="ошибка", message=str(info["error"]))
    if run.status == "идёт" and not active and now - run.started > RUN_LIMIT_SEC:
        run.status = "оборван"
        run.message = "строки о завершении в журнале нет — прогон не дошёл до конца"
    return run


def approve_baseline() -> str:
    rc, out, err = _run("baseline-approve", timeout=120)
    if rc != 0:
        raise SecError((err or out).strip() or "не удалось принять эталон")
    return out.strip()
