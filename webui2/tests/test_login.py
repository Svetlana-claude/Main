"""Проверки входа, замка и смены пароля на временной базе.

    webui2/.venv/bin/python -m pytest webui2/tests -q
"""
from common import (PASSWORD, client, code_now, db, do_login, do_setup, hidden,  # noqa: F401
                    security)


def test_pages_closed_without_login(client):
    for path in ("/", "/chat", "/projects", "/permissions", "/settings"):
        r = client.get(path, follow_redirects=False)
        assert r.status_code == 303
    # Хозяйки ещё нет — ведёт на первую настройку
    assert client.get("/login", follow_redirects=False).headers["location"].endswith("/setup")


def test_unknown_address_leads_home(client):
    r = client.get("/c/290", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith("/")
    assert client.get("/static/nety.css").status_code == 404


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
    from app.web import local_time
    assert local_time("2026-10-27T09:00:00+00:00") == "27.10.2026 12:00 по Москве"
