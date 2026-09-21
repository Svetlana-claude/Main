"""Проверка входа Claude из веб-интерфейса («Настройки» → «Вход Claude»).

Места, где это ломается незаметно:

* ссылка вынимается из вывода не целиком — claude.com открывается, но вход
  не проходит, и понять почему нельзя;
* код не доходит до команды (без псевдотерминала `claude auth login` его не
  спрашивает) — кнопка «Подтвердить» висит;
* неверный код выдаётся за удачный вход;
* брошенный вход висит процессом вечно;
* ошибка истёкшего входа в чате остаётся сырой строкой «Failed to
  authenticate», и плашки в шапке нет — о поломке узнают только по ответам.

Настоящий `claude` не запускается: стенд подкладывает поддельный (CLAUDE_BIN),
который печатает ссылку так же, как Claude Code 2.1 — гиперссылкой терминала
OSC 8 и приглашением «Paste code here if prompted >», — и сверяет код. Вход
хозяина не затрагивается. Второй экземпляр приложения — на свободном порту,
со своим пользователем `claude-login-probe`, всё убирается за собой.

Запуск:  .venv/bin/python tests/check_claude_login.py
"""
import asyncio
import os
import re
import socket
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PROJECT_DIR = Path(__file__).resolve().parent.parent
FAILED: list[str] = []
LOGIN = "claude-login-probe"
PASSWORD = "стенд-входа-claude-2026"
GOOD_CODE = "Zx9Kq2LmN8pR4tV6#state-abc123"
URL = ("https://claude.com/cai/oauth/authorize?code=true&client_id=probe"
       "&redirect_uri=https%3A%2F%2Fplatform.claude.com%2Foauth%2Fcode%2Fcallback"
       "&scope=user%3Ainference+user%3Aprofile&code_challenge=AbC-dEf_123"
       "&code_challenge_method=S256&state=state-abc123")
AUTH_ERROR = "Failed to authenticate: OAuth session expired and could not be refreshed"

# Поддельный claude. Ведёт себя как настоящий в тех местах, на которые
# опирается приложение; `-p` отвечает ошибкой входа, пока есть файл-метка.
FAKE = r'''#!/usr/bin/env python3
import json, os, sys, time
args = sys.argv[1:]
flag = os.environ["FAKE_CLAUDE_FAIL_FLAG"]
if args[:2] == ["auth", "status"]:
    print(json.dumps({"loggedIn": True, "authMethod": "claude.ai",
                      "email": "probe@example.com", "subscriptionType": "pro"}))
    sys.exit(0)
if args[:2] == ["auth", "login"]:
    if not os.isatty(0):
        print("не терминал: код спрашивать не буду"); sys.exit(1)
    url = os.environ["FAKE_CLAUDE_URL"]
    # Как у Claude Code 2.1: гиперссылка OSC 8 с тем же адресом в видимом тексте,
    # и всё — кусками, чтобы адрес приходил не одним чтением.
    out = ("Opening browser to sign in…\r\nIf the browser didn't open, visit: "
           "\x1b]8;;" + url + "\x1b\\" + url + "\x1b]8;;\x1b\\\r\n")
    for i in range(0, len(out), 40):
        sys.stdout.write(out[i:i + 40]); sys.stdout.flush(); time.sleep(0.01)
    while True:
        sys.stdout.write("Paste code here if prompted > "); sys.stdout.flush()
        code = sys.stdin.readline().strip()
        if code == os.environ["FAKE_CLAUDE_CODE"]:
            try: os.unlink(flag)
            except FileNotFoundError: pass
            print("\r\nLogin successful."); sys.exit(0)
        print("\r\nOAuth error: Invalid code")
if "-p" in args:
    prompt = args[args.index("-p") + 1]
    stream = "stream-json" in args
    if os.path.exists(flag):
        if stream and "ЧЕРЕЗ-ИТОГ" in prompt:
            print(json.dumps({"type": "result", "is_error": True, "result": os.environ["FAKE_CLAUDE_ERR"]}))
            sys.exit(1)
        sys.stderr.write(os.environ["FAKE_CLAUDE_ERR"] + "\n"); sys.exit(1)
    if stream:
        print(json.dumps({"type": "result", "is_error": False, "result": "работает",
                          "session_id": "probe", "usage": {}}))
    else:
        print("работает")
    sys.exit(0)
sys.exit(2)
'''


def check(ok: bool, what: str) -> None:
    if ok:
        print(f"  ok: {what}")
    else:
        FAILED.append(what)
        print(f"  ПРОВАЛ: {what}")


def pids_of(bin_path: str) -> list[int]:
    """Живые процессы поддельного claude — по /proc, а не pgrep (см. CLAUDE.md, 13)."""
    found = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            cmd = (entry / "cmdline").read_bytes().split(b"\0")
            state = (entry / "stat").read_text().split()[2]
        except OSError:
            continue
        if state != "Z" and any(part.decode(errors="replace") == bin_path for part in cmd):
            found.append(int(entry.name))
    return found


# ── Разбор строк ─────────────────────────────────────────────────────

