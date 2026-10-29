"""Безопасность: ночная проверка сервера — сводка, отчёты, проверка по кнопке,
«так и должно быть».

Саму проверку завёл старый сайт: каждую ночь `audit.sh` снимает состояние
сервера (через обёртку webui-sec), сверяет с эталоном и пишет отчёт в
SEC_STATE/reports. Сайт эти отчёты читает и разбирает для сводки; по кнопке
запускает тот же audit.sh без исправлений (REMEDIATE=0); «так и должно быть» —
снимок дня становится эталоном (`webui-sec baseline-approve`)."""
import asyncio
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse
from markupsafe import Markup, escape

from . import claude, config, markup
from .web import csrf_ok, current, guarded, local_time, templates

router = APIRouter()

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Разделы снимка — по-русски
TOPICS = {"LISTEN": "Что слушает сеть", "USERS": "Пользователи", "PASSWD": "Пароли пользователей",
          "SUDO": "Права администратора", "SSHKEYS": "Ключи для входа", "SSHCONF": "Настройки входа",
          "CRON": "Задания по расписанию", "SYSTEMD": "Службы", "SUID": "Программы с особыми правами",
          "LOGIN_SRC": "Откуда входили", "FIREWALL": "Защитная стена", "HOST": "Сервер",
          "PROCS": "Процессы", "UPDATES": "Обновления", "DOCKER": "Контейнеры",
          "ETC_CHANGED": "Изменённые настройки системы", "WORLDWRITABLE": "Файлы, открытые всем на запись",
          "MINER_IOC": "Признаки майнеров", "AUTHFAIL": "Попытки входа"}

# Известные порты — словами
PORTS = {"tcp 22": "вход на сервер (SSH)", "tcp 80": "сайты (http)", "tcp 443": "сайты (https)",
         "tcp 25": "почта: приём", "tcp 587": "почта: отправка", "tcp 993": "почта: ящик (IMAP)",
         "udp 51820": "VPN"}
# Без имени программы слушает само ядро системы — так выглядят VPN
KERNEL = "служба системы без имени программы — так выглядит VPN"

STATE: dict = {"what": None, "error": "", "since": 0.0}
_task: dict = {"t": None}


# ── Чтение отчётов ───────────────────────────────────────────────────────

def _reports_dir() -> Path:
    return config.SEC_STATE / "reports"


