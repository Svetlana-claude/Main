"""Проверки этапа 7: устройства VPN и ночная проверка безопасности."""
import json
import os
import shutil
import time
from pathlib import Path

import pytest

from common import client, inside  # noqa: F401
from test_chat import csrf_of

from app import sec

VPN_DB = Path(os.environ["FAKE_VPN_DB"])
SEC_DIR = Path(os.environ["FAKE_SEC_STATE"])


@pytest.fixture(autouse=True)
def clean():
    VPN_DB.write_text(json.dumps({"phone": {"ip": "10.8.0.3", "rx": 2048, "tx": 4096,
                                            "shake": int(time.time()) - 3 * 86400}}))
    shutil.rmtree(SEC_DIR, ignore_errors=True)
    sec.STATE.update(what=None, error="")
    yield
    sec.STATE.update(what=None, error="")


def wait_sec(c, timeout=20.0) -> dict:
    end = time.time() + timeout
    while time.time() < end:
        state = c.get("/security/state").json()
        if not state["what"]:
            return state
        time.sleep(0.1)
    raise AssertionError("проверка не кончилась")


def test_closed_without_login(client):
    for path in ("/vpn", "/vpn/d/phone", "/security", "/security/report/2026-01-01"):
        r = client.get(path, follow_redirects=False)
        assert r.status_code == 303 and "login" in r.headers["location"]
    assert client.get("/vpn/d/phone/file").status_code == 403
    assert client.get("/vpn/d/phone/qr.svg").status_code == 403
    assert client.get("/security/state").status_code == 403
    assert client.post("/security/check", data={"csrf": "x"}).status_code == 403
    assert client.post("/vpn/new", data={"name": "x", "csrf": "x"}, follow_redirects=False).status_code == 303
    assert "x" not in json.loads(VPN_DB.read_text())


def test_vpn_list_add_and_file(inside):
    page = inside.get("/vpn").text
    assert "phone" in page and "подключалось 3 дн назад" in page and "получено 2,0 КБ" in page
    # Подделка формы не заводит устройство
    inside.post("/vpn/new", data={"name": "чужое", "csrf": "подделка"})
    assert list(json.loads(VPN_DB.read_text())) == ["phone"]
    r = inside.post("/vpn/new", data={"name": "Планшет мамы", "csrf": csrf_of(inside)}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith("/vpn/d/planshet-mamy?new=1")
    page = inside.get("/vpn/d/planshet-mamy?new=1")
    assert "Устройство заведено" in page.text and "no-store" in page.headers["cache-control"]
    f = inside.get("/vpn/d/planshet-mamy/file")
    assert f.status_code == 200 and "fake-secret-planshet-mamy" in f.text
    assert "no-store" in f.headers["cache-control"] and "attachment" in f.headers["content-disposition"]
    qr = inside.get("/vpn/d/planshet-mamy/qr.svg")
    assert qr.status_code == 200 and qr.headers["content-type"].startswith("image/svg") and "<svg" in qr.text
    assert "no-store" in qr.headers["cache-control"]
    # Секрет не попадает на саму страницу
    assert "fake-secret" not in page.text and "fake-secret" not in inside.get("/vpn").text
    # То же имя второй раз — нет
    page = inside.post("/vpn/new", data={"name": "планшет мамы", "csrf": csrf_of(inside)}).text
    assert "уже есть" in page
    page = inside.post("/vpn/new", data={"name": "!!!", "csrf": csrf_of(inside)}).text
    assert "Напиши имя устройства" in page


def test_vpn_bad_names_and_remove(inside):
    assert "fake-secret" not in inside.get("/vpn/d/..%2Fphone/file").text
    assert inside.get("/vpn/d/-rf/file").status_code == 404
    assert inside.get("/vpn/d/nobody", follow_redirects=False).status_code == 303
    inside.post("/vpn/d/phone/remove", data={"csrf": "подделка"})
    assert "phone" in json.loads(VPN_DB.read_text())
    r = inside.post("/vpn/d/phone/remove", data={"csrf": csrf_of(inside)}, follow_redirects=False)
    assert r.headers["location"].endswith("/vpn?done=phone")
    assert json.loads(VPN_DB.read_text()) == {}
    assert "отозвано" in inside.get("/vpn?done=phone").text
    assert inside.get("/vpn/d/phone/file").status_code == 404


def test_vpn_wrapper_error_is_shown(inside):
    VPN_DB.write_text("испорчено")
    assert "Не получилось" in inside.get("/vpn").text


def test_security_without_reports(inside):
    page = inside.get("/security").text
    assert "Отчётов пока нет" in page
    assert 'id="sec-count"' in page and ">!</span>" in page


def test_security_check_and_approve(inside):
    r = inside.post("/security/check", data={"csrf": csrf_of(inside)})
    assert r.status_code == 200
    state = wait_sec(inside)
    assert state["error"] == ""
    assert (SEC_DIR / "runs.log").read_text().split() == ["REMEDIATE=0"]   # по кнопке — без исправлений
    page = inside.get("/security").text
    assert "Что слушает сеть" in page and "tcp 0.0.0.0:4444" in page
    assert "порт 4444</strong> — неизвестно что" in page and "порт 22</strong> — вход на сервер" in page
    assert "8002" not in page.split("Что открыто наружу")[1].split("Кто может войти")[0]
    assert "mokeeva" in page and "glavpryg" not in page.split("Кто может войти")[1].split("Отчёты")[0]
    assert "заблокировано подборщиков: 7" in page and "по Москве" in page
    assert "Ключей для входа: 1;" in page and "built-in" not in page
    assert "Так и должно быть" in page
    assert '<span class="badge" id="sec-count"' in page and ">2</span>" in page
    # Отчёт: время в её поясе, HTML из файла не проходит, снимок свёрнут
    day = time.strftime("%Y-%m-%d")
    rep = inside.get(f"/security/report/{day}").text
    assert "00:00 UTC" not in rep and "по Москве" in rep
    assert "<b>" not in rep and "&lt;b&gt;" in rep and "Полный снимок состояния" in rep
    # Принять нормой
    inside.post("/security/approve", data={"csrf": "подделка"})
    assert not (SEC_DIR / "approved").exists()
    inside.post("/security/approve", data={"csrf": csrf_of(inside)})
    assert wait_sec(inside)["error"] == ""
    page = inside.get("/security").text
    assert "Ничего не поменялось" in page and "Так и должно быть" not in page
    assert 'id="sec-count" title="Изменений с прошлой нормы" hidden' in page


def test_security_failure_is_shown(inside):
    SEC_DIR.mkdir(parents=True, exist_ok=True)
    (SEC_DIR / "fail").write_text("")
    inside.post("/security/check", data={"csrf": csrf_of(inside)})
    state = wait_sec(inside)
    assert "нужен пароль" in state["error"]
    assert "нужен пароль" in inside.get("/security").text
    assert inside.get("/security/report/../../etc", follow_redirects=False).status_code in (303, 404)


def test_stale_report_warns(inside):
    inside.post("/security/check", data={"csrf": csrf_of(inside)})
    wait_sec(inside)
    old = time.time() - 3 * 86400
    for p in (SEC_DIR / "reports").iterdir():
        os.utime(p, (old, old))
    page = inside.get("/security").text
    assert "Свежего отчёта нет" in page and ">!</span>" in page
