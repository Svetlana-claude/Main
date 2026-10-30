"""Конструктор 3D: всё закрыто входом и замком, хранилище, ИИ выключен."""
import os
import re
from pathlib import Path

import pytest

from common import TMP, client, db, inside  # noqa: F401
from test_chat import csrf_of

os.environ.setdefault("KONSTRUKTOR3D_DIR", str(TMP / "k3d"))
from app import konstruktor  # noqa: E402

MODEL = {"name": "Проба", "parts": [{"id": "a", "name": "А", "shape": {"type": "group"}}]}
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 100


@pytest.fixture(autouse=True)
def place(tmp_path, monkeypatch):
    monkeypatch.setattr(konstruktor, "DATA", tmp_path)


ADDRESSES = [("get", "/3d/"), ("get", "/3d/redaktor.js"), ("get", "/3d/api/status"), ("get", "/3d/api/models"),
             ("get", "/3d/api/models/a"), ("put", "/3d/api/models/a"), ("delete", "/3d/api/models/a"),
             ("get", "/3d/api/exports"), ("get", "/3d/api/exports/a"), ("put", "/3d/api/exports/a"),
             ("get", "/3d/api/photos/a/0"), ("put", "/3d/api/photos/a/0"), ("post", "/3d/api/models/a/materialy"),
             ("post", "/3d/api/generate"), ("post", "/3d/api/refine"), ("get", "/3d/api/nesushchestvuet")]


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

    h = {"content-type": "image/png"}
    assert c.put("/3d/api/photos/proba/0?view=сбоку", content=PNG, headers=h).status_code == 200
    assert c.post("/3d/api/models/proba/materialy", json={"photos": [{"n": 1}]}).status_code == 400
    z = c.post("/3d/api/models/proba/materialy", json={"photos": [{"n": 0}], "size": "1 м"}).json()
    assert z["source"]["photos"] == [{"n": 0, "view": "сбоку"}] and z["source"]["size"] == "1 м"
    r = c.get("/3d/api/photos/proba/0")
    assert r.content == PNG and r.headers["content-type"] == "image/png"
    assert c.put("/3d/api/photos/proba/1", content=b"<b>", headers={"content-type": "text/html"}).status_code == 400
    assert c.put("/3d/api/photos/proba/40", content=PNG, headers=h).status_code == 400
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
