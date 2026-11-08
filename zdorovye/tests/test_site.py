"""Проверки «Здоровья»: вход, приглашения, доступы, странички, анализы, копии."""
import os
import re
import subprocess
import sys
from pathlib import Path

from conftest import (PASSWORD, TMP, csrf, hidden, jpeg, login, new_client,
                      reset_fails, setup_link, wait_parsed)

from app import config, db

ROOT = Path(__file__).resolve().parents[1]


def add_member(c, name: str, birth: str = "1990-05-01") -> int:
    r = c.post("/members/new", data={"name": name, "birth_date": birth, "sex": "ж", "csrf": csrf(c)})
    assert r.status_code == 303
    return int(r.headers["location"].rstrip("/").split("/")[-1])


def invite(c, member_id: int) -> str:
    r = c.post("/invites/new", data={"member_id": member_id, "csrf": csrf(c)})
    assert r.status_code == 200, r.text[:300]
    return re.search(r"/join/([\w-]+)", r.text).group(1)


def join(token: str, login_name: str):
    m = new_client()
    r = m.get(f"/join/{token}")
    assert r.status_code == 200
    r = m.post(f"/join/{token}", data={"login": login_name, "password": PASSWORD, "password2": PASSWORD,
                                       "pre": hidden(r.text, "pre")})
    return m, r


# ── 1. Вход ──────────────────────────────────────────────────────────────

def test_owner_sees_everyone(site):
    a = add_member(site, "Светлана")
    b = add_member(site, "Андрей")
    r = site.get("/")
    assert r.status_code == 200 and "Светлана" in r.text and "Андрей" in r.text
    assert site.get(f"/m/{a}").status_code == 200 and site.get(f"/m/{b}").status_code == 200


def test_setup_link_dies_after_use(site):
    r = site.get("/setup/anything")
    assert r.status_code == 303 and r.headers["location"].endswith("/login")


def test_wrong_code_does_not_enter(site):
    reset_fails()
    c = new_client()
    r = login(c, "Svetlana", PASSWORD)
    r = c.post("/login/code", data={"pass_token": hidden(r.text, "pass_token"), "code": "000000",
                                    "pre": hidden(r.text, "pre")})
    assert r.status_code == 401
    assert c.get("/").status_code == 303


# ── 7. Чужим закрыто ─────────────────────────────────────────────────────

def test_nothing_without_login(site):
    member_id = add_member(site, "Без входа")
    c = new_client()
    for path in ("/", f"/m/{member_id}", "/access", f"/m/{member_id}/docs/1/file", "/kopii/klyuch",
                 f"/m/{member_id}/chart?key=x"):
        r = c.get(path)
        assert r.status_code in (303, 401), path
        assert "Без входа" not in r.text
    r = c.post(f"/m/{member_id}/profile", data={"name": "взлом"})
    assert r.status_code in (401, 403)
    assert db.one("SELECT name FROM members WHERE id = ?", (member_id,))["name"] == "Без входа"


def test_brute_force_blocked(site):
    reset_fails()
    c = new_client()
    for _ in range(config.FAIL_LIMIT):
        assert login(c, "Svetlana", "неверный-пароль").status_code == 401
    r = login(c, "Svetlana", PASSWORD)
    assert r.status_code == 429 and "Слишком много попыток" in r.text
    reset_fails()


