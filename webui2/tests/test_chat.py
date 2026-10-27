"""Проверки чата на временной базе с подставным Claude."""
import json
import time

from common import CLAUDE_LOG, client, db, hidden, inside  # noqa: F401


def new_conv(c) -> int:
    csrf = hidden(c.get("/settings").text, "csrf")
    r = c.post("/chat/new", data={"csrf": csrf}, follow_redirects=False)
    assert r.status_code == 303
    return int(r.headers["location"].rstrip("/").rsplit("/", 1)[1])


def csrf_of(c) -> str:
    return hidden(c.get("/settings").text, "csrf")


def send(c, conv: int, text: str) -> dict:
    r = c.post(f"/chat/{conv}/send", data={"text": text, "csrf": csrf_of(c)})
    assert r.status_code == 200, r.text
    return r.json()


def wait_idle(c, conv: int, timeout: float = 20) -> list[dict]:
    end = time.time() + timeout
    while time.time() < end:
        if not c.get(f"/chat/{conv}/feed").json()["running"]:
            return db.rows("SELECT role, text FROM messages WHERE conv_id = ? ORDER BY id", (conv,))
        time.sleep(0.1)
    raise AssertionError("ответ не закончился")


def test_chat_closed_without_login(client):
    assert client.get("/chat", follow_redirects=False).status_code == 303
    assert client.get("/chat/1/feed").status_code == 403
    assert client.get("/chat/1/stream").status_code == 403
    assert client.post("/chat/1/send", data={"text": "привет"}).status_code == 403


def test_empty_chat_then_last_conversation_opens(inside):
    assert "Разговоров пока нет" in inside.get("/chat").text
    first = new_conv(inside)
    send(inside, first, "раз")
    wait_idle(inside, first)
    second = new_conv(inside)
    send(inside, second, "два")
    wait_idle(inside, second)
    r = inside.get("/chat", follow_redirects=False)
    assert r.headers["location"].endswith(f"/chat/{second}")


def test_send_answer_title_markdown(inside):
    conv = new_conv(inside)
    assert send(inside, conv, "Как дела у кота Барсика сегодня вечером, расскажи подробно пожалуйста")["mode"] == "new"
    rows = wait_idle(inside, conv)
    assert [r["role"] for r in rows] == ["user", "assistant"]
    row = db.one("SELECT * FROM conversations WHERE id = ?", (conv,))
    assert row["title"].startswith("Как дела у кота Барсика") and row["title"].endswith("…")
    assert len(row["title"]) <= 61
    assert row["model"] == "sonnet" and row["session_id"] and row["context_tokens"] == 4200
    html = inside.get(f"/chat/{conv}").text
    assert "<strong>Ответ:</strong>" in html and "<table>" in html
    assert "<script>alert" not in html and "&lt;script&gt;alert" in html
    assert "вес: <span id=\"weight\">4 тыс.</span>" in html


def test_claude_runs_bare_and_resumes(inside):
    CLAUDE_LOG.write_text("")
    conv = new_conv(inside)
    send(inside, conv, "первое")
    wait_idle(inside, conv)
    send(inside, conv, "второе")
    wait_idle(inside, conv)
    runs = [json.loads(line) for line in CLAUDE_LOG.read_text().splitlines()]
    assert len(runs) == 2
    first, second = runs
    for flag in ("--disable-slash-commands", "--strict-mcp-config"):
        assert flag in first["argv"]
    assert first["argv"][first["argv"].index("--tools") + 1] == ""
    assert first["argv"][first["argv"].index("--setting-sources") + 1] == ""
    assert first["argv"][first["argv"].index("--model") + 1] == "sonnet"
    assert "--resume" not in first["argv"]
    session = db.one("SELECT session_id FROM conversations WHERE id = ?", (conv,))["session_id"]
    assert second["argv"][second["argv"].index("--resume") + 1] == session
    assert first["cwd"].endswith("/room")
    assert not [k for k in first["env"] if k.startswith("WEBUI2_") or k == "SECRET_KEY"]


