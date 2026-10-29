"""Проверки разрешений и кружков на временной базе с подставным Claude."""
import re
import shutil
import time

import pytest

from common import TMP, client, db, inside  # noqa: F401
from test_chat import csrf_of, send, wait_idle
from test_projects import new_project, new_topic

from app import perms


@pytest.fixture(autouse=True)
def clean():
    shutil.rmtree(TMP / "projects", ignore_errors=True)
    db.run("DELETE FROM permissions")
    yield


def wait_ask(c, state="wait", timeout=10.0) -> dict:
    end = time.time() + timeout
    while time.time() < end:
        row = db.one("SELECT * FROM permissions ORDER BY id DESC LIMIT 1")
        if row and row["state"] == state:
            return row
        time.sleep(0.05)
    raise AssertionError(f"нет запроса в состоянии {state}")


def topic(c) -> tuple[int, int]:
    pid = new_project(c, "Разрешения")
    return pid, new_topic(c, pid)


def test_permissions_page_closed_without_login(client):
    for path in ("/permissions", "/lights"):
        r = client.get(path, follow_redirects=False)
        assert r.status_code in (303, 403), path
    r = client.post("/permissions/1/yes", data={"csrf": "x"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith("/login")


def test_allow(inside):
    pid, conv = topic(inside)
    send(inside, conv, "спроси про команду")
    ask = wait_ask(inside)
    assert ask["what"] == "Выполнить команду" and ask["detail"] == "curl -s https://example.com"
    assert ask["place"] == "Разрешения · спроси про команду" and ask["project_id"] == pid
    # Кружки и щит: тема и проект ждут разрешения
    lights = inside.get("/lights").json()
    assert lights["ask"] == 1 and lights["c"] == {str(conv): "wait"} and lights["p"] == {str(pid): "wait"}
    page = inside.get("/permissions").text
    assert "curl -s https://example.com" in page and "Разрешить" in page
    assert re.search(r'id="ask-count"[^>]*>1<', page)
    assert 'class="light wait" data-c="%d"' % conv in inside.get(f"/projects/{pid}/t/{conv}").text
    # Чужая форма без ключа — не решает
    inside.post(f"/permissions/{ask['id']}/yes", data={"csrf": "подделка"})
    assert db.one("SELECT state FROM permissions WHERE id = ?", (ask["id"],))["state"] == "wait"
    r = inside.post(f"/permissions/{ask['id']}/yes", data={"csrf": csrf_of(inside)}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith("/permissions")
    rows = wait_idle(inside, conv)
    assert "— разрешили" in rows[-1]["text"]
    assert db.one("SELECT state FROM permissions WHERE id = ?", (ask["id"],))["state"] == "yes"
    assert inside.get("/lights").json() == {"ask": 0, "c": {}, "p": {}}
    page = inside.get("/permissions").text
    assert "Сейчас никто не ждёт" in page and "разрешено" in page
    # Повторный ответ на закрытый вопрос ничего не меняет
    inside.post(f"/permissions/{ask['id']}/no", data={"csrf": csrf_of(inside)})
    assert db.one("SELECT state FROM permissions WHERE id = ?", (ask["id"],))["state"] == "yes"


def test_deny(inside):
    _, conv = topic(inside)
    send(inside, conv, "спроси ещё")
    ask = wait_ask(inside)
    inside.post(f"/permissions/{ask['id']}/no", data={"csrf": csrf_of(inside)})
    rows = wait_idle(inside, conv)
    assert "отказ: " + perms.DENIED in rows[-1]["text"]
    assert "запрещено" in inside.get("/permissions").text


def test_no_answer_is_refusal(inside, monkeypatch):
    monkeypatch.setattr(perms, "WAIT_SEC", 0.5)
    _, conv = topic(inside)
    send(inside, conv, "спроси и жди")
    rows = wait_idle(inside, conv)
    assert "отказ: " + perms.LATE in rows[-1]["text"]
    assert wait_ask(inside, "late")


def test_claude_withdraws_question(inside):
    _, conv = topic(inside)
    send(inside, conv, "передумай")
    rows = wait_idle(inside, conv)
    assert "(передумал)" in rows[-1]["text"]
    assert wait_ask(inside, "gone")


def test_deleting_topic_drops_question(inside):
    pid, conv = topic(inside)
    send(inside, conv, "спроси и брось")
    wait_ask(inside)
    inside.post(f"/chat/{conv}/delete", data={"csrf": csrf_of(inside)})
    ask = wait_ask(inside, "gone")
    page = inside.get("/permissions").text
    assert "ответ оборвался" in page and ask["place"] in page
    assert inside.get("/lights").json()["ask"] == 0


def test_chat_light_while_running(inside):
    r = inside.post("/chat/new", data={"csrf": csrf_of(inside)}, follow_redirects=False)
    conv = int(r.headers["location"].rsplit("/", 1)[1])
    send(inside, conv, "медленно расскажи")
    assert inside.get("/lights").json()["c"] == {str(conv): "busy"}
    assert 'class="light busy" data-c="%d"' % conv in inside.get(f"/chat/{conv}").text
    wait_idle(inside, conv)
    assert 'class="light free" data-c="%d"' % conv in inside.get(f"/chat/{conv}").text