def test_forms_need_csrf(site):
    member_id = add_member(site, "Проверка формы")
    r = site.post(f"/m/{member_id}/profile", data={"name": "без знака"})
    assert r.status_code == 403
    other = new_client()
    other.cookies = site.cookies
    r = other.post(f"/m/{member_id}/profile", data={"name": "чужой сайт", "csrf": csrf(site)},
                   headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


# ── 2. Приглашения и доступы ─────────────────────────────────────────────

def test_invite_access_flow(site):
    own = add_member(site, "Муж")
    child = add_member(site, "Дочка", "2015-03-02")
    token = invite(site, own)
    m, r = join(token, "andrey")
    assert r.status_code == 303
    # Ссылка разовая
    assert new_client().get(f"/join/{token}").status_code == 404

    home = m.get("/").text
    assert "Моя страничка" in home and "Муж" in home
    assert m.get(f"/m/{own}").status_code == 200
    assert m.get(f"/m/{child}").status_code == 404
    assert m.get("/access").status_code == 403
    # Свою страничку править можно
    mc = hidden(m.get("/").text, "csrf")
    assert m.post(f"/m/{own}/profile", data={"name": "Муж", "allergies": "пенициллин", "csrf": mc}).status_code == 303

    # Запрос → у Светланы «Принять»
    assert m.post("/access/ask", data={"member_id": child, "csrf": mc}).status_code == 303
    page = site.get("/access").text
    assert "andrey" in page and "Принять" in page and "Отклонить" in page
    access_id = db.one("SELECT id FROM access WHERE state = 'asked'")["id"]
    site.post(f"/access/{access_id}/grant", data={"csrf": csrf(site)})
    assert m.get(f"/m/{child}").status_code == 200
    # Чужую — только смотреть
    assert m.post(f"/m/{child}/profile", data={"name": "x", "csrf": mc}).status_code == 403
    assert "Завершить" in site.get("/access").text

    # «Завершить» — снова закрыто
    site.post(f"/access/{access_id}/end", data={"csrf": csrf(site)})
    assert m.get(f"/m/{child}").status_code == 404

    # Отклонённый запрос доступа не даёт
    m.post("/access/ask", data={"member_id": child, "csrf": mc})
    again = db.one("SELECT id FROM access WHERE state = 'asked'")["id"]
    site.post(f"/access/{again}/decline", data={"csrf": csrf(site)})
    assert m.get(f"/m/{child}").status_code == 404
    assert "Попросить ещё раз" in m.get("/").text

    # Удалённый вход больше не входит
    user_id = db.one("SELECT id FROM users WHERE login = 'andrey'")["id"]
    site.post(f"/users/{user_id}/delete", data={"csrf": csrf(site)})
    assert m.get("/").status_code == 303


def test_member_cannot_grant_himself(site):
    own = add_member(site, "Брат")
    other = add_member(site, "Сестра")
    m, _ = join(invite(site, own), "brat")
    mc = hidden(m.get("/").text, "csrf")
    m.post("/access/ask", data={"member_id": other, "csrf": mc})
    access_id = db.one("SELECT id FROM access WHERE state = 'asked' ORDER BY id DESC")["id"]
    assert m.post(f"/access/{access_id}/grant", data={"csrf": mc}).status_code == 403
    assert m.get(f"/m/{other}").status_code == 404
    assert m.post("/invites/new", data={"member_id": other, "csrf": mc}).status_code == 403


# ── 3. Страничка ─────────────────────────────────────────────────────────

def test_profile_illness_vaccine(site):
    mid = add_member(site, "Бабушка", "1950-01-10")
    c = csrf(site)
    site.post(f"/m/{mid}/profile", data={"name": "Бабушка", "birth_date": "1950-01-10", "chronic": "гипертония",
                                         "medicines": "лозартан 50 мг утром", "vitamins": "D3 2000", "csrf": c})
    site.post(f"/m/{mid}/ill", data={"title": "ОРВИ", "started": "2026-02-01", "ended": "2026-02-07",
                                     "treatment": "постельный режим", "csrf": c})
    site.post(f"/m/{mid}/ill", data={"title": "Бронхит", "started": "2025-11-03", "csrf": c})
    site.post(f"/m/{mid}/vac", data={"name": "Грипп", "done_on": "2025-10-01", "next_due": "2026-01-01", "csrf": c})
    page = site.get(f"/m/{mid}").text
    for text in ("гипертония", "лозартан", "D3 2000", "ОРВИ", "постельный режим", "Бронхит", "Грипп",
                 "01.01.2026", "пора", "<b>2026</b>: 1 раз, 7 дн."):
        assert text in page, text
    assert "Прививка: Грипп" in site.get("/").text


# ── 4. Анализы ───────────────────────────────────────────────────────────

def upload(c, mid: int, **env) -> int:
    os.environ.update(env)
    r = c.post(f"/m/{mid}/docs", data={"csrf": csrf(c)}, files={"blank": ("blank.jpg", jpeg(), "image/jpeg")})
    assert r.status_code == 303, r.text[:300]
    return int(r.headers["location"].rstrip("/").split("/")[-1])


def test_lab_parse_review_chart(site):
    mid = add_member(site, "Анализы")
    doc_id = upload(site, mid, FAKE_HB="105", FAKE_DATE="2026-09-01", FAKE_MODE="ok")
    doc = wait_parsed(doc_id)
    assert doc["state"] == "review" and doc["taken_on"] == "2026-09-01" and doc["lab"] == "Тест-Лаб"
    page = site.get(f"/m/{mid}/docs/{doc_id}").text
    assert "Сверь с бланком" in page and 'value="105"' in page and 'value="45,5"' in page and "отрицательно" in page

    # Светлана поправляет значение и добавляет строку руками
    form = {"csrf": csrf(site), "taken_on": "2026-09-01", "lab": "Тест-Лаб",
            "name": ["Гемоглобин", "Ферритин", "Антитела к ВИЧ", "Глюкоза"],
            "value": ["104", "45,5", "отрицательно", "5,1"], "unit": ["г/л", "мкг/л", "", "ммоль/л"],
            "low": ["120", "13", "", "3,9"], "high": ["140", "150", "", "6,1"], "ref_text": ["", "", "", ""]}
    assert site.post(f"/m/{mid}/docs/{doc_id}/save", data=form).status_code == 303
    rows = {r["name"]: r for r in db.rows("SELECT * FROM results WHERE doc_id = ?", (doc_id,))}
    assert rows["Гемоглобин"]["value"] == 104 and rows["Ферритин"]["value"] == 45.5
    assert rows["Антитела к ВИЧ"]["value_text"] == "отрицательно" and rows["Глюкоза"]["low"] == 3.9

    second = upload(site, mid, FAKE_HB="128", FAKE_DATE="2026-10-15")
    assert wait_parsed(second)["state"] == "review"
    form.update(taken_on="2026-10-15", value=["128", "60", "отрицательно", "4,8"])
    site.post(f"/m/{mid}/docs/{second}/save", data=form)

    page = site.get(f"/m/{mid}").text
    assert "Гемоглобин" in page and "2 изм." in page
    chart = site.get(f"/m/{mid}/chart", params={"key": "гемоглобин"}).text
    assert chart.count('<circle class="pt out"') == 1 and chart.count('<circle class="pt"') == 1
    assert 'class="norm"' in chart and "01.09.26" in chart and "15.10.26" in chart

    # Файл бланка — только своим
    assert site.get(f"/m/{mid}/docs/{doc_id}/file").headers["content-type"] == "image/jpeg"


def test_lab_flags_on_home(site):
    mid = add_member(site, "Флаги")
    doc_id = upload(site, mid, FAKE_HB="100", FAKE_DATE="2026-08-01")
    wait_parsed(doc_id)
    form = {"csrf": csrf(site), "taken_on": "2026-08-01", "lab": "", "name": ["Гемоглобин"], "value": ["100"],
            "unit": ["г/л"], "low": ["120"], "high": ["140"], "ref_text": [""]}
    site.post(f"/m/{mid}/docs/{doc_id}/save", data=form)
    home = site.get("/").text
    assert re.search(r"Флаги</span>.*?Вне нормы: 1", home, re.S)


def test_lab_empty_parse_and_manual(site):
    mid = add_member(site, "Пустой бланк")
    doc_id = upload(site, mid, FAKE_MODE="empty")
    doc = wait_parsed(doc_id)
    assert doc["state"] == "error" and "вручную" in doc["error"]
    os.environ["FAKE_MODE"] = "ok"
    page = site.get(f"/m/{mid}/docs/{doc_id}").text
    assert "Разобрать ещё раз" in page and page.count('name="name"') == 8


def test_member_cannot_see_others_files(site):
    own = add_member(site, "Свой")
    other = add_member(site, "Чужой")
    doc_id = upload(site, other, FAKE_MODE="ok")
    wait_parsed(doc_id)
    m, _ = join(invite(site, own), "svoy")
    assert m.get(f"/m/{other}/docs/{doc_id}/file").status_code == 404
    assert m.get(f"/m/{own}/docs/{doc_id}/file").status_code == 404     # чужой бланк под своим номером
    assert m.get(f"/m/{other}/chart", params={"key": "гемоглобин"}).status_code == 404


def test_bad_upload_rejected(site):
    mid = add_member(site, "Не бланк")
    r = site.post(f"/m/{mid}/docs", data={"csrf": csrf(site)},
                  files={"blank": ("x.html", b"<script>alert(1)</script>", "text/html")})
    assert r.status_code == 400
    assert not db.rows("SELECT id FROM docs WHERE member_id = ?", (mid,))


def test_delete_member_removes_files(site):
    mid = add_member(site, "Удаляемый")
    doc_id = upload(site, mid, FAKE_MODE="ok")
    wait_parsed(doc_id)
    path = config.FILES_DIR / db.one("SELECT file FROM docs WHERE id = ?", (doc_id,))["file"]
    assert path.exists()
    site.post(f"/m/{mid}/delete", data={"sure": "да", "csrf": csrf(site)})
    assert not path.exists() and site.get(f"/m/{mid}").status_code == 404


# ── 5. Как приложение ────────────────────────────────────────────────────

def test_app_manifest_and_icons(site):
    c = new_client()
    man = c.get("/manifest.webmanifest").json()
    assert man["display"] == "standalone" and man["short_name"] == "Здоровье"
    for icon in man["icons"]:
        assert c.get(icon["src"]).status_code == 200
    assert c.get("/static/icon-180.png").status_code == 200
    sw = c.get("/sw.js")
    assert sw.status_code == 200 and "caches" not in sw.text
    assert 'rel="manifest"' in c.get("/login").text


# ── 6. Копии ─────────────────────────────────────────────────────────────

def kopiya(*args) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(ROOT / "tools/kopiya.py"), *args], capture_output=True,
                          text=True, env=os.environ.copy(), cwd=ROOT)


