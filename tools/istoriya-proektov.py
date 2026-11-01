#!/usr/bin/env python3
"""История проектов: по файлу .md на проект — задачи из журнала, просьбы и команды
из истории разговоров. Пароли и ключи заменяются метками ⟦К-0001⟧ и выносятся
в папку «ключи» (не в git); обратно их подставляет ключи/vstroit.py.

Берёт только журнал, заметки памяти и истории разговоров. Вывод команд и файлы
с секретами на сервере не читает: сюда попадает лишь то, что было в самих
командах и сообщениях.

Запуск: python3 tools/istoriya-proektov.py [папка-результата]
"""
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

MAIN = Path.home() / "main"
HISTORY = Path.home() / ".claude" / "projects"
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else MAIN / "exchange" / "istoriya-proektov"
LOGS = [MAIN / "log.md", MAIN / "log-arhiv-2026.md"]
MSK = timedelta(hours=3)

# Проекты из списка на сайте; прочие (архивные) в выдачу не идут.
# Свежего списка в файлах нет: это девять перенесённых 29.10.2026 (журнал, этап 8).
KEEP = {"sc-parashyuty", "glavpryg-sayt", "logotip", "griby", "3d", "letalki",
        "viza-italiya", "tunel", "novyy-proekt"}

TITLES = {
    "glavpryg-sayt": "Главпрыг: сайт", "glavpryg-dop": "Главпрыг: дополнительно",
    "sc-parashyuty": "SkyCenter: парашюты", "webui": "Веб-интерфейс, старый сайт",
    "webui2": "Новый сайт (v2)", "bezopasnost": "Безопасность", "3d": "3D-конструктор",
    "lodka": "Лодка и тримаран", "letalki": "Леталки", "viza-italiya": "Виза в Италию",
    "tatu": "Тату", "telegram-bot": "Телеграм-бот", "griby": "Грибы и календарь Aevit",
    "vpn": "VPN", "vpn-server": "VPN-сервер", "tunel": "Туннель",
    "kompyuter": "Компьютер", "logotip": "Логотип", "illyustrator": "Иллюстратор",
    "optimizaciya": "Оптимизация", "knigi": "Книги", "samolet": "Самолёт",
    "novyy-proekt": "Новый проект (новый сайт)", "infra": "Инфраструктура сервера", "tools": "Инструменты",
    "obshchee": "Общее: сервер, правила, прочее", "chat-sayta": "Чат сайта",
    "proby": "Пробные запуски и стенды",
}
# Журнал делится по заголовку записи: первое совпадение решает
LOG_RULES = [
    (r"главпрыг|игра «|точно в круг", "glavpryg-sayt"), (r"skycenter|скайцентр", "sc-parashyuty"),
    (r"сайт v2|новый сайт", "novyy-proekt"), (r"aevit|календар|гриб", "griby"),
    (r"безопасн|кнопка доступа|аудит", "bezopasnost"), (r"3d|конструктор", "3d"),
    (r"лодк|тримаран|судно|рейс", "lodka"), (r"леталк", "letalki"), (r"виза", "viza-italiya"),
    (r"тату", "tatu"), (r"телеграм", "telegram-bot"), (r"туннел", "tunel"),
    (r"vpn", "vpn"), (r"логотип", "logotip"),
    (r"webui|веб-интерфейс|вкладк|кружок|тем[аыу]\b|сжати|панел|интерфейс|скачиван", "webui"),
]

