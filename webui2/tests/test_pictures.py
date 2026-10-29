"""Проверки «Картинок»: сетка по проектам и папкам, превью, закрытое не отдаётся."""
import io
import os
from pathlib import Path

from PIL import Image

from common import TMP, client, db, inside  # noqa: F401
from test_projects import clean_folder, new_project  # noqa: F401


def png(path: Path, size=(40, 30)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (200, 30, 30)).save(path)


def setup_pics(c):
    pid = new_project(c, "Галерея")
    base = Path(db.one("SELECT path FROM projects WHERE id = ?", (pid,))["path"])
    png(base / "obl.png")
    png(base / "maket" / "glavnaya.png", (900, 600))
    png(base / "maket" / "sub" / "knopka.jpg")
    (base / "maket" / "risunok.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>')
    png(base / ".skrytoe" / "net.png")
    png(base / "node_modules" / "net.png")
    png(base / ".hidden.png")
    (base / ".env").write_text("SECRET=1")
    (base / "notes.txt").write_text("не картинка")
    env = base / "okruzhenie"
    png(env / "net.png")
    (env / "pyvenv.cfg").write_text("")
    outside = TMP / "vne.png"
    png(outside)
    os.symlink(outside, base / "ssylka.png")
    return pid, base


def test_closed_without_login(client):
    assert client.get("/pictures", follow_redirects=False).status_code == 303
    for path in ("/pictures/list", "/pictures/thumb?src=1/obl.png", "/pictures/view?src=1/obl.png",
                 "/pictures/file?src=1/obl.png"):
        assert client.get(path).status_code == 403


def test_catalog_by_project_and_folder(inside):
    pid, _ = setup_pics(inside)
    page = inside.get("/pictures").text
    assert 'title="Картинки"' in page and 'aria-current="page"' in page
    data = inside.get("/pictures/list").json()
    group = next(g for g in data["groups"] if g["id"] == pid)
    folders = {f["path"]: sorted(i["name"] for i in f["images"]) for f in group["folders"]}
    assert folders == {"": ["obl.png"], "maket": ["glavnaya.png", "risunok.svg"], "maket/sub": ["knopka.jpg"]}
    assert group["count"] == 4 and group["folders"][0]["path"] == ""


def test_thumb_view_and_file(inside):
    pid, _ = setup_pics(inside)
    r = inside.get(f"/pictures/thumb?src={pid}/maket/glavnaya.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/webp"
    assert max(Image.open(io.BytesIO(r.content)).size) == 480
    assert inside.get(f"/pictures/thumb?src={pid}/maket/glavnaya.png").content == r.content   # из склада
    v = inside.get(f"/pictures/view?src={pid}/maket/risunok.svg")
    assert v.status_code == 200 and v.headers["content-security-policy"] == "sandbox"
    f = inside.get(f"/pictures/file?src={pid}/obl.png")
    assert f.status_code == 200 and "attachment" in f.headers["content-disposition"]


def test_closed_files_are_not_served(inside):
    pid, _ = setup_pics(inside)
    for src in (".env", "notes.txt", ".hidden.png", ".skrytoe/net.png", "node_modules/net.png",
                "okruzhenie/net.png", "ssylka.png", "../vne.png", "maket/../../vne.png",
                "maket/../obl.png", "/etc/passwd", "999/obl.png", "x/obl.png"):
        key = src if src[0].isdigit() or src.startswith("x/") else f"{pid}/{src}"
        assert inside.get("/pictures/view", params={"src": key}).status_code == 404, src
