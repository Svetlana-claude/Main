"""Перенос проектов со старого сайта (раздел 9 ТЗ).

Запускается питоном старого сайта (там есть драйвер его базы):
    webui/.venv/bin/python webui2/tools/import_old.py 57 60 77 ...
Числа — номера проектов в базе старого сайта.

Что делает:
1. Копия данных старого сайта (вся база) и копия базы нового — в
   ~/.local/share/webui2/backup/, права только для владельца.
2. Каждый проект подключается к своей прежней папке (ничего не копируется
   и не переименовывается), темы переносятся целиком: название, модель,
   продолжение беседы Claude (session_id), все сообщения со временем.
Старый сайт только читается.

Повторный запуск дописывает то, что появилось на старом сайте с прошлого
раза. Тему, в которую уже писали на новом сайте, он не трогает — иначе
сообщения двух сайтов перемешаются.
"""
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from dotenv import dotenv_values
from psycopg.conninfo import conninfo_to_dict

OLD_ENV = Path.home() / ".config/webui/webui.env"
DATA = Path(os.environ.get("WEBUI2_DATA", Path.home() / ".local/share/webui2"))
NEW_DB = DATA / "site.db"
BACKUP = DATA / "backup"
TOPIC_MODEL = "opus"

IMPORTED = """CREATE TABLE IF NOT EXISTS imported (
    kind     TEXT NOT NULL,      -- project | conv
    old_id   INTEGER NOT NULL,
    new_id   INTEGER NOT NULL,
    old_last INTEGER NOT NULL DEFAULT 0,   -- последнее перенесённое сообщение старого сайта
    new_last INTEGER NOT NULL DEFAULT 0,   -- и его номер на новом
    PRIMARY KEY (kind, old_id)
)"""


def norm(text: str) -> str:
    return text.lower().replace("ё", "е")


def iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).isoformat()


def model_of(name: str | None) -> str:
    for key in ("opus", "sonnet", "haiku"):
        if name and key in name:
            return key
    return TOPIC_MODEL


