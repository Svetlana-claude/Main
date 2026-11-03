"""Конструктор 3D: всё закрыто входом и замком, хранилище, ИИ выключен."""
import io
import zipfile
from pathlib import Path

import pytest

from common import TMP, client, db, inside  # noqa: F401
from test_chat import csrf_of

from app import konstruktor  # noqa: E402

MODEL = {"name": "Проба", "parts": [{"id": "a", "name": "А", "shape": {"type": "group"}}]}
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 100


@pytest.fixture(autouse=True)
def place(tmp_path, monkeypatch):
    monkeypatch.setattr(konstruktor, "DATA", tmp_path)
    monkeypatch.setattr(konstruktor, "TMP", tmp_path / ".meta" / "zagruzka")


ADDRESSES = [("get", "/3d/"), ("get", "/3d/redaktor.js"), ("get", "/3d/api/status"), ("get", "/3d/api/models"),
             ("get", "/3d/api/models/a"), ("put", "/3d/api/models/a"), ("delete", "/3d/api/models/a"),
             ("get", "/3d/api/exports"), ("get", "/3d/api/exports/a"), ("put", "/3d/api/exports/a"),
             ("get", "/3d/api/photos/a/0"), ("put", "/3d/api/photos/a/0"), ("post", "/3d/api/models/a/materialy"),
             ("put", "/3d/api/arhiv/a/abcdefgh"), ("post", "/3d/api/arhiv/a/abcdefgh/razobrat"), ("get", "/3d/api/chat/a"), ("post", "/3d/api/chat/a/start"), ("get", "/3d/api/models/a/versiya"), ("post", "/3d/api/generate"), ("post", "/3d/api/refine"), ("get", "/3d/api/nesushchestvuet")]


def test_closed_without_login(client):
    for method, url in ADDRESSES:
        r = getattr(client, method)(url, follow_redirects=False)
        assert r.status_code in (303, 403), url
        assert "three" not in r.text and "Конструктор" not in r.text, url


def test_closed_under_lock(inside):
    client = inside
    with db.tx() as con:
        con.execute("UPDATE sessions SET locked = 1")
    for method, url in ADDRESSES:
        r = getattr(client, method)(url, follow_redirects=False)
        assert "Конструктор" not in r.text, url
        if "/api/" in url:
            assert r.status_code == 403, url
        else:
            assert "Закрыто замком" in r.text, url


def test_editor_opens_and_stays_inside(inside):
    r = inside.get("/3d/")
    assert r.status_code == 200 and "Конструктор 3D" in r.text
    assert inside.get("/3d/dvizhok/format.js").status_code == 200
    assert inside.get("/3d/..%2f..%2f..%2fapp%2fconfig.py").status_code == 404
    assert inside.get("/3d/%2e%2e/%2e%2e/%2e%2e/webui2/app/config.py").status_code in (404, 200) \
        and "SECRET_KEY" not in inside.get("/3d/%2e%2e/%2e%2e/%2e%2e/webui2/app/config.py").text


def test_model_photo_export(inside):
    c = inside
    assert c.get("/3d/api/status").json()["ai"] is False
    assert c.put("/3d/api/models/proba", json={"model": MODEL}).status_code == 200
    assert c.put("/3d/api/models/proba", json={"model": {"x": 1}}).status_code == 400
    assert c.put("/3d/api/models/Плохой", json={"model": MODEL}).status_code == 400
    assert [m["id"] for m in c.get("/3d/api/models").json()["models"]] == ["proba"]
    (konstruktor.DATA / "modeli" / "slomana.json").write_text("{", encoding="utf-8")
    assert c.get("/3d/api/models/slomana").status_code == 409
    (konstruktor.DATA / "modeli" / "slomana.json").unlink()

    h = {"content-type": "image/png"}
    assert c.put("/3d/api/photos/proba/0?view=сбоку", content=PNG, headers=h).status_code == 200
    assert c.post("/3d/api/models/proba/materialy", json={"photos": [{"n": 1}]}).status_code == 400
    z = c.post("/3d/api/models/proba/materialy", json={"photos": [{"n": 0}], "size": "1 м"}).json()
    assert z["source"]["photos"] == [{"n": 0, "view": "сбоку", "file": "foto/proba/0.png"}] and z["source"]["size"] == "1 м"
    r = c.get("/3d/api/photos/proba/0")
    assert r.content == PNG and r.headers["content-type"] == "image/png"
    assert c.put("/3d/api/photos/proba/1", content=b"<b>", headers={"content-type": "text/html"}).status_code == 400
    assert c.put("/3d/api/photos/proba/100", content=PNG, headers=h).status_code == 400
    assert c.put("/3d/api/photos/proba/1", content=b"0" * (5 * 1024 * 1024 + 1), headers=h).status_code == 400

    assert c.put("/3d/api/exports/proba?name=Проба", content=b"<html>", headers={"content-type": "text/html"}).status_code == 200
    assert c.get("/3d/api/exports").json()["exports"][0]["name"] == "Проба"
    r = c.get("/3d/api/exports/proba")
    assert r.content == b"<html>" and "attachment" in r.headers["content-disposition"]

    assert c.delete("/3d/api/models/proba").status_code == 200
    assert c.get("/3d/api/models/proba").status_code == 404 and c.get("/3d/api/exports/proba").status_code == 404


