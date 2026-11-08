"""Общее для проверок: временная база и папки, подставной Claude, клиенты."""
import io
import os
import re
import tempfile
import time
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="zd-test-"))
HERE = Path(__file__).resolve().parent
import sys  # noqa: E402
sys.path.insert(0, str(HERE.parent))
(TMP / "test.env").write_text(
    f"SECRET_KEY=test-key-0123456789\nDATA_DIR={TMP / 'data'}\nLOGIN=Svetlana\n"
    f"CLAUDE_BIN={HERE / 'fake_claude.py'}\nSITE_URL=http://testserver\n", encoding="utf-8")
os.environ.update(ZD_ENV=str(TMP / "test.env"), ROOT_PATH="", ZD_INSECURE_COOKIE="1",
                  ZD_KOPII=str(TMP / "kopii"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from app import config, db, security  # noqa: E402
from app.main import app  # noqa: E402

PASSWORD = "очень-длинный-пароль"
ORIGIN = {"Origin": "http://testserver"}


def new_client() -> TestClient:
    return TestClient(app, headers=ORIGIN, follow_redirects=False)


def hidden(html: str, name: str) -> str:
    m = re.search(rf'name="{name}" value="([^"]*)"', html)
    assert m, f"нет поля {name}"
    return m.group(1)


def code_now(secret: str, shift: int = 0) -> str:
    return security.totp_at(secret, int(time.time()) // 30 + shift)


def setup_link() -> str:
    """Как tools/prepare.py: секрет и разовая ссылка."""
    import secrets
    token = secrets.token_urlsafe(24)
    with db.tx() as con:
        con.execute("DELETE FROM setup")
        con.execute("INSERT INTO setup (key, value) VALUES ('totp_secret', ?)", (security.new_totp_secret(),))
        con.execute("INSERT INTO setup (key, value) VALUES ('token_hash', ?)", (security.token_hash(token),))
    return token


def owner_secret() -> str:
    return db.one("SELECT totp_secret FROM users WHERE role = 'owner'")["totp_secret"]


def reset_fails() -> None:
    db.run("DELETE FROM login_fails")


def login(c: TestClient, login_name: str, password: str, secret: str | None = None, shift: int = 0):
    r = c.get("/login")
    r = c.post("/login", data={"login": login_name, "password": password, "pre": hidden(r.text, "pre")})
    if secret is None:
        return r
    assert r.status_code == 200 and "Код с телефона" in r.text, r.text[:300]
    return c.post("/login/code", data={"pass_token": hidden(r.text, "pass_token"), "code": code_now(secret, shift),
                                       "pre": hidden(r.text, "pre")})


def csrf(c: TestClient) -> str:
    return hidden(c.get("/").text, "csrf")


def jpeg(text: str = "blank") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (400, 300), "white").save(buf, "JPEG")
    return buf.getvalue()


def wait_parsed(doc_id: int, timeout: float = 20) -> dict:
    end = time.time() + timeout
    while time.time() < end:
        doc = db.one("SELECT * FROM docs WHERE id = ?", (doc_id,))
        if doc["state"] != "parsing":
            return doc
        time.sleep(0.1)
    raise AssertionError("разбор не закончился")


@pytest.fixture(scope="session")
def site():
    """Сайт с пройденной настройкой и вошедшей Светланой."""
    with new_client() as c:
        token = setup_link()
        r = c.get(f"/setup/{token}")
        secret = db.one("SELECT value FROM setup WHERE key = 'totp_secret'")["value"]
        r = c.post(f"/setup/{token}", data={"password": PASSWORD, "password2": PASSWORD,
                                            "code": code_now(secret), "pre": hidden(r.text, "pre")})
        assert r.status_code == 303
        r = login(c, "Svetlana", PASSWORD, secret, shift=1)
        assert r.status_code == 303, r.text[:300]
        yield c


__all__ = ["config", "TMP"]
