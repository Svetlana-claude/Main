"""Общее для проверок: временная база, подставной Claude, вход."""
import os
import re
import sys
import tempfile
import time
from pathlib import Path

import pytest

TMP = Path(tempfile.mkdtemp(prefix="webui2-test-"))
FAKE = Path(__file__).resolve().parent / "fake_claude.py"
CLAUDE_LOG = TMP / "claude.log"
(TMP / "test.env").write_text(f"SECRET_KEY=test-key\nDB_PATH={TMP / 'site.db'}\nLOGIN=Svetlana\n"
                              f"CLAUDE_BIN={FAKE}\nCHAT_DIR={TMP / 'room'}\n"
                              f"PROJECTS_DIR={TMP / 'projects'}\n"
                              f"POWER_CMD={sys.executable} {Path(__file__).resolve().parent / 'fake_power.py'}\n")
os.environ.update(WEBUI2_ENV=str(TMP / "test.env"), ROOT_PATH="", WEBUI2_INSECURE_COOKIE="1",
                  FAKE_CLAUDE_LOG=str(CLAUDE_LOG), FAKE_POWER_LOG=str(TMP / "power.log"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app import db, security, web  # noqa: E402
from app.main import app  # noqa: E402

SECRET = "JBSWY3DPEHPK3PXP"
PASSWORD = "очень-длинный-пароль"
ORIGIN = {"origin": "http://testserver"}


def code_now(shift: int = 0) -> str:
    return security.totp_at(SECRET, int(time.time()) // 30 + shift)


def hidden(html: str, name: str) -> str:
    return re.search(rf'name="{name}" value="([^"]*)"', html).group(1)


@pytest.fixture()
def client():
    with TestClient(app, headers=ORIGIN) as c:
        with db.tx() as con:
            for table in ("messages", "conversations", "projects", "sessions", "users", "login_fails", "setup",
                          "prefs", "load_samples"):
                con.execute(f"DELETE FROM {table}")
            con.execute("INSERT INTO setup (key, value) VALUES ('totp_secret', ?)", (SECRET,))
        web._zone["name"] = None
        yield c


def do_setup(c, code=None, **over):
    page = c.get("/setup")
    form = {"pre": hidden(page.text, "pre"), "password": PASSWORD, "password2": PASSWORD,
            "lock": "2468", "lock2": "2468", "code": code or code_now(-1)}
    form.update(over)
    return c.post("/setup", data=form, follow_redirects=False)


def do_login(c, password=PASSWORD, code=None):
    page = c.get("/login")
    r = c.post("/login", data={"pre": hidden(page.text, "pre"), "login": "Svetlana",
                               "password": password})
    if r.status_code != 200:
        return r
    return c.post("/login/code", data={"pre": hidden(r.text, "pre"),
                                       "pass_token": hidden(r.text, "pass_token"),
                                       "code": code or code_now()}, follow_redirects=False)


@pytest.fixture()
def inside(client):
    """Хозяйка заведена и вошла."""
    do_setup(client)
    assert do_login(client).status_code == 303
    return client