def report_dates() -> list[str]:
    try:
        names = [p.name for p in _reports_dir().glob("rep_*.md")]
    except OSError:
        return []
    return sorted((n[4:-3] for n in names if DATE_RE.match(n[4:-3])), reverse=True)


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _mtime_iso(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
    except OSError:
        return datetime.now(timezone.utc).isoformat()


def day_label(date: str) -> str:
    y, m, d = date.split("-")
    return f"{d}.{m}.{y}"


def parse_report(text: str) -> dict:
    """Части отчёта: что исправлено само, расхождения с эталоном (их можно
    принять нормой), тревоги и справки."""
    def part(title: str) -> str:
        m = re.search(rf"^## {re.escape(title)}\n(.*?)(?=^## |\Z)", text, re.S | re.M)
        return m.group(1).strip() if m else ""

    fixed = part("Устранено автоматически")
    block = part("Расхождения с эталоном (машинная проверка)")
    block = re.sub(r"^```\n?|```.*$", "", block, flags=re.S | re.M).strip()
    changes, alerts, notes = [], [], []
    for chunk in re.split(r"^### ", block, flags=re.M)[1:]:
        title, _, body = chunk.partition("\n")
        lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
        if title.startswith("Расхождение с эталоном: "):
            key = title.split(": ", 1)[1].strip()
            items = []
            for ln in lines:
                kind, _, what = ln.partition(":")
                items.append({"added": kind.strip() == "ПОЯВИЛОСЬ", "text": what.strip() or ln})
            changes.append({"key": key, "title": TOPICS.get(key, key), "rows": items})
        elif title.startswith("Справочно") or title.startswith("Слушают наружу"):
            notes.append({"title": title.strip(), "lines": lines})
        else:
            alerts.append({"title": title.strip(), "lines": lines})
    no_reference = "Эталон отсутствует" in block
    nothing_fixed = not fixed or "не потребовалось" in fixed or "отключено" in fixed
    return {"fixed": "" if nothing_fixed else fixed, "changes": changes, "alerts": alerts,
            "notes": notes, "no_reference": no_reference,
            "count": sum(len(c["rows"]) for c in changes) + len(alerts)}


def parse_snapshot(text: str) -> dict[str, list[str]]:
    parts: dict[str, list[str]] = {}
    key = None
    for line in text.splitlines():
        if line.startswith("##") and not line.startswith("###"):
            key = line[2:].strip()
            parts[key] = []
        elif key and line.strip():
            parts[key].append(line.rstrip())
    return parts


def _outside(listen: list[str]) -> list[dict]:
    """Что принимает подключения извне: всё, что слушает не только сам сервер."""
    seen: dict[str, dict] = {}
    for line in listen:
        m = re.match(r"^(tcp|udp)\s+(\S+):(\d+)\s*(.*)$", line)
        if not m:
            continue
        proto, addr, port, progs = m.groups()
        if addr.startswith("127.") or addr in ("[::1]", "::1") or addr.startswith("[fe80"):
            continue
        item = seen.setdefault(f"{proto} {port}", {"port": port, "how": proto, "progs": set()})
        item["progs"].update(re.findall(r'"([^"]+)"', progs))
    out = []
    for key, item in sorted(seen.items(), key=lambda kv: (int(kv[1]["port"]), kv[1]["how"])):
        what = PORTS.get(key) or ("" if item["progs"] else KERNEL)
        out.append({"port": item["port"], "what": what or "неизвестно что", "known": bool(what),
                    "how": item["how"], "progs": ", ".join(sorted(item["progs"]))})
    return out


def _value(lines: list[str], key: str) -> str:
    for line in lines:
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip()
    return ""


def _logins(snap: dict[str, list[str]]) -> dict:
    users = [ln.split()[0] for ln in snap.get("USERS", [])
             if "shell=" in ln and not re.search(r"shell=\S*(nologin|false)$", ln) and not ln.startswith("--")]
    conf = {ln.split()[0]: ln.split()[-1] for ln in snap.get("SSHCONF", []) if " " in ln}
    keys = [ln for ln in snap.get("SSHKEYS", []) if "SHA256:" in ln]
    auth = snap.get("AUTHFAIL", [])
    ok_from = []
    for ln in auth:
        m = re.match(r"^\s*(\d+) for (\S+) from (\S+)", ln)
        if m:
            ok_from.append({"count": m.group(1), "user": m.group(2), "ip": m.group(3)})
    return {"users": users, "key_count": len(keys),
            "password": conf.get("passwordauthentication", "?") == "yes",
            "root": conf.get("permitrootlogin", "?") not in ("no", "?"),
            "failed": _value(auth, "failed_password_24h") or "0", "ok_from": ok_from}


def summary() -> dict | None:
    """Сводка последнего отчёта и его снимка."""
    dates = report_dates()
    if not dates:
        return None
    date = dates[0]
    path = _reports_dir() / f"rep_{date}.md"
    text = _read(path)
    if text is None:
        return None
    report = parse_report(text)
    snap = parse_snapshot(_read(config.SEC_STATE / "snapshots" / f"{date}.txt") or "")
    fw = snap.get("FIREWALL", [])
    upd = snap.get("UPDATES", [])
    banned = next((ln.split(":", 1)[1].strip() for ln in fw if ln.startswith("Currently banned")), "")
    age = time.time() - path.stat().st_mtime
    return {"date": date, "label": day_label(date), "at": _mtime_iso(path), **report,
            "stale": age > config.SEC_STALE_HOURS * 3600,
            # Принять нормой можно только сегодняшний снимок — тот, что она видит
            "approvable": date == time.strftime("%Y-%m-%d") and bool(report["changes"]),
            "has_snapshot": bool(snap),
            "outside": _outside(snap.get("LISTEN", [])),
            "wall": "DROP" in _value(fw, "v4_policy") and "DROP" in _value(fw, "v6_policy"),
            "guard": _value(fw, "fail2ban") == "active", "banned": banned,
            "logins": _logins(snap),
            "updates": {"security": _value(upd, "pending_security") or "0",
                        "total": _value(upd, "pending_total") or "0",
                        "reboot": _value(upd, "требуется_перезагрузка") == "да"}}


_alert_cache: dict = {"key": None, "value": 0}


def alert() -> int | str:
    """Для значка в шапке: число находок последнего отчёта, «!» — отчёта давно нет."""
    dates = report_dates()
    if not dates:
        return "!"
    path = _reports_dir() / f"rep_{dates[0]}.md"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return "!"
    if time.time() - mtime > config.SEC_STALE_HOURS * 3600:
        return "!"
    if _alert_cache["key"] != (path, mtime):
        text = _read(path) or ""
        _alert_cache.update(key=(path, mtime), value=parse_report(text)["count"])
    return _alert_cache["value"]


templates.env.globals["sec_alert"] = alert


def render_report(text: str, at_iso: str) -> Markup:
    """Отчёт на страницу: время — в её поясе; полный снимок — свёрнутым
    блоком (в самом отчёте он обёрнут в HTML, а HTML из файла не пропускается)."""
    head, _, tail = text.partition("<details>")
    head = re.sub(r"Аудит выполнен [^\n]*", f"Проверка — {local_time(at_iso)}.", head)
    snap = ""
    if tail:
        m = re.search(r"```\n?(.*?)```", tail, re.S)
        if m:
            snap = (f'<details class="snap"><summary>Полный снимок состояния</summary>'
                    f'<pre>{escape(m.group(1))}</pre></details>')
    return Markup(markup.render(head)) + Markup(snap)


# ── Проверка по кнопке и «так и должно быть» ────────────────────────────

def snapshot_state() -> dict:
    return {"what": STATE["what"], "error": STATE["error"], "last": report_dates()[:1]}


async def _exec(cmd: list[str], extra: dict | None = None) -> tuple[int, str]:
    env = claude.child_env()
    env.update({"LC_ALL": "C", **(extra or {})})
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.STDOUT, env=env)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=config.SEC_RUN_MIN * 60)
    except asyncio.TimeoutError:
        proc.kill()
        return 1, f"проверка не уложилась в {config.SEC_RUN_MIN} минут"
    return proc.returncode, out.decode("utf-8", "replace")