# --- Секреты -----------------------------------------------------------------
PATTERNS = [
    ("закрытый ключ", r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----"),
    ("ключ Anthropic", r"\bsk-ant-[A-Za-z0-9_\-]{20,}"),
    ("ключ API", r"\bsk-[A-Za-z0-9_\-]{32,}"),
    ("ключ GitHub", r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})"),
    ("ключ Google", r"\bAIza[0-9A-Za-z_\-]{35}"),
    ("ключ Яндекса", r"\by[0-3]_[A-Za-z0-9_\-]{30,}"),
    ("ключ Hugging Face", r"\bhf_[A-Za-z0-9]{30,}"),
    ("ключ Telegram-бота", r"\b\d{8,10}:AA[A-Za-z0-9_\-]{30,}"),
    ("ключ AWS", r"\bAKIA[0-9A-Z]{16}"),
    ("токен JWT", r"\beyJ[A-Za-z0-9_\-]{15,}\.[A-Za-z0-9_\-]{15,}\.[A-Za-z0-9_\-]{10,}"),
    ("ключ VPN", r"\bvless://[^\s\"'`<>]+"),
]
# Значение после слова-подсказки или внутри адреса/команды — группа val
CONTEXT = [
    ("пароль в адресе", r"://[^\s:/@\"']+:(?P<val>[^\s@/\"']{4,})@"),
    ("пароль в команде", r"\bsshpass\s+-p\s*['\"]?(?P<val>[^\s'\"]{4,})"),
    ("пароль базы", r"\b(?:mysql|mariadb|mysqldump)\b[^\n|;]*?\s-p(?P<val>[^\s'\"$-][^\s'\"]{3,})"),
    ("пароль в команде", r"\bcurl\b[^\n|;]*?\s(?:-u|--user)\s+['\"]?[^\s:'\"]+:(?P<val>[^\s'\"]{4,})"),
    ("пароль в проверке", r"(?i)name=[\"']?pass\w*[\"']?\]?[\"']?\s*,\s*[\"'](?P<val>[^\"'\s$]{6,})"),
    ("пароль", r"(?i)(?<![a-zа-я])(?:password|parol|пароль)\w*[\"']?\s*[:=,]\s*[\"'](?P<val>[^\"'\s$]{6,})[\"']"),
    ("пароль или ключ", r"(?i)(?<![a-zа-я])(?:пароль|парол[яеь]м?|password|passwd|pass|pwd|parol|secret|секрет"
                        r"|token|токен|api[_\- ]?key|apikey|private[_\- ]?key|preshared[_\- ]?key"
                        r"|client_secret|ключ)"
                        r"[\w\-]*[\"'`*]*\s*(?:[:=]|—|-|это|is)\s*[\"'`*]*(?P<val>[A-Za-z0-9!@#%^&_+=/.\-]{6,})"),
]
NOT_SECRET = re.compile(
    r"(?i)^(?:null|none|true|false|str|string|text|hidden|password\w*|secret\w*|token\w*|"
    r"required|optional|env|config|getenv|environ|bool|int|dict|example\w*|changeme|"
    r"xxx+|\*+|https?|file|path|name|value|hash\w*|bcrypt\w*|sha\d+\w*|length|input|"
    r"current-password|new-password|confirm\w*)$")


def looks_secret(val: str) -> bool:
    val = val.rstrip(".,;:)")
    if len(val) < 6 or NOT_SECRET.match(val):
        return False
    if val[0] in "$<{(#-" or val.isdigit() or val.startswith(("/", "~/", "./", "http")) or "..." in val:
        return False
    if re.search(r"\.(?:py|php|md|sh|pass|json|conf|txt|env|js|html|netrc|key|pem)$", val):
        return False
    if re.fullmatch(r"[a-z_]+(?:\.[a-z_]+)+", val):   # settings.password и подобное
        return False
    # Обычное слово — не пароль: нужна цифра или знак
    return bool(re.search(r"\d|[!@#%^&+=]", val))


class Vault:
    def __init__(self):
        self.ids = {}          # значение -> метка
        self.info = {}         # метка -> (вид, значение, проект, когда)

    def mark(self, val, kind, project, when):
        if val not in self.ids:
            tag = f"⟦К-{len(self.ids) + 1:04d}⟧"
            self.ids[val] = tag
            self.info[tag] = (kind, val, project, when)
        return self.ids[val]

    def scrub(self, text, project, when):
        for kind, rx in PATTERNS:
            text = re.sub(rx, lambda m: self.mark(m.group(0), kind, project, when), text, flags=re.S)
        for kind, rx in CONTEXT:
            def sub(m):
                val = m.group("val").rstrip(".,;:)")
                if "⟦" in val or not looks_secret(val):
                    return m.group(0)
                tag = self.mark(val, kind, project, when)
                return m.group(0).replace(val, tag, 1)
            text = re.sub(rx, sub, text)
        return text

    def finish(self, text):
        """Значение, найденное в одном месте, закрывается и во всех остальных."""
        for val in sorted(self.ids, key=len, reverse=True):
            if len(val) >= 8 and val in text:
                text = text.replace(val, self.ids[val])
        return text