def check_pure() -> None:
    from app.services import claude_auth as ca

    check(ca.is_auth_error(AUTH_ERROR), "строка 21.09.2026 распознаётся как ошибка входа")
    check(not ca.is_auth_error("You've hit your limit · resets 9:50am (UTC)"),
          "исчерпанный лимит за ошибку входа не принимается")
    check(not ca.is_auth_error(None) and not ca.is_auth_error(""), "пустая строка — не ошибка входа")
    check(ca.explain(AUTH_ERROR) == ca.EXPLAIN and ca.explain("иное") == "иное",
          "explain: ошибка входа — словами, прочее как есть")

    raw = ("visit: \x1b]8;;" + URL + "\x1b\\" + URL + "\x1b]8;;\x1b\\\r\nPaste code here if prompted > ")
    check(ca._find_url(raw) == URL, "ссылка из гиперссылки OSC 8 вынимается целиком")
    check(ca._find_url("visit: \x1b]8;;" + URL[:60]) == "",
          "оборванная гиперссылка не выдаётся за ссылку")
    check(ca._find_url("visit: " + URL + "\r\n") == URL, "без OSC 8 — ссылка из видимого текста")
    check("state=" not in ca._tail(type("F", (), {"output": raw})()),
          "в выводе для показа ссылки с параметрами входа нет")


# ── Вход в процессе приложения ───────────────────────────────────────

async def check_flow(bin_path: str) -> None:
    from app import config
    from app.services import claude_auth as ca

    config.CLAUDE_BIN = bin_path

    flow = await ca.start()
    check(flow["state"] == "waiting_code", f"после запуска ждём код (состояние {flow['state']})")
    check(flow["url"] == URL, "ссылка на странице совпадает с выданной командой")
    again = await ca.start()
    check(again["url"] == URL and len(pids_of(bin_path)) == 1,
          "второе нажатие «Войти заново» не плодит второй процесс")

    flow = await ca.submit("abc")
    check(flow["state"] == "waiting_code" and "не похоже" in flow["message"],
          "явно не код — отказ без передачи команде, вход продолжается")

    t0 = time.time()
    ca.FINISH_WAIT_SEC = 3
    flow = await ca.submit("wrong-code-123456#x")
    check(flow["state"] == "failed" and "не приняли" in flow["message"],
          "неверный код — вход не выполнен")
    check(time.time() - t0 < 10, "на неверном коде не висим дольше отведённого")
    await asyncio.sleep(0.3)
    check(not pids_of(bin_path), "после неверного кода процесс входа снят")

    await ca.start()
    flow = await ca.submit("  " + GOOD_CODE[:10] + "\n" + GOOD_CODE[10:] + " ")
    check(flow["state"] == "done", f"верный код (с прилипшими пробелами) — вход выполнен: {flow['message']!r}")
    check("работает" in flow["message"], "после входа прошёл проверочный вызов")
    check(not pids_of(bin_path), "после входа процессов не осталось")

    await ca.start()
    ca._flow.started -= ca.LOGIN_TTL_SEC + 1
    flow = ca.current()
    check(flow["state"] == "failed" and "10 минут" in flow["message"],
          "код не введён вовремя — вход снимается")
    await asyncio.sleep(0.3)
    check(not pids_of(bin_path), "снятый по времени вход не оставляет процесса")

    await ca.start()
    await ca.cancel()
    await asyncio.sleep(0.3)
    check(ca.current() is None and not pids_of(bin_path), "«Отменить» снимает процесс")


# ── Живая страница ───────────────────────────────────────────────────

def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):     # noqa: D401
        return None