def backup(url: str) -> list[Path]:
    """Полная копия базы старого сайта и копия базы нового."""
    os.umask(0o077)
    BACKUP.mkdir(mode=0o700, parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    old = BACKUP / f"old-site-{stamp}.sql"
    # Пароль — через окружение, а не в строке запуска (её видно в списке процессов)
    info = conninfo_to_dict(url)
    env = dict(os.environ)
    for key, var in (("host", "PGHOST"), ("port", "PGPORT"), ("user", "PGUSER"),
                     ("password", "PGPASSWORD"), ("dbname", "PGDATABASE")):
        if info.get(key):
            env[var] = str(info[key])
    with open(old, "wb") as out:
        subprocess.run(["pg_dump", "--no-owner"], stdout=out, env=env, check=True)
    new = BACKUP / f"new-site-before-import-{stamp}.db"
    src, dst = sqlite3.connect(NEW_DB), sqlite3.connect(new)
    with dst:
        src.backup(dst)
    src.close()
    dst.close()
    for p in (old, new):
        p.chmod(0o600)
    return [old, new]


def free_slug(con: sqlite3.Connection, base: str) -> str:
    slug, n = base, 2
    while con.execute("SELECT 1 FROM projects WHERE slug = ?", (slug,)).fetchone():
        slug, n = f"{base}-{n}", n + 1
    return slug


def link(con, kind: str, old_id: int):
    return con.execute("SELECT * FROM imported WHERE kind = ? AND old_id = ?", (kind, old_id)).fetchone()


def import_project(old, con, pid: int) -> str:
    p = old.execute("SELECT id, name, workdir, allow_bash, created_at FROM projects WHERE id = %s",
                    (pid,)).fetchone()
    if not p:
        return f"{pid}: нет такого проекта"
    _, name, workdir, allow_bash, created = p
    known = link(con, "project", pid)
    if known and con.execute("SELECT 1 FROM projects WHERE id = ?", (known["new_id"],)).fetchone():
        new_pid = known["new_id"]
    else:
        same = con.execute("SELECT id FROM projects WHERE path = ?", (workdir,)).fetchone()
        if same:
            new_pid = same["id"]
        else:
            stamp = iso(created)
            new_pid = con.execute(
                "INSERT INTO projects (name, slug, path, allow_commands, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (name, free_slug(con, Path(workdir).name), workdir, int(bool(allow_bash)), stamp, stamp)).lastrowid
        con.execute("INSERT OR REPLACE INTO imported (kind, old_id, new_id) VALUES ('project', ?, ?)",
                    (pid, new_pid))

    added = skipped = 0
    convs = old.execute("SELECT id, title, claude_session_id, created_at, updated_at FROM conversations "
                        "WHERE project_id = %s ORDER BY id", (pid,)).fetchall()
    for cid, title, session, c_created, c_updated in convs:
        last_model = old.execute("SELECT model FROM messages WHERE conversation_id = %s AND model IS NOT NULL "
                                 "ORDER BY id DESC LIMIT 1", (cid,)).fetchone()
        known = link(con, "conv", cid)
        if known and not con.execute("SELECT 1 FROM conversations WHERE id = ?", (known["new_id"],)).fetchone():
            known = None    # тему на новом сайте удалили — переносим заново
        if known:
            newest = con.execute("SELECT COALESCE(MAX(id), 0) FROM messages WHERE conv_id = ?",
                                 (known["new_id"],)).fetchone()[0]
            if newest != known["new_last"]:
                skipped += 1    # на новом сайте уже писали — не смешиваем
                continue
            new_cid, after = known["new_id"], known["old_last"]
        else:
            new_cid = con.execute(
                "INSERT INTO conversations (title, model, session_id, created_at, updated_at, project_id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (title or "", model_of(last_model and last_model[0]), session, iso(c_created),
                 iso(c_updated), new_pid)).lastrowid
            after = 0
        old_last, new_last = after, known["new_last"] if known else 0
        for mid, role, text, m_created in old.execute(
                "SELECT id, role, content, created_at FROM messages WHERE conversation_id = %s AND id > %s "
                "ORDER BY id", (cid, after)):
            new_last = con.execute("INSERT INTO messages (conv_id, role, text, norm, created_at) "
                                   "VALUES (?, ?, ?, ?, ?)",
                                   (new_cid, role, text or "", norm(text or ""), iso(m_created))).lastrowid
            old_last = mid
        con.execute("UPDATE conversations SET title = ?, model = ?, session_id = COALESCE(?, session_id), "
                    "updated_at = ? WHERE id = ?",
                    (title or "", model_of(last_model and last_model[0]), session, iso(c_updated), new_cid))
        con.execute("INSERT OR REPLACE INTO imported (kind, old_id, new_id, old_last, new_last) "
                    "VALUES ('conv', ?, ?, ?, ?)", (cid, new_cid, old_last, new_last))
        added += 1
    con.execute("UPDATE projects SET updated_at = MAX(updated_at, COALESCE((SELECT MAX(updated_at) "
                "FROM conversations WHERE project_id = ?), updated_at)) WHERE id = ?", (new_pid, new_pid))
    note = f", не тронуто (писали на новом): {skipped}" if skipped else ""
    return f"{name}: тем перенесено/обновлено {added}{note}"


def main(ids: list[int]) -> None:
    if not ids:
        sys.exit("Укажи номера проектов старого сайта")
    url = dotenv_values(OLD_ENV)["DATABASE_URL"]
    for p in backup(url):
        print("копия:", p)
    con = sqlite3.connect(NEW_DB, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute(IMPORTED)
    with psycopg.connect(url) as old_con:
        old_con.read_only = True
        old = old_con.cursor()
        try:
            for pid in ids:
                print(import_project(old, con, pid))
            con.commit()
        finally:
            con.close()


if __name__ == "__main__":
    main([int(a) for a in sys.argv[1:]])