def test_foreign_page_cannot_write(inside):
    r = inside.put("/3d/api/models/proba", json={"model": MODEL}, headers={"origin": "https://chuzhoy.example"})
    assert r.status_code == 403
    assert not list(konstruktor.DATA.glob("models/*"))


def test_ai_is_off(inside):
    for url in ("/3d/api/generate", "/3d/api/refine"):
        r = inside.post(url, json={})
        assert r.status_code == 400 and "выключено" in r.json()["error"]


def test_project_and_chat(inside, monkeypatch):
    c = inside
    assert c.get("/3d/api/status").json()["chat"] is True
    row = db.one("SELECT * FROM projects WHERE slug = '3d-modeli'")
    folder = Path(row["path"])
    assert (folder / "PAMYATKA.md").is_file() and (folder / "modeli/parashyut.json").is_file()
    assert "foto/" in (folder / ".gitignore").read_text(encoding="utf-8")
    monkeypatch.setattr(konstruktor, "DATA", folder)
    st = c.get("/3d/api/chat/parashyut").json()
    assert st["conv"] is None
    assert c.post("/3d/api/chat/net-takoy/start").status_code == 404
    first = c.post("/3d/api/chat/parashyut/start").json()
    assert first["first"] is True
    again = c.post("/3d/api/chat/parashyut/start").json()
    assert again == {"conv": first["conv"], "first": True}   # сообщений ещё нет
    other = c.post("/3d/api/chat/samolet/start").json()
    assert other["conv"] != first["conv"]


def test_models_project_is_locked(inside):
    from app import claude, config
    project = {"slug": config.MODELS_SLUG, "full_access": 1, "allow_commands": 1, "path": "/x"}
    cmd = claude.project_argv("opus", None, project)
    assert cmd[cmd.index("--tools") + 1] == "Read,Write,Edit,Glob,Grep"
    assert "bypassPermissions" not in cmd and cmd[cmd.index("--permission-prompts") + 1] == "none"


def _upload(c, data: bytes, token="abcdefgh12", name="a.zip", step=1000):
    for at in range(0, len(data), step):
        r = c.put(f"/3d/api/arhiv/proba/{token}?offset={at}", content=data[at:at + step])
        assert r.status_code == 200
    return c.post(f"/3d/api/arhiv/proba/{token}/razobrat", params={"name": name})


def _jpeg() -> bytes:
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (3000, 2000), "red").save(b, "JPEG")
    return b.getvalue()


def test_archive(inside):
    c = inside
    assert c.put("/3d/api/models/proba", json={"model": MODEL}).status_code == 200
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("папка/спереди.JPG", _jpeg())
        z.writestr("../../vzlom.jpg", _jpeg())
        z.writestr("заметка.txt", "x")
        z.writestr("битое.png", "не картинка")
        z.writestr("__MACOSX/._a.jpg", "x")
    r = _upload(c, b.getvalue()).json()
    views = sorted(p["view"] for p in r["photos"])
    assert views == ["vzlom", "спереди"]
    assert sorted(r["skipped"]) == ["битое.png", "заметка.txt"]
    assert not (konstruktor.DATA.parent / "vzlom.jpg").exists()
    img = c.get(f"/3d/api/photos/proba/{r['photos'][0]['n']}")
    assert img.headers["content-type"] == "image/jpeg" and len(img.content) < 200000
    assert not list(konstruktor.TMP.iterdir())


def test_archive_refusals(inside):
    c = inside
    c.put("/3d/api/models/proba", json={"model": MODEL})
    r = c.put("/3d/api/arhiv/proba/abcdefgh12?offset=5", content=b"x")
    assert r.status_code == 409 and r.json()["have"] == 0
    c.put("/3d/api/arhiv/proba/abcdefgh99?offset=0", content=b"12345")
    assert c.put("/3d/api/arhiv/proba/abcdefgh99?offset=0", content=b"x").json()["have"] == 5
    r = _upload(c, b"neponyatno", name="a.txt")
    assert r.status_code == 400 and "не снимок" in r.json()["error"]
    assert c.post("/3d/api/arhiv/proba/abcdefgh12/razobrat").status_code == 400
    assert c.put("/3d/api/arhiv/proba/plohoy!/x").status_code in (400, 404, 405)
