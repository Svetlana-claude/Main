"""Проверки входа, замка и смены пароля на временной базе.

    webui2/.venv/bin/python -m pytest webui2/tests -q
"""
import os
import re
import sys
import tempfile
import time
from pathlib import Path

import pytest

TMP = Path(tempfile.mkdtemp(prefix="webui2-test-"))
(TMP / "test.env").write_text(f"SECRET_KEY=test-key\nDB_PATH={TMP / 'site.db'}\nLOGIN=Svetlana\n")
os.environ.update(WEBUI2_ENV=str(TMP / "test.env"), ROOT_PATH="", WEBUI2_INSECURE_COOKIE="1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app import db, security  # noqa: E402
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
            for table in ("sessions", "users", "login_fails", "setup"):
                con.execute(f"DELETE FROM {table}")
            con.execute("INSERT INTO setup (key, value) VALUES ('totp_secret', ?)", (SECRET,))
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


def test_pages_closed_without_login(client):
    for path in ("/", "/chat", "/projects", "/permissions", "/settings"):
        r = client.get(path, follow_redirects=False)
        assert r.status_code == 303
    # Хозяйки ещё нет — ведёт на первую настройку
    assert client.get("/login", follow_redirects=False).headers["location"].endswith("/setup")


def test_setup_needs_phone_code(client):
    r = do_setup(client, code="000000")
    assert r.status_code == 400 and "Код с телефона не подошёл" in r.text
    assert db.one("SELECT id FROM users") is None
    assert do_setup(client).status_code == 303
    user = db.one("SELECT password_hash, lock_hash FROM users")
    assert PASSWORD not in user["password_hash"] and user["password_hash"].startswith("$argon2")
    assert db.one("SELECT value FROM setup") is None
    # Второй раз страница настройки уже закрыта
    assert client.get("/setup", follow_redirects=False).status_code == 303


def test_setup_checks_password(client):
    assert "не короче 10" in do_setup(client, password="short", password2="short").text
    assert "не совпадают" in do_setup(client, password2="другой-пароль-123").text
    assert "от 4 до 8 цифр" in do_setup(client, lock="12", lock2="12").text


def test_login_logout(client):
    do_setup(client)
    r = do_login(client)
    assert r.status_code == 303
    assert client.get("/chat").status_code == 200
    assert "Выйти" in client.get("/chat").text
    csrf = hidden(client.get("/chat").text, "csrf")
    client.post("/logout", data={"csrf": csrf})
    assert client.get("/chat", follow_redirects=False).status_code == 303
    assert db.one("SELECT count(*) AS n FROM sessions")["n"] == 0


def test_wrong_password_and_code(client):
    do_setup(client)
    assert do_login(client, password="не-тот-пароль").status_code == 401
    assert do_login(client, code="123456").status_code == 401
    assert client.get("/chat", follow_redirects=False).status_code == 303


def test_code_not_reused(client):
    do_setup(client, code=code_now(-1))
    code = code_now()
    assert do_login(client, code=code).status_code == 303
    client.cookies.clear()
    assert do_login(client, code=code).status_code == 401


def test_brute_force_limit(client):
    do_setup(client)
    for _ in range(5):
        do_login(client, password="не-тот-пароль")
    r = do_login(client)
    assert r.status_code == 429 and "Слишком много попыток" in r.text


def test_form_without_token_refused(client):
    do_setup(client)
    r = client.post("/login", data={"pre": "чужой", "login": "Svetlana", "password": PASSWORD})
    assert r.status_code == 400
    do_login(client)
    # Запрос с чужого сайта
    r = client.post("/lock", data={"csrf": hidden(client.get("/chat").text, "csrf")},
                    headers={"origin": "https://evil.example"})
    assert r.status_code == 403
    r = client.post("/lock", data={"csrf": "не-тот"})
    assert r.status_code == 403


def test_lock(client):
    do_setup(client)
    do_login(client)
    csrf = hidden(client.get("/settings").text, "csrf")
    assert client.post("/lock", data={"csrf": csrf}).json() == {"ok": True}
    assert client.get("/state").json() == {"in": True, "locked": True}
    for path in ("/chat", "/projects", "/settings"):
        page = client.get(path)
        assert "Закрыто замком" in page.text and "Смена пароля" not in page.text
    r = client.post("/unlock", data={"csrf": csrf, "code": "1111", "back": "/settings"})
    assert r.status_code == 401
    r = client.post("/unlock", data={"csrf": csrf, "code": "2468", "back": "//evil.example/"},
                    follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"
    assert "Смена пароля" in client.get("/settings").text


def test_change_password(client):
    do_setup(client)
    do_login(client)
    csrf = hidden(client.get("/settings").text, "csrf")
    new = "новый-длинный-пароль"
    r = client.post("/settings/password", data={"csrf": csrf, "old": "не-тот", "new": new, "new2": new})
    assert "Старый пароль не подошёл" in r.text
    r = client.post("/settings/password", data={"csrf": csrf, "old": PASSWORD, "new": new, "new2": new})
    assert r.status_code == 200 and "Пароль изменён" in r.text
    client.cookies.clear()
    assert do_login(client).status_code == 401
    assert do_login(client, password=new, code=code_now(1)).status_code == 303


def test_time_shown_in_moscow():
    from app.main import local_time
    assert local_time("2026-10-27T09:00:00+00:00") == "27.10.2026 12:00 по Москве"