# --- Истории разговоров ------------------------------------------------------
def folder_project(path: str) -> str:
    p = Path(path or "")
    if str(p).startswith("/tmp"):
        return "proby"
    if ".local/share/webui2" in str(p):
        return "chat-sayta"
    if str(p).startswith(str(Path.home() / "projects" / "lodka")):
        return "lodka"
    try:
        parts = p.relative_to(MAIN).parts
    except ValueError:
        return "obshchee"
    return parts[0] if parts and (MAIN / parts[0]).is_dir() and parts[0] != "exchange" else "obshchee"


def dir_project(name: str) -> str:
    if name.startswith("-tmp"):
        return "proby"
    if "local-share-webui2" in name:
        return "chat-sayta"
    if name.endswith("projects-lodka"):
        return "lodka"
    return name.removeprefix("-home-mokeeva-main-") if name != "-home-mokeeva-main" else "obshchee"


def clean_user(text: str) -> str:
    text = re.sub(r"<system-reminder>.*?</system-reminder>", "", text, flags=re.S)
    text = re.sub(r"<task-notification>.*?</task-notification>", "", text, flags=re.S)
    text = re.sub(r"</?(?:pasted_content|command-[a-z]+|local-command-[a-z]+)[^>]*>", "", text)
    return text.strip()


def stamp(ts: str):
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).replace(tzinfo=None) + MSK
    except (ValueError, AttributeError):
        return None


def read_session(path: Path, seen: set):
    """Шаги разговора по порядку: (когда, вид, текст)."""
    steps, cwds = [], Counter()
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if o.get("uuid") in seen or o.get("isMeta"):
                continue
            seen.add(o.get("uuid"))
            when, msg = stamp(o.get("timestamp")), o.get("message") or {}
            if o.get("cwd"):
                cwds[o["cwd"]] += 1
            content = msg.get("content")
            blocks = [{"type": "text", "text": content}] if isinstance(content, str) else content or []
            for b in blocks:
                if not isinstance(b, dict):
                    continue
                if o.get("type") == "user" and b.get("type") == "text":
                    text = clean_user(b.get("text", ""))
                    if text and not text.startswith(("[Request interrupted", "Caveat:")):
                        steps.append((when, "ask", text))
                elif o.get("type") == "assistant" and b.get("type") == "tool_use":
                    inp = b.get("input") or {}
                    if b.get("name") == "Bash" and inp.get("command"):
                        steps.append((when, "cmd", inp["command"]))
                    elif b.get("name") in ("Edit", "Write", "NotebookEdit"):
                        file = inp.get("file_path") or inp.get("notebook_path") or ""
                        steps.append((when, "file", file))
    return steps, cwds


def session_project(dirname, steps, cwds):
    project = dir_project(dirname)
    if project != "obshchee":
        return project
    # Общая папка: проект определяют пути, которых касались команды и правки
    votes = Counter()
    for _, kind, text in steps:
        if kind in ("cmd", "file"):
            for name in re.findall(r"(?:main/|^|\s)([a-z0-9\-]+)/", text):
                if name in TITLES and name != "obshchee":
                    votes[name] += 1
    top = votes.most_common(1)
    return top[0][0] if top and top[0][1] >= 3 else "obshchee"


# --- Журнал ------------------------------------------------------------------
def read_log():
    entries = defaultdict(list)
    for path in LOGS:
        chunks = re.split(r"(?m)^(?=## )", path.read_text(encoding="utf-8"))
        for chunk in chunks[1:]:
            head = chunk.splitlines()[0][3:].strip()
            project = next((p for rx, p in LOG_RULES if re.search(rx, head, re.I)), "obshchee")
            entries[project].append((head, chunk.split("\n", 1)[-1].strip().rstrip("-").strip()))
    return entries


def fence(text):
    return f"~~~~\n{text}\n~~~~"