def test_backup_encrypt_and_open(site):
    add_member(site, "Для копии")
    r = kopiya("klyuch")
    assert r.returncode == 0, r.stderr
    key = TMP / "klyuch.asc"
    # Ключ скачивается со страницы «Доступы» один раз
    assert "Скачать ключ" in site.get("/access").text
    key.write_bytes(site.get("/kopii/klyuch").content)
    assert b"PRIVATE KEY" in key.read_bytes()
    assert kopiya("sdelat").returncode == 0
    copies = sorted((TMP / "kopii").glob("zdorovye-*.tar.gpg"))
    assert copies and b"zdorovye.db" not in copies[-1].read_bytes()      # внутри не прочитать
    r = kopiya("proverit", str(key), str(copies[-1]))
    assert r.returncode == 0 and "база ok" in r.stdout, r.stderr
    # Без ключа не открывается
    empty = TMP / "pustoy-gnupg"
    empty.mkdir(mode=0o700, exist_ok=True)
    r = subprocess.run(["gpg", "--homedir", str(empty), "--batch", "--decrypt", str(copies[-1])], capture_output=True)
    assert r.returncode != 0
    # Светлана подтвердила — ключа на сервере нет
    site.post("/kopii/klyuch/ubrat", data={"sure": "да", "csrf": csrf(site)})
    assert not config.KEY_FILE.exists() and site.get("/kopii/klyuch").status_code == 404
    assert "Последняя копия" in site.get("/access").text


def test_new_setup_link_cannot_take_over(site):
    """Даже если кто-то создаст новую ссылку настройки, второй хозяйки не будет."""
    token = setup_link()
    assert new_client().get(f"/setup/{token}").status_code == 303
    assert db.one("SELECT count(*) AS n FROM users WHERE role = 'owner'")["n"] == 1
    db.run("DELETE FROM setup")
