"""Проверки файлов проекта: загрузка, список, просмотр, скачивание, защита."""
import os
import time
from pathlib import Path

from common import TMP, client, db, inside  # noqa: F401
from test_chat import csrf_of
from test_projects import clean_folder, new_project  # noqa: F401

from app import files


def setup_project(c, name="Файлы"):
    pid = new_project(c, name)
    return pid, Path(db.one("SELECT path FROM projects WHERE id = ?", (pid,))["path"]) / "downloads"


def upload(c, pid, items, csrf=None, **kw):
    return c.post(f"/projects/{pid}/files/upload", data={"csrf": csrf or csrf_of(c), "back": ""},
                  files=[("files", item) for item in items], follow_redirects=False, **kw)


def test_files_closed_without_login(client):
    for path in ("/projects/1/files", "/projects/1/files/view/a.txt", "/projects/1/files/get/a.txt"):
        r = client.get(path, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"].endswith("/login"), path
    assert client.get("/projects/1/files/list").status_code == 403
    assert client.post("/projects/1/files/upload", files=[("files", ("a.txt", b"x"))]).status_code == 403


def test_upload_names_and_list(inside):
    pid, down = setup_project(inside)
    r = upload(inside, pid, [("заметка.txt", b"one"), ("заметка.txt", b"two"), (".env", b"secret=1"),
                             ("../../побег.txt", b"esc"), ("C:\\docs\\отчёт.md", b"# Hi")])
    assert r.status_code == 303 and r.headers["location"].endswith(f"/projects/{pid}/files?f=ok#files")
    names = sorted(p.name for p in down.iterdir())
    assert names == ["env", "заметка (2).txt", "заметка.txt", "отчёт.md", "побег.txt"]
    assert (down / "заметка (2).txt").read_bytes() == b"two"
    assert not (down.parent.parent / "побег.txt").exists()
    page = inside.get(f"/projects/{pid}").text
    assert "заметка (2).txt" in page and "Загрузить файлы" in page


def test_big_upload_and_limit(inside, monkeypatch):
    pid, down = setup_project(inside)
    blob = os.urandom(3 * 1024 * 1024)
    assert upload(inside, pid, [("большой.bin", blob)]).status_code == 303
    assert (down / "большой.bin").read_bytes() == blob
    monkeypatch.setattr(files, "UPLOAD_LIMIT", 1024 * 1024)
    r = upload(inside, pid, [("слишком.bin", blob)], headers={"x-upload": "1"})
    assert r.status_code == 400 and "512" in r.json()["message"]
    assert sorted(p.name for p in down.iterdir()) == ["большой.bin"]   # и без недогруженных хвостов


def test_upload_needs_token(inside):
    pid, down = setup_project(inside)
    assert upload(inside, pid, [("a.txt", b"x")], csrf="подделка").status_code == 403
    r = inside.post(f"/projects/{pid}/files/upload", data={"csrf": csrf_of(inside)},
                    files=[("files", ("a.txt", b"x"))], headers={"origin": "https://evil.example"})
    assert r.status_code == 403
    assert list(down.iterdir()) == []


def test_upload_json_answer(inside):
    pid, _ = setup_project(inside)
    r = upload(inside, pid, [("a.txt", b"x")], headers={"x-upload": "1"})
    assert r.json() == {"ok": True, "message": "Загружено"}
    html = inside.get(f"/projects/{pid}/files/list").json()["html"]
    assert "a.txt" in html


def test_download_is_sandboxed(inside):
    pid, down = setup_project(inside)
    (down / "стр.html").write_text("<script>alert(1)</script>")
    r = inside.get(f"/projects/{pid}/files/get/стр.html")
    assert r.status_code == 200 and r.text == "<script>alert(1)</script>"
    assert r.headers["content-security-policy"] == "sandbox"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["content-disposition"].startswith("attachment")
    assert r.headers["content-type"] == "application/octet-stream"


def test_only_plain_files_in_downloads(inside, tmp_path):
    pid, down = setup_project(inside)
    (down / ".hidden").write_text("тайна")
    outside = tmp_path / "secret.txt"
    outside.write_text("тайна")
    (down / "link.txt").symlink_to(outside)
    (down / "папка").mkdir()
    for name in (".hidden", "link.txt", "папка"):
        assert inside.get(f"/projects/{pid}/files/get/{name}").status_code == 404, name
    for name in ("..%2FCLAUDE.md", "%2E%2E%2FCLAUDE.md", "../CLAUDE.md"):
        r = inside.get(f"/projects/{pid}/files/get/{name}", follow_redirects=False)
        assert r.status_code in (303, 404) and "по-русски" not in r.text, name
    assert files.find({"path": str(down.parent)}, "../CLAUDE.md") is None
    listed = inside.get(f"/projects/{pid}/files").text
    assert "тайна" not in listed and ".hidden" not in listed and "link.txt" not in listed


def test_view_text_and_markdown(inside):
    pid, down = setup_project(inside)
    (down / "план.md").write_text("# План\n\n**жирно** <script>alert(1)</script>")
    (down / "список.txt").write_text("строка <b>1</b>")
    (down / "фото.jpg").write_bytes(b"\xff\xd8\xff\x00" * 100)
    md = inside.get(f"/projects/{pid}/files/view/план.md").text
    assert "<strong>жирно</strong>" in md and "<script>alert" not in md
    txt = inside.get(f"/projects/{pid}/files/view/список.txt").text
    assert "строка &lt;b&gt;1&lt;/b&gt;" in txt
    assert "не текст" in inside.get(f"/projects/{pid}/files/view/фото.jpg").text


def test_list_newest_first(inside):
    pid, down = setup_project(inside)
    for i, name in enumerate(("старый.txt", "средний.txt", "новый.txt")):
        (down / name).write_text(name)
        os.utime(down / name, (time.time() - 100 + i, time.time() - 100 + i))
    names = [f["name"] for f in files.list_files({"path": str(down.parent)})]
    assert names == ["новый.txt", "средний.txt", "старый.txt"]


def test_clean_name():
    assert files.clean_name("...") == "файл"
    assert files.clean_name("a\x00b\n.txt") == "ab.txt"
    long = files.clean_name("я" * 300 + ".pdf")
    assert long.endswith(".pdf") and len(long.encode()) <= 200
