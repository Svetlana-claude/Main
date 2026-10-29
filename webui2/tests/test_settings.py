"""Проверки настроек: часовой пояс, перезапуск с ожиданием, нагрузка."""
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from common import TMP, client, db, inside  # noqa: F401
from test_chat import csrf_of, send, wait_idle

from app import power

POWER_LOG = Path(os.environ["FAKE_POWER_LOG"])


@pytest.fixture(autouse=True)
def clean():
    POWER_LOG.unlink(missing_ok=True)
    Path(str(POWER_LOG) + ".fail").unlink(missing_ok=True)
    power.STATE.update(what=None, phase="", error="")
    yield
    power.STATE.update(what=None, phase="", error="")


def new_chat(c) -> int:
    r = c.post("/chat/new", data={"csrf": csrf_of(c)}, follow_redirects=False)
    return int(r.headers["location"].rsplit("/", 1)[1])


def wait_power(c, check, timeout=15.0) -> dict:
    end = time.time() + timeout
    while time.time() < end:
        state = c.get("/settings/power").json()
        if check(state):
            return state
        time.sleep(0.1)
    raise AssertionError(f"не дождался: {state}")


def test_closed_without_login(client):
    assert client.get("/settings/power").status_code == 403
    assert client.get("/settings/load").status_code == 403
    assert client.post("/settings/power/site", data={"csrf": "x"}).status_code == 403
    assert not POWER_LOG.exists()


def test_timezone(inside):
    conv = new_chat(inside)
    send(inside, conv, "который час")
    wait_idle(inside, conv)
    assert "по Москве" in inside.get(f"/chat/{conv}").text
    inside.post("/settings/timezone", data={"zone_id": "Asia/Novosibirsk", "csrf": "подделка"})
    assert "по Москве" in inside.get(f"/chat/{conv}").text
    inside.post("/settings/timezone", data={"zone_id": "Mars/Base", "csrf": csrf_of(inside)})
    assert "по Москве" in inside.get(f"/chat/{conv}").text
    r = inside.post("/settings/timezone", data={"zone_id": "Asia/Novosibirsk", "csrf": csrf_of(inside)},
                    follow_redirects=False)
    assert r.status_code == 303
    page = inside.get(f"/chat/{conv}").text
    assert "по Новосибирску" in page and "по Москве" not in page
    # Время сдвинуто на 4 часа от московского
    stamp = db.one("SELECT created_at FROM messages WHERE conv_id = ? LIMIT 1", (conv,))["created_at"]
    novosib = datetime.fromisoformat(stamp) + timedelta(hours=7)
    assert f"{novosib:%H:%M} по Новосибирску" in page
    assert 'value="Asia/Novosibirsk" selected' in inside.get("/settings").text


def test_restart_right_away(inside):
    r = inside.post("/settings/power/site", data={"csrf": csrf_of(inside)})
    assert r.json()["what"] == "site"
    state = wait_power(inside, lambda s: s["phase"] == "going")
    assert state["boot"] == power.BOOT
    end = time.time() + 5
    while not POWER_LOG.exists() and time.time() < end:
        time.sleep(0.05)
    assert POWER_LOG.read_text().split() == ["restart-site"]
    # Второй раз не начинается, пока идёт первый
    assert inside.post("/settings/power/server", data={"csrf": csrf_of(inside)}).status_code == 409


def test_waits_for_answers_and_blocks_new_ones(inside):
    conv, other = new_chat(inside), None
    send(inside, conv, "медленно расскажи сказку")
    inside.post("/settings/power/server", data={"csrf": csrf_of(inside)})
    state = wait_power(inside, lambda s: s["phase"] == "waiting")
    assert state["runs"] == 1
    assert "Перезагрузить сервер" in inside.get("/settings").text
    other = new_chat(inside)
    r = inside.post(f"/chat/{other}/send", data={"text": "привет", "csrf": csrf_of(inside)})
    assert r.status_code == 409 and "перезапуска" in r.json()["error"]
    assert not POWER_LOG.exists()
    wait_idle(inside, conv)
    wait_power(inside, lambda s: s["phase"] == "going")
    end = time.time() + 5
    while not POWER_LOG.exists() and time.time() < end:
        time.sleep(0.05)
    assert POWER_LOG.read_text().split() == ["reboot"]


def test_cancel_while_waiting(inside):
    conv = new_chat(inside)
    send(inside, conv, "медленно ещё сказку")
    inside.post("/settings/power/site", data={"csrf": csrf_of(inside)})
    wait_power(inside, lambda s: s["phase"] == "waiting")
    state = inside.post("/settings/power/cancel", data={"csrf": csrf_of(inside)}).json()
    assert state["what"] is None
    wait_idle(inside, conv)
    time.sleep(1.5)
    assert not POWER_LOG.exists()
    send(inside, conv, "снова можно")
    wait_idle(inside, conv)


def test_command_failure_is_shown(inside):
    Path(str(POWER_LOG) + ".fail").write_text("")
    inside.post("/settings/power/site", data={"csrf": csrf_of(inside)})
    state = wait_power(inside, lambda s: s["error"])
    assert state["what"] is None and "нет прав" in state["error"]
    assert "нет прав" in inside.get("/settings").text


def test_load_now_and_day_chart(inside):
    now = inside.get("/settings/load").json()
    for key in ("cpu", "mem", "disk"):
        assert 0 <= now[key] <= 100
    assert " ГБ из " in now["mem_text"]
    assert "Замеров пока нет" in inside.get("/settings").text
    start = datetime.now(timezone.utc) - timedelta(hours=3)
    rows = [(start + timedelta(minutes=i), 10 + i, 40, 55) for i in range(5)]
    rows += [(start + timedelta(hours=1, minutes=i), 30, 41, 55) for i in range(5)]   # после перерыва
    rows += [(start - timedelta(hours=30), 99, 99, 99)]                                  # старше суток
    for at, cpu, mem, dsk in rows:
        db.run("INSERT INTO load_samples (at, cpu, mem, disk) VALUES (?, ?, ?, ?)", (at.isoformat(), cpu, mem, dsk))
    page = inside.get("/settings").text
    assert page.count('class="series"') == 6            # три графика, у каждого — два куска
    assert "Таблицей по часам" in page and "99" not in re.sub(r"<svg.*?</svg>", "", page, flags=re.S).split("Таблицей")[1]
    assert re.search(r'id="load-cpu">\d+ %<', page)
