"""Проверка загрузки нескольких файлов и целой папки во вкладке «Загрузка».

Что ломается и что здесь ловится:

* **форма берёт один файл** — у поля нет `multiple`, а у второго поля нет
  `webkitdirectory`: выбрать несколько файлов или папку браузер не даст;
* **сервер берёт один файл из пачки** — без скриптов форма шлёт все файлы
  одним запросом, и до правки в базу попадал только первый;
* **путь внутри папки теряется** — файлы папки ложатся россыпью, и чей
  кадр «1.png» из трёх одинаковых, уже не понять. Путь должен остаться
  и в подписи (`files.filename`), и на диске — общей папкой выбора;
* **путь из браузера выводит запись наружу** — `../` в пути — чужие данные,
  файл обязан лечь внутри `uploads/`;
* **два имени после транслитерации совпали** («a b» и «a-b») — второй файл
  не должен затереть первый;
* **удаление оставляет пустые папки** в `uploads/`.

Стенд поднимает свою копию приложения на свободном порту (как
`check_upload_limit.py`) и заводит свой проект; рабочая служба не трогается.

Запуск:  .venv/bin/python tests/check_upload_mnogo.py
"""
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import config, db, security as auth          # noqa: E402
from check_upload_limit import free_port, wait_ready   # noqa: E402

PROJECT_DIR = Path(__file__).resolve().parent.parent
FAILED: list[str] = []


def check(ok: bool, what: str) -> None:
    if ok:
        print(f"  ok: {what}")
    else:
        FAILED.append(what)
        print(f"  ПРОВАЛ: {what}")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


OPENER = urllib.request.build_opener(NoRedirect)


def post(url: str, cookie: str, files: list[tuple[str, bytes]],
         fields: dict[str, str] | None = None, js: bool = False):
    """Многочастный запрос: поля и файлы под общим именем `upload`.
    Возвращает код ответа, адрес переадресации и тело."""
    boundary = "granitsa" + uuid.uuid4().hex
    body = b""
    for name, value in (fields or {}).items():
        body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n"
                 f"{value}\r\n").encode()
    for filename, data in files:
        body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"upload\"; "
                 f"filename=\"{filename}\"\r\nContent-Type: application/octet-stream\r\n\r\n"
                 ).encode() + data + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    req.add_header("Cookie", f"{config.COOKIE_NAME}={cookie}")
    if js:
        req.add_header("X-Zagruzka", "1")
    try:
        with OPENER.open(req, timeout=60) as res:
            return res.status, res.headers.get("Location", ""), res.read().decode()
    except urllib.error.HTTPError as err:
        return err.code, err.headers.get("Location", ""), err.read().decode("utf-8", "replace")


def rows(project_id: int) -> list[dict]:
    return db.query(
        "SELECT id, filename, stored_name, size_bytes FROM files "
        "WHERE project_id = %s ORDER BY id", (project_id,))


def inside_uploads(stored: str) -> bool:
    uploads = config.UPLOADS_DIR.resolve()
    path = (config.UPLOADS_DIR / stored).resolve()
    return uploads in path.parents and path.is_file()