def test_append_goes_into_running_answer(inside):
    CLAUDE_LOG.write_text("")
    conv = new_conv(inside)
    send(inside, conv, "медленно отвечай")
    time.sleep(0.5)
    assert send(inside, conv, "дописка про чай")["mode"] == "append"
    # Пока идёт ответ, дописка видна на странице
    assert "дописка про чай" in inside.get(f"/chat/{conv}/feed").json()["html"]
    rows = wait_idle(inside, conv, timeout=60)
    assert [r["role"] for r in rows] == ["user", "assistant", "user", "assistant"]
    assert rows[2]["text"] == "дописка про чай" and "дописка про чай" in rows[3]["text"]
    assert len(CLAUDE_LOG.read_text().splitlines()) == 1     # один запуск на обе


def test_stream_gives_live_text(inside):
    conv = new_conv(inside)
    send(inside, conv, "медленно")
    seen = []
    with inside.stream("GET", f"/chat/{conv}/stream") as r:
        for line in r.iter_lines():
            if line.startswith("data: "):
                ev = json.loads(line[6:])
                seen.append(ev["t"])
                if ev["t"] == "done":
                    break
    assert seen[0] == "snapshot" and "delta" in seen and "saved" in seen and seen[-1] == "done"


def test_error_answer_saved(inside):
    conv = new_conv(inside)
    send(inside, conv, "ошибка")
    rows = wait_idle(inside, conv)
    assert rows[-1]["role"] == "error"


def test_model_rename_delete(inside):
    conv = new_conv(inside)
    send(inside, conv, "привет")
    wait_idle(inside, conv)
    csrf = csrf_of(inside)
    inside.post(f"/chat/{conv}/model", data={"model": "opus", "csrf": csrf})
    inside.post(f"/chat/{conv}/model", data={"model": "gpt", "csrf": csrf})
    assert db.one("SELECT model FROM conversations WHERE id = ?", (conv,))["model"] == "opus"
    inside.post(f"/chat/{conv}/rename", data={"title": "  Про   кота ", "csrf": csrf})
    assert db.one("SELECT title FROM conversations WHERE id = ?", (conv,))["title"] == "Про кота"
    # Без токена ничего не меняется
    inside.post(f"/chat/{conv}/delete", data={"csrf": "чужой"})
    assert db.one("SELECT id FROM conversations WHERE id = ?", (conv,))
    inside.post(f"/chat/{conv}/delete", data={"csrf": csrf})
    assert db.one("SELECT id FROM conversations WHERE id = ?", (conv,)) is None
    assert db.one("SELECT count(*) AS n FROM messages WHERE conv_id = ?", (conv,))["n"] == 0


def test_empty_conversations_do_not_pile_up(inside):
    new_conv(inside)
    new_conv(inside)
    new_conv(inside)
    assert db.one("SELECT count(*) AS n FROM conversations")["n"] == 1


def test_last_40_and_show_earlier(inside):
    conv = new_conv(inside)
    for i in range(45):
        db.run("INSERT INTO messages (conv_id, role, text, norm, created_at) VALUES (?, 'user', ?, ?, ?)",
               (conv, f"сообщение-{i:02d}", f"сообщение-{i:02d}", db.now()))
    html = inside.get(f"/chat/{conv}").text
    assert "сообщение-05" in html and "сообщение-04" not in html and "Показать раньше" in html
    html = inside.get(f"/chat/{conv}?n=80").text
    assert "сообщение-00" in html and "Показать раньше" not in html


def test_search_case_and_yo(inside):
    conv = new_conv(inside)
    send(inside, conv, "Ёжик пошёл в ЛЕС за грибами")
    wait_idle(inside, conv)
    html = inside.get("/search", params={"q": "ежик лес"}).text
    assert "Найдено: 2" in html          # сообщение и ответ-эхо
    assert "Ничего не нашлось" in inside.get("/search", params={"q": "ежик море"}).text


def test_big_quiet_conversation_hint(inside):
    conv = new_conv(inside)
    send(inside, conv, "привет")
    wait_idle(inside, conv)
    db.run("UPDATE conversations SET context_tokens = 200000, updated_at = '2026-01-01T00:00:00+00:00' WHERE id = ?",
           (conv,))
    assert "дешевле начать новый разговор" in inside.get(f"/chat/{conv}").text
