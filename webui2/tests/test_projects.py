"""Проверки проектов и тем на временной базе с подставным Claude."""
import json
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path

import pytest

from common import CLAUDE_LOG, TMP, client, db, inside  # noqa: F401
from test_chat import csrf_of, send, wait_idle

from app import config, projects


@pytest.fixture(autouse=True)
def clean_folder():
    shutil.rmtree(TMP / "projects", ignore_errors=True)
    yield


def new_project(c, name: str) -> int:
    r = c.post("/projects/new", data={"name": name, "csrf": csrf_of(c)}, follow_redirects=False)
    assert r.status_code == 303, r.text
    return int(r.headers["location"].rstrip("/").rsplit("/", 1)[1])


def new_topic(c, pid: int) -> int:
    r = c.post(f"/projects/{pid}/topic/new", data={"csrf": csrf_of(c)}, follow_redirects=False)
    assert r.status_code == 303
    assert f"/projects/{pid}/t/" in r.headers["location"]
    return int(r.headers["location"].rsplit("/", 1)[1])


def last_launch() -> dict:
    return json.loads(CLAUDE_LOG.read_text(encoding="utf-8").splitlines()[-1])


def test_projects_closed_without_login(client):
    for path in ("/projects", "/projects/1", "/projects/1/t/1", "/projects/1/delete"):
        r = client.get(path, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"].endswith("/login"), path


def test_new_project_folder(inside):
    assert "Проектов пока нет" in inside.get("/projects").text
    pid = new_project(inside, "Мой  сайт про Щуку")
    proj = db.one("SELECT * FROM projects WHERE id = ?", (pid,))
    path = Path(proj["path"])
    assert proj["name"] == "Мой сайт про Щуку"
    assert path == TMP / "projects" / "moy-sayt-pro-schuku"
    assert (path / ".git").is_dir() and (path / "downloads").is_dir()
    assert "downloads/" in (path / ".gitignore").read_text() and ".env" in (path / ".gitignore").read_text()
    assert "Только по-русски" in (path / "CLAUDE.md").read_text()
    log = subprocess.run(["git", "-C", str(path), "log", "--format=%an|%s"], capture_output=True, text=True)
    assert log.stdout.strip().startswith(projects._git_identity()[0] + "|Новый проект")
    # Тот же адрес папки занят — к имени добавляется номер
    again = new_project(inside, "мой сайт про щуку")
    assert db.one("SELECT slug FROM projects WHERE id = ?", (again,))["slug"] == "moy-sayt-pro-schuku-2"
    assert db.one("SELECT slug FROM projects WHERE id = ?", (new_project(inside, "!!!"),))["slug"] == "project"
    page = inside.get("/projects").text
    assert "Мой сайт про Щуку" in page and "moy-sayt-pro-schuku-2" in page


def test_new_project_needs_name_and_token(inside):
    r = inside.post("/projects/new", data={"name": "   ", "csrf": csrf_of(inside)})
    assert "Напиши название проекта" in r.text
    inside.post("/projects/new", data={"name": "Чужой", "csrf": "подделка"})
    assert db.one("SELECT COUNT(*) AS n FROM projects")["n"] == 0


def test_topic_runs_in_project_folder(inside):
    pid = new_project(inside, "Кот")
    path = db.one("SELECT path FROM projects WHERE id = ?", (pid,))["path"]
    empty = inside.get(f"/projects/{pid}").text
    assert "Тем пока нет" in empty and "Новая тема" in empty
    topic = new_topic(inside, pid)
    assert db.one("SELECT model FROM conversations WHERE id = ?", (topic,))["model"] == "opus"
    send(inside, topic, "создай файл")
    rows = wait_idle(inside, topic)
    assert rows[-1]["role"] == "assistant" and "Сейчас гляну" not in rows[-1]["text"]
    launch = last_launch()
    assert launch["cwd"] == path
    assert (Path(path) / "made-by-claude.txt").is_file()
    argv = launch["argv"]
    assert "--tools" not in argv and "--setting-sources" not in argv and "--system-prompt" not in argv
    assert argv[argv.index("--permission-mode") + 1] == "acceptEdits"
    assert argv[argv.index("--permission-prompt-tool") + 1] == "stdio"
    banned = argv[argv.index("--disallowed-tools") + 1:]
    assert "Bash" not in banned and "AskUserQuestion" in banned
    assert "--allowed-tools" not in argv
    assert f"Read(/{config.DB_PATH.parent}/**)" in banned
    assert not any(k.startswith("WEBUI2_") for k in launch["env"])
    # Тема не видна в чате, а её адрес в чате ведёт в проект
    assert f"/projects/{pid}/t/{topic}" not in inside.get("/chat").text
    r = inside.get(f"/chat/{topic}", follow_redirects=False)
    assert r.headers["location"].endswith(f"/projects/{pid}/t/{topic}")
    page = inside.get(f"/projects/{pid}").text
    assert "создай файл" in page and "Запускать команды" in page


def test_status_line_in_stream(inside):
    pid = new_project(inside, "Статус")
    topic = new_topic(inside, pid)
    send(inside, topic, "медленно глянь")
    seen = []
    with inside.stream("GET", f"/chat/{topic}/stream") as r:
        for line in r.iter_lines():
            if line.startswith("data: "):
                ev = json.loads(line[6:])
                seen.append(ev)
                if ev["t"] == "done":
                    break
    statuses = [ev["x"] for ev in seen if ev["t"] == "status"] + [ev.get("s") for ev in seen if ev["t"] == "snapshot"]
    assert "Читаю CLAUDE.md…" in statuses
    assert any(ev["t"] == "start" for ev in seen)
    rows = wait_idle(inside, topic)
    assert rows[-1]["text"].startswith("**Ответ:** медленно глянь")


def test_access_checkboxes(inside):
    pid = new_project(inside, "Доступ")
    topic = new_topic(inside, pid)
    inside.post(f"/projects/{pid}/access", data={"commands": "1", "csrf": "подделка"})
    assert db.one("SELECT allow_commands FROM projects WHERE id = ?", (pid,))["allow_commands"] == 0
    inside.post(f"/projects/{pid}/access", data={"commands": "1", "back": str(topic), "csrf": csrf_of(inside)})
    send(inside, topic, "привет")
    wait_idle(inside, topic)
    argv = last_launch()["argv"]
    allowed = argv[argv.index("--allowed-tools") + 1:argv.index("--disallowed-tools")]
    assert allowed == ["Bash", "BashOutput", "KillShell"]
    assert f"Bash(*{config.ENV_FILE.name}*)" in argv
    inside.post(f"/projects/{pid}/access", data={"full": "1", "csrf": csrf_of(inside)})
    proj = db.one("SELECT allow_commands, full_access FROM projects WHERE id = ?", (pid,))
    assert proj == {"allow_commands": 1, "full_access": 1}
    send(inside, topic, "ещё")
    wait_idle(inside, topic)
    argv = last_launch()["argv"]
    assert argv[argv.index("--permission-mode") + 1] == "bypassPermissions"
    assert "Read(/" + str(config.ENV_FILE.parent) + "/**)" in argv
    inside.post(f"/projects/{pid}/access", data={"csrf": csrf_of(inside)})
    assert db.one("SELECT full_access FROM projects WHERE id = ?", (pid,))["full_access"] == 0


def test_search_finds_topics(inside):
    pid = new_project(inside, "Сад")
    topic = new_topic(inside, pid)
    send(inside, topic, "Посадить ёлку")
    wait_idle(inside, topic)
    page = inside.get("/search", params={"q": "ЕЛКУ"}).text
    assert f"/projects/{pid}/t/{topic}?n=10000" in page and "проект «Сад»" in page


def test_topic_rename_and_delete(inside):
    pid = new_project(inside, "Темы")
    topic = new_topic(inside, pid)
    r = inside.post(f"/chat/{topic}/rename", data={"title": "Про сад", "csrf": csrf_of(inside)},
                    follow_redirects=False)
    assert r.headers["location"].endswith(f"/projects/{pid}/t/{topic}")
    r = inside.post(f"/chat/{topic}/delete", data={"csrf": csrf_of(inside)}, follow_redirects=False)
    assert r.headers["location"].endswith(f"/projects/{pid}")
    assert db.one("SELECT id FROM conversations WHERE id = ?", (topic,)) is None


def wait_state(pid: int, states: tuple, timeout: float = 15):
    end = time.time() + timeout
    while time.time() < end:
        row = db.one("SELECT delete_state FROM projects WHERE id = ?", (pid,))
        if row is None or row["delete_state"] in states:
            return row
        time.sleep(0.1)
    raise AssertionError("не дождался")


def test_project_delete_after_yes(inside):
    pid = new_project(inside, "На удаление")
    path = Path(db.one("SELECT path FROM projects WHERE id = ?", (pid,))["path"])
    topic = new_topic(inside, pid)
    send(inside, topic, "привет")
    wait_idle(inside, topic)
    inside.post(f"/projects/{pid}/delete", data={"csrf": "подделка"})
    assert db.one("SELECT delete_state FROM projects WHERE id = ?", (pid,))["delete_state"] == ""
    inside.post(f"/projects/{pid}/delete", data={"csrf": csrf_of(inside)})
    wait_state(pid, ("ready",))
    page = inside.get(f"/projects/{pid}/delete").text
    assert "fake-test.service" in page and "Да, удалить" in page
    assert path.is_dir()
    # Пока ждёт «да», тема ведёт на страницу удаления
    assert inside.get(f"/projects/{pid}/t/{topic}", follow_redirects=False).headers["location"].endswith("/delete")
    # «Отмена» — всё как было
    inside.post(f"/projects/{pid}/delete/no", data={"csrf": csrf_of(inside)})
    assert db.one("SELECT delete_state FROM projects WHERE id = ?", (pid,))["delete_state"] == ""
    inside.post(f"/projects/{pid}/delete", data={"csrf": csrf_of(inside)})
    wait_state(pid, ("ready",))
    inside.post(f"/projects/{pid}/delete/yes", data={"csrf": csrf_of(inside)})
    assert wait_state(pid, ()) is None
    assert not path.exists()
    assert db.one("SELECT id FROM conversations WHERE id = ?", (topic,)) is None
    assert inside.get(f"/projects/{pid}/delete", follow_redirects=False).headers["location"].endswith("/projects")
    remove_run = last_launch()["argv"]
    assert remove_run[remove_run.index("--permission-mode") + 1] == "bypassPermissions"


def test_project_with_nothing_outside(inside):
    pid = new_project(inside, "ничего вне")
    inside.post(f"/projects/{pid}/delete", data={"csrf": csrf_of(inside)})
    wait_state(pid, ("ready",))
    launches = len(CLAUDE_LOG.read_text().splitlines())
    inside.post(f"/projects/{pid}/delete/yes", data={"csrf": csrf_of(inside)})
    assert wait_state(pid, ()) is None
    assert len(CLAUDE_LOG.read_text().splitlines()) == launches   # убирать нечего — без второго запуска


def test_site_folder_cannot_be_removed(inside, tmp_path):
    assert not projects.removable(str(config.PROJECT_DIR))
    assert not projects.removable(str(config.PROJECT_DIR.parent))
    assert not projects.removable(str(config.PROJECTS_DIR))
    assert not projects.removable(str(Path.home()))
    assert not projects.removable(str(tmp_path))
    config.PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    link = config.PROJECTS_DIR / "link"
    link.symlink_to(config.PROJECT_DIR)
    assert not projects.removable(str(link))
    assert projects.removable(str(config.PROJECTS_DIR / "x"))
    # Проект, чья папка вдруг указывает на сайт: удаление отказывает, папка цела
    stamp = db.now()
    pid = db.insert("INSERT INTO projects (name, slug, path, delete_state, delete_report, created_at, "
                    "updated_at) VALUES ('сайт', 'site', ?, 'ready', 'Вне папки проекта ничего нет', ?, ?)",
                    (str(config.PROJECT_DIR), stamp, stamp))
    inside.post(f"/projects/{pid}/delete/yes", data={"csrf": csrf_of(inside)})
    row = wait_state(pid, ("unclear",))
    assert row["delete_state"] == "unclear"
    assert (config.PROJECT_DIR / "app").is_dir()


def test_old_base_gets_project_column(tmp_path, monkeypatch):
    old = tmp_path / "old.db"
    con = sqlite3.connect(old)
    con.executescript("CREATE TABLE conversations (id INTEGER PRIMARY KEY, title TEXT NOT NULL DEFAULT '', "
                      "model TEXT NOT NULL DEFAULT 'sonnet', session_id TEXT, context_tokens INTEGER NOT NULL "
                      "DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);"
                      "INSERT INTO conversations (created_at, updated_at) VALUES ('x', 'x');")
    con.close()
    monkeypatch.setattr(config, "DB_PATH", old)
    db.init()
    db.init()
    assert db.one("SELECT project_id FROM conversations") == {"project_id": None}


def test_project_rename_keeps_folder(inside):
    pid = new_project(inside, "Сад")
    before = db.one("SELECT slug, path FROM projects WHERE id = ?", (pid,))
    topic = new_topic(inside, pid)
    inside.post(f"/projects/{pid}/rename", data={"name": "Чужое", "csrf": "подделка"})
    assert db.one("SELECT name FROM projects WHERE id = ?", (pid,))["name"] == "Сад"
    inside.post(f"/projects/{pid}/rename", data={"name": "   ", "csrf": csrf_of(inside)})
    assert db.one("SELECT name FROM projects WHERE id = ?", (pid,))["name"] == "Сад"
    r = inside.post(f"/projects/{pid}/rename", data={"name": "  Огород   у дома ", "csrf": csrf_of(inside),
                                                     "back": str(topic)}, follow_redirects=False)
    assert r.headers["location"].endswith(f"/projects/{pid}/t/{topic}")
    after = db.one("SELECT name, slug, path FROM projects WHERE id = ?", (pid,))
    assert after["name"] == "Огород у дома" and after["slug"] == before["slug"] and after["path"] == before["path"]
    assert "Огород у дома" in inside.get("/projects").text
    assert 'id="proj-rename-btn"' in inside.get(f"/projects/{pid}/t/{topic}").text