def run(port: int, cookie: str, project_id: int) -> None:
    url = f"http://127.0.0.1:{port}"
    action = f"{url}/projects/{project_id}/upload"

    page = urllib.request.urlopen(urllib.request.Request(
        f"{url}/projects?id={project_id}",
        headers={"Cookie": f"{config.COOKIE_NAME}={cookie}"}), timeout=30
    ).read().decode("utf-8", "replace")
    tags = re.findall(r"<input[^>]*type=\"file\"[^>]*>", page)
    check(any("multiple" in t and 'id="upload-files"' in t for t in tags),
          "поле файлов разрешает выбрать несколько")
    check(any("webkitdirectory" in t for t in tags), "есть поле выбора папки")

    print("Без скриптов — вся пачка одним запросом:")
    code, where, _ = post(action, cookie, [
        ("первый.txt", b"1"), ("второй.txt", b"22"), ("третий.txt", b"333")])
    got = rows(project_id)
    check(code == 303 and "err=" not in where, f"ответ — переадресация без ошибки ({code} {where})")
    check([r["filename"] for r in got] == ["первый.txt", "второй.txt", "третий.txt"],
          f"приняты все три файла, а не первый ({[r['filename'] for r in got]})")
    check(all(inside_uploads(r["stored_name"]) for r in got), "все три легли на диск")

    print("Со скриптом — папка, по файлу на запрос:")
    paket = uuid.uuid4().hex
    before = {r["id"] for r in rows(project_id)}
    for put, data in [("Фото/вложенная/кадр 1.png", b"a"),
                      ("Фото/a b.txt", b"bb"),
                      ("Фото/a-b.txt", b"ccc"),
                      ("../../../tmp/побег.txt", b"dddd")]:
        code, _, body = post(action, cookie, [(Path(put).name, data)],
                             {"put": put, "paket": paket}, js=True)
        check(code == 200 and json.loads(body).get("ok") is True,
              f"«{put}»: ответ JSON ok ({code})")
    new = [r for r in rows(project_id) if r["id"] not in before]
    names = {r["filename"]: r for r in new}
    check(set(names) == {"Фото/вложенная/кадр 1.png", "Фото/a b.txt", "Фото/a-b.txt", "tmp/побег.txt"},
          f"подписи хранят путь внутри папки, без `..` ({sorted(names)})")
    folder = [r for r in new if r["filename"].startswith("Фото/")]
    tops = {Path(r["stored_name"]).parts[0] for r in folder}
    check(len(tops) == 1 and next(iter(tops)).startswith(paket),
          f"файлы одной папки лежат на диске вместе ({sorted(tops)})")
    check(any(len(Path(r["stored_name"]).parts) == 3 for r in folder),
          "вложенность папки сохранена на диске")
    check(all(inside_uploads(r["stored_name"]) for r in new), "ничего не легло вне uploads/")
    ab = [names.get("Фото/a b.txt"), names.get("Фото/a-b.txt")]
    check(all(ab) and ab[0]["stored_name"] != ab[1]["stored_name"]
          and (config.UPLOADS_DIR / ab[0]["stored_name"]).read_bytes() == b"bb"
          and (config.UPLOADS_DIR / ab[1]["stored_name"]).read_bytes() == b"ccc",
          "совпавшие после транслитерации имена не затёрли друг друга")

    print("Удаление:")
    nested = names.get("Фото/вложенная/кадр 1.png")
    if nested:
        subdir = (config.UPLOADS_DIR / nested["stored_name"]).parent
        post(f"{url}/projects/files/{nested['id']}/delete", cookie, [])
        check(not subdir.exists(), "опустевшая папка убрана вместе с файлом")
        check((config.UPLOADS_DIR / ab[0]["stored_name"]).is_file(),
              "непустая папка выбора осталась")


def main() -> int:
    db.init_pool()
    user = db.query_one("SELECT id FROM users ORDER BY id LIMIT 1")
    if not user:
        print("ПРОВАЛ: в базе нет пользователя")
        return 1

    mark = uuid.uuid4().hex[:8]
    session_id = auth.new_session_id()
    db.execute(
        "INSERT INTO sessions (id, user_id, expires_at, ip, user_agent) "
        "VALUES (%s, %s, %s, %s, %s)",
        (session_id, user["id"], auth.session_expiry(), "127.0.0.1", "check_upload_mnogo"),
    )
    project_id = db.query_one(
        "INSERT INTO projects (name, slug, workdir) VALUES (%s, %s, %s) RETURNING id",
        (f"Стенд загрузки {mark}", f"stend-zagruzki-{mark}", "/tmp/stend-zagruzki"),
    )["id"]

    port = free_port()
    proc = subprocess.Popen(
        [str(PROJECT_DIR / ".venv/bin/python"), "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=str(PROJECT_DIR), env=dict(os.environ, ROOT_PATH=""),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        if not wait_ready(port, proc):
            print("ПРОВАЛ: стенд приложения не поднялся")
            return 1
        run(port, auth.sign_session_id(session_id), project_id)
    finally:
        proc.terminate()
        proc.wait(timeout=20)
        for row in rows(project_id):
            path = config.UPLOADS_DIR / row["stored_name"]
            path.unlink(missing_ok=True)
            if path.parent != config.UPLOADS_DIR:
                for parent in path.parents:
                    if parent == config.UPLOADS_DIR:
                        break
                    try:
                        parent.rmdir()
                    except OSError:
                        break
        db.execute("DELETE FROM projects WHERE id = %s", (project_id,))
        db.execute("DELETE FROM sessions WHERE id = %s", (session_id,))

    if FAILED:
        print(f"ПРОВАЛ ({len(FAILED)}):")
        for what in FAILED:
            print(" -", what)
        return 1
    print("OK: несколько файлов и папка принимаются, путь сохраняется, наружу не выходит")
    return 0


if __name__ == "__main__":
    sys.exit(main())