def check_live(bin_path: str, env: dict, fail_flag: Path) -> None:
    from app import db, security

    db.execute("DELETE FROM users WHERE login = %s", (LOGIN,))
    uid = db.query_one(
        "INSERT INTO users (login, password_hash, must_change) VALUES (%s, %s, false) RETURNING id",
        (LOGIN, security.hash_password(PASSWORD)),
    )["id"]
    chat_id = db.query_one(
        "INSERT INTO conversations (kind, title) VALUES ('chat', 'стенд входа claude') RETURNING id"
    )["id"]
    db.execute("DELETE FROM login_attempts WHERE ip = '127.0.0.1'")

    port = free_port()
    proc = subprocess.Popen(
        [str(PROJECT_DIR / ".venv/bin/python"), "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=str(PROJECT_DIR), env={**env, "CLAUDE_BIN": bin_path},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    opener = urllib.request.build_opener(NoRedirect)
    cookie = ""

    def call(method: str, path: str, fields: dict | None = None, timeout: int = 60):
        data = urllib.parse.urlencode(fields).encode() if fields is not None else None
        headers = {"Cookie": cookie} if cookie else {}
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data,
                                     headers=headers, method=method)
        try:
            with opener.open(req, timeout=timeout) as res:
                return res.status, res.read().decode("utf-8", "replace"), dict(res.headers)
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", "replace"), dict(exc.headers)

    def wait_run(chat: int) -> None:
        for _ in range(100):
            n = db.query_one("SELECT count(*) AS n FROM messages WHERE conversation_id = %s "
                             "AND role <> 'user'", (chat,))["n"]
            if n:
                return
            time.sleep(0.1)

    try:
        for _ in range(60):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=1):
                    break
            except Exception:                          # noqa: BLE001
                time.sleep(0.5)

        status, _, headers = call("POST", "/login", {"login": LOGIN, "password": PASSWORD})
        cookie = headers.get("set-cookie", "").split(";")[0]
        check(status == 303 and cookie, "стендовый пользователь вошёл в панель")

        status, body, _ = call("GET", "/settings")
        check('/settings/claude"' in body, "в «Настройках» есть переход ко входу Claude")
        check("Войти заново</a>" not in body, "пока вход работает — плашки в шапке нет")

        status, body, headers = call("GET", "/settings/claude")
        check(status == 200 and "probe@example.com" in body, "страница показывает аккаунт")
        check(headers.get("cache-control") == "no-store", "страница входа не кэшируется")

        # Ошибка входа в чате: и событием error (stderr), и итогом с признаком ошибки.
        fail_flag.touch()
        call("POST", f"/chats/{chat_id}/send", {"text": "привет"})
        wait_run(chat_id)
        stored = db.query_one("SELECT content FROM messages WHERE conversation_id = %s "
                              "AND role <> 'user' ORDER BY id DESC LIMIT 1", (chat_id,))
        check(stored and AUTH_ERROR in stored["content"], "в базе ошибка хранится как пришла")
        status, body, _ = call("GET", f"/chats?id={chat_id}")
        check("Вход Claude истёк: Claude Code не смог" in body,
              "в ленте чата ошибка входа объяснена словами")
        check("Failed to authenticate" not in body, "сырая строка ошибки на экран не выходит")
        check('/settings/claude">Войти заново</a>' in body, "в шапке плашка со ссылкой «Войти заново»")
        _, body, _ = call("GET", "/")
        check('/settings/claude">Войти заново</a>' in body, "плашка видна и на других страницах")
        _, body, _ = call("GET", "/settings/claude")
        check("вход истёк" in body, "страница входа показывает «вход истёк»")

        # Нажатия — как в браузере.
        status, _, _ = call("POST", "/settings/claude/start", {})
        _, body, _ = call("GET", "/settings/claude")
        check(URL.replace("&", "&amp;") in body, "после «Войти заново» на странице ссылка claude.com")
        check('name="code"' in body, "и поле для кода")
        status, _, _ = call("POST", "/settings/claude/code", {"code": GOOD_CODE}, timeout=120)
        _, body, _ = call("GET", "/settings/claude")
        check("Вход выполнен, Claude отвечает" in body, "после кода — «Вход выполнен»")
        check("Войти заново</a>" not in body, "после входа плашка в шапке пропала")
        _, body, _ = call("GET", "/settings/claude")
        check("Вход выполнен, Claude отвечает" not in body, "итог входа показывается один раз")

        # Итог с признаком ошибки — второй путь той же ошибки.
        fail_flag.touch()
        call("POST", f"/chats/{chat_id}/send", {"text": "ЧЕРЕЗ-ИТОГ"})
        time.sleep(1.5)
        _, body, _ = call("GET", "/")
        check('/settings/claude">Войти заново</a>' in body,
              "ошибка входа итогом (is_error) тоже ставит плашку")
        fail_flag.unlink(missing_ok=True)
        status, _, _ = call("POST", "/settings/claude/check", {})
        _, body, _ = call("GET", "/")
        check("Войти заново</a>" not in body, "удачная «Проверить» снимает плашку")

        # Без входа в панель — ни страницы, ни запуска.
        cookie = ""
        status, _, _ = call("POST", "/settings/claude/start", {})
        check(status == 303 and not pids_of(bin_path), "без входа в панель вход Claude не запускается")
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        db.execute("DELETE FROM conversations WHERE id = %s", (chat_id,))
        db.execute("DELETE FROM users WHERE id = %s", (uid,))
        db.execute("DELETE FROM login_attempts WHERE ip = '127.0.0.1'")


def main() -> int:
    from app import db

    with tempfile.TemporaryDirectory(prefix="claude-login-") as tmp:
        bin_path = str(Path(tmp) / "claude")
        Path(bin_path).write_text(FAKE, encoding="utf-8")
        os.chmod(bin_path, stat.S_IRWXU)
        fail_flag = Path(tmp) / "auth-fails"
        env = {**os.environ, "FAKE_CLAUDE_URL": URL, "FAKE_CLAUDE_CODE": GOOD_CODE,
               "FAKE_CLAUDE_ERR": AUTH_ERROR, "FAKE_CLAUDE_FAIL_FLAG": str(fail_flag)}
        os.environ.update(env)

        print("Разбор строк")
        check_pure()
        print("Вход в процессе")
        asyncio.run(check_flow(bin_path))
        print("Живая страница")
        db.init_pool()
        try:
            check_live(bin_path, env, fail_flag)
        finally:
            db.close_pool()
        left = pids_of(bin_path)
        check(not left, f"после стенда поддельных claude не осталось ({left})")

    print()
    if FAILED:
        print(f"ПРОВАЛОВ: {len(FAILED)}")
        return 1
    print("Все проверки пройдены.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