def main():
    (OUT / "проекты").mkdir(parents=True, exist_ok=True)
    keys = OUT / "ключи"
    keys.mkdir(exist_ok=True)
    os.chmod(keys, 0o700)
    vault = Vault()

    sessions = defaultdict(list)
    seen = set()
    for pdir in sorted(p for p in HISTORY.iterdir() if p.is_dir()):
        for path in sorted(pdir.rglob("*.jsonl")):
            steps, cwds = read_session(path, seen)
            if steps:
                project = session_project(pdir.name, steps, cwds)
                sessions[project].append((steps[0][0] or datetime.min, path, steps))

    log = read_log()
    totals = {}
    for old in (OUT / "проекты").glob("*.md"):
        old.unlink()
    for project in sorted(KEEP):
        lines = [f"# {TITLES.get(project, project)}", "",
                 f"Папка проекта: `{project}`. Время — московское. Пароли и ключи заменены "
                 "метками вида ⟦К-номер⟧, значения — в папке «ключи».", ""]
        lines += ["## Задачи из журнала", ""]
        for head, body in log.get(project, []):
            when = re.match(r"\d{2}\.\d{2}\.\d{4}", head)
            lines += [f"### {head}", "", vault.scrub(body, project, when.group(0) if when else ""), ""]
        if not log.get(project):
            lines += ["В журнале записей нет.", ""]
        lines += ["## Разговоры и команды", ""]
        asks = cmds = 0
        for start, path, steps in sorted(sessions.get(project, []), key=lambda s: s[0]):
            tag = " (помощник)" if "subagents" in str(path) else ""
            lines += [f"### Разговор {start:%d.%m.%Y %H:%M}{tag}", ""]
            files = []
            for when, kind, text in steps:
                label = f"{when:%d.%m %H:%M}" if when else ""
                date = f"{when:%d.%m.%Y}" if when else ""
                if kind == "file":
                    files.append(text)
                    continue
                if files:
                    lines += ["Правил файлы: " + ", ".join(f"`{f}`" for f in dict.fromkeys(files)), ""]
                    files = []
                text = vault.scrub(text, project, date)
                if kind == "ask":
                    asks += 1
                    lines += [f"**Задача, {label}:**", "", "> " + text.replace("\n", "\n> "), ""]
                else:
                    cmds += 1
                    lines += [fence(text), ""]
            if files:
                lines += ["Правил файлы: " + ", ".join(f"`{f}`" for f in dict.fromkeys(files)), ""]
        if not sessions.get(project):
            lines += ["Сохранившейся истории разговоров нет.", ""]
        totals[project] = (len(log.get(project, [])), asks, cmds, "\n".join(lines))

    # Второй проход нужен, когда собраны все значения
    memory = sorted((HISTORY / "-home-mokeeva-main" / "memory").glob("*.md"))
    mem_text = ["# Память", ""] + [f"## {m.name}\n\n{m.read_text(encoding='utf-8')}\n" for m in memory]
    (OUT / "pamyat.md").write_text(vault.finish("\n".join(mem_text)), encoding="utf-8")
    for project, (_, _, _, text) in totals.items():
        (OUT / "проекты" / f"{project}.md").write_text(vault.finish(text), encoding="utf-8")

    by_project = defaultdict(list)
    for tag, (kind, val, project, when) in vault.info.items():
        by_project[project].append((tag, kind, val, when))
    for old in keys.glob("*.md"):
        old.unlink()
    for project, rows in by_project.items():
        out = [f"# Ключи: {TITLES.get(project, project)}", ""]
        for tag, kind, val, when in rows:
            out += [f"## {tag}", "", f"Что это: {kind}. Встретилось: {when}.", "", fence(val), ""]
        path = keys / f"{project}.md"
        path.write_text("\n".join(out), encoding="utf-8")
        os.chmod(path, 0o600)

    index = ["# История проектов", "", "| Проект | Файл | Задач в журнале | Просьб | Команд |", "|---|---|---|---|---|"]
    for project, (entries, asks, cmds, _) in sorted(totals.items(), key=lambda t: -t[1][2]):
        index.append(f"| {TITLES.get(project, project)} | `проекты/{project}.md` | {entries} | {asks} | {cmds} |")
    index += ["", f"Найдено паролей и ключей: {len(vault.info)}, они в папке «ключи», по файлу на проект.",
              "Метки вида ⟦К-номер⟧ в файлах проектов — это места, куда они встают.", "",
              "Чтобы встроить ключи: `python3 ключи/vstroit.py`. Появится папка `со-ключами` "
              "с теми же файлами, но с настоящими значениями. Отправлять её никому нельзя.", ""]
    (OUT / "README.md").write_text("\n".join(index), encoding="utf-8")
    print(len(totals), "проектов,", len(vault.info), "ключей,", sum(t[2] for t in totals.values()), "команд")


if __name__ == "__main__":
    main()