def _tail(out: str) -> str:
    return ((out.strip().splitlines() or ["без пояснений"])[-1])[:200]


async def _check() -> str:
    # Отчёт за сегодня перепишется; ночной (в нём то, что исправлено само)
    # сохраняется рядом один раз
    today = time.strftime("%Y-%m-%d")
    night, keep = _reports_dir() / f"rep_{today}.md", _reports_dir() / f"night_{today}.md"
    if night.is_file() and not keep.exists():
        try:
            keep.write_bytes(night.read_bytes())
        except OSError:
            pass
    # Без исправлений: по кнопке — только посмотреть
    code, out = await _exec(config.SEC_AUDIT, {"REMEDIATE": "0"})
    return "" if code == 0 else f"Проверка не прошла: {_tail(out)}"


def _today_snapshot() -> bool:
    # audit.sh называет снимок датой сервера — так же считаем «сегодня»
    return (config.SEC_STATE / "snapshots" / f"{time.strftime('%Y-%m-%d')}.txt").is_file()


async def _worker(what: str) -> None:
    error = ""
    try:
        if what == "approve":
            if not _today_snapshot():
                error = await _check()
            if not error:
                code, out = await _exec(config.SEC_APPROVE)
                if code != 0:
                    error = f"Не получилось принять: {_tail(out)}"
        if not error:
            error = await _check()                # отчёт заново — уже против новой нормы
    except OSError as exc:
        error = f"Не получилось: {exc}"
    finally:
        STATE.update(what=None, error=error)


def start(what: str) -> bool:
    if what not in ("check", "approve") or STATE["what"]:
        return False
    STATE.update(what=what, error="", since=time.monotonic())
    _task["t"] = asyncio.create_task(_worker(what))
    return True


# ── Адреса ───────────────────────────────────────────────────────────────

@router.get("/security", name="security")
def security_page(request: Request):
    return guarded(request, "security.html", "security",
                   {"title": "Безопасность", "s": summary(), "run": snapshot_state(),
                    "dates": report_dates(), "day_label": day_label, "topics": TOPICS})


@router.get("/security/report/{date}", name="security_report")
def security_report(request: Request, date: str):
    sess = current(request)
    if not sess or sess["locked"]:
        return guarded(request, "security_report.html", "security")
    if not DATE_RE.match(date):
        return RedirectResponse(request.url_for("security"), status_code=303)
    path = _reports_dir() / f"rep_{date}.md"
    text = _read(path)
    if text is None:
        return RedirectResponse(request.url_for("security"), status_code=303)
    return guarded(request, "security_report.html", "security",
                   {"title": f"Отчёт за {day_label(date)}", "label": day_label(date),
                    "html": render_report(text, _mtime_iso(path))})


@router.get("/security/state", name="security_state")
def security_state(request: Request):
    sess = current(request)
    if not sess or sess["locked"]:
        return JSONResponse({"error": "нет доступа"}, status_code=403)
    return JSONResponse(snapshot_state(), headers={"Cache-Control": "no-store"})


@router.post("/security/{what}", name="security_start")
async def security_start(request: Request, what: str, csrf: str = Form("")):
    sess = current(request)
    if not sess or sess["locked"] or not csrf_ok(request, sess, csrf):
        return JSONResponse({"error": "Нет доступа — обнови страницу"}, status_code=403)
    if what not in ("check", "approve"):
        return JSONResponse({"error": "нет такого действия"}, status_code=404)
    if not start(what):
        return JSONResponse({"error": "Проверка уже идёт", **snapshot_state()}, status_code=409)
    return JSONResponse(snapshot_state())
