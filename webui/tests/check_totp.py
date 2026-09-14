"""Проверка второго фактора входа: код из приложения-аутентификатора.

Места, где это ломается незаметно или опасно:

* алгоритм посчитан неверно — приложение показывает одно, сервер ждёт другое,
  и включённый второй фактор закрывает вход хозяину;
* при включённом втором факторе сессия всё равно выдаётся после одного пароля —
  защита выглядит включённой, но не действует;
* тот же код проходит дважды — подсмотренный код остаётся ключом;
* окно приёма слишком широкое — одновременно годны десятки кодов;
* пропуск ко второму шагу подделывается или живёт вечно;
* секрет включается без подтверждения кодом — сбитое сканирование закрывает вход.

Стенд поднимает второй экземпляр приложения на свободном порту (рабочую службу
не трогает), заводит СВОЕГО пользователя `totp-probe` — настоящий вход
хозяина не затрагивается ни на миг — и убирает всё за собой.

Запуск:  .venv/bin/python tests/check_totp.py
"""
import base64
import http.cookiejar
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db, security                          # noqa: E402
from app.services import totp                         # noqa: E402

PROJECT_DIR = Path(__file__).resolve().parent.parent
FAILED: list[str] = []
LOGIN = "totp-probe"
PASSWORD = "стенд-второго-фактора-2026"


def check(ok: bool, what: str) -> None:
    if ok:
        print(f"  ok: {what}")
    else:
        FAILED.append(what)
        print(f"  ПРОВАЛ: {what}")


# ── Алгоритм ─────────────────────────────────────────────────────────

def check_pure() -> None:
    # RFC 6238, приложение B: SHA1, секрет "12345678901234567890", 8 цифр.
    key = b"12345678901234567890"
    for t, want in [(59, "94287082"), (1111111109, "07081804"), (1111111111, "14050471"),
                    (1234567890, "89005924"), (2000000000, "69279037"), (20000000000, "65353130")]:
        check(totp.hotp(key, t // 30, digits=8) == want, f"RFC 6238, T={t}: {want}")

    secret = totp.new_secret()
    check(len(base64.b32decode(secret)) == 20, "секрет — 160 бит, как требует RFC 4226")
    check(totp.new_secret() != secret, "секреты не повторяются")

    now = 1_800_000_000.0
    step = totp.current_step(now)
    code = totp.code_at(secret, step)
    check(totp.match(secret, code, 0, now) == step, "текущий код принимается")
    check(totp.match(secret, totp.code_at(secret, step - 1), 0, now) == step - 1,
          "код предыдущего отрезка принимается (часы телефона отстают)")
    check(totp.match(secret, totp.code_at(secret, step + 1), 0, now) == step + 1,
          "код следующего отрезка принимается (часы телефона спешат)")
    check(totp.match(secret, totp.code_at(secret, step - 2), 0, now) is None,
          "код двух отрезков назад отвергается — окно не шире ±1")
    check(totp.match(secret, totp.code_at(secret, step + 2), 0, now) is None,
          "код на два отрезка вперёд отвергается")
    check(totp.match(secret, code, step, now) is None,
          "уже принятый отрезок второй раз не проходит")
    check(totp.match(secret, f"{code[:3]} {code[3:]}", 0, now) == step,
          "код с пробелом посередине принимается")
    for bad in ["", "12345", "1234567", "abcdef", "12345a"]:
        check(totp.match(secret, bad, 0, now) is None, f"негодный код «{bad}» отвергнут")
    check(totp.match(secret.lower(), code, 0, now) == step, "секрет в нижнем регистре понимается")

    uri = totp.provisioning_uri(secret, "Svetlana")
    check(uri.startswith("otpauth://totp/") and f"secret={secret}" in uri and "period=30" in uri,
          "адрес для приложения собран по формату otpauth://")


# ── Живой вход ────────────────────────────────────────────────────────

def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_ready(port: int, proc: subprocess.Popen, tries: int = 60) -> bool:
    for _ in range(tries):
        if proc.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=1) as res:
                if res.status == 200:
                    return True
        except Exception:                              # noqa: BLE001
            time.sleep(0.5)
    return False


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):     # noqa: D401
        return None


def check_live() -> None:
    db.execute("DELETE FROM users WHERE login = %s", (LOGIN,))
    secret = totp.new_secret()
    row = db.query_one(
        "INSERT INTO users (login, password_hash, must_change, totp_secret, totp_enabled) "
        "VALUES (%s, %s, false, %s, true) RETURNING id",
        (LOGIN, security.hash_password(PASSWORD), secret),
    )
    uid = row["id"]
    # Счётчик неудач по адресу общий со всеми входами: чистим свой адрес до и
    # после, иначе стенд сам себе закрыл бы вход, а заодно и хозяину с петли.
    db.execute("DELETE FROM login_attempts WHERE ip = '127.0.0.1'")

    port = free_port()
    proc = subprocess.Popen(
        [str(PROJECT_DIR / ".venv/bin/python"), "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=str(PROJECT_DIR), env=dict(os.environ),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    opener = urllib.request.build_opener(NoRedirect)

    def post(path: str, fields: dict) -> tuple[int, str, dict]:
        data = urllib.parse.urlencode(fields).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data)
        try:
            with opener.open(req, timeout=15) as res:
                return res.status, res.read().decode("utf-8", "replace"), dict(res.headers)
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", "replace"), dict(exc.headers)

    def token_of(body: str) -> str:
        m = re.search(r'name="token" value="([^"]+)"', body)
        return m.group(1) if m else ""

    try:
        if not wait_ready(port, proc):
            check(False, "второй экземпляр не поднялся")
            return

        # 1. Пароль верен — сессии нет, есть второй шаг.
        status, body, headers = post("/login", {"login": LOGIN, "password": PASSWORD})
        check(status == 200 and "Код из приложения" in body,
              f"после верного пароля — форма кода, а не вход (код {status})")
        check("webui_session" not in headers.get("set-cookie", ""),
              "после одного пароля cookie сессии НЕ выдаётся")
        count = db.query_one("SELECT count(*) AS n FROM sessions WHERE user_id = %s", (uid,))["n"]
        check(count == 0, "после одного пароля в базе нет ни одной сессии")
        token = token_of(body)
        check(bool(token), "в форме кода есть пропуск ко второму шагу")

        # 2. Неверный пароль — второго шага нет.
        status, body, _ = post("/login", {"login": LOGIN, "password": "не тот"})
        check("Неверный логин или пароль" in body and not token_of(body),
              "при неверном пароле пропуск ко второму шагу не выдаётся")

        # 3. Неверный код — сессии нет.
        wrong = str((int(totp.code_at(secret, totp.current_step())) + 1) % 1000000).zfill(6)
        status, body, headers = post("/login/totp", {"token": token, "code": wrong})
        check("Код не подошёл" in body and "webui_session" not in headers.get("set-cookie", ""),
              "неверный код — отказ, сессии нет")

        # 4. Подделанный пропуск.
        status, body, headers = post("/login/totp", {"token": token[:-4] + "AAAA",
                                                    "code": totp.code_at(secret, totp.current_step())})
        check("Войдите заново" in body and "webui_session" not in headers.get("set-cookie", ""),
              "подделанный пропуск — отказ, сессии нет")

        # 5. Пропуск, подписанный чужой солью (например, подпись сессии).
        forged = security.sign_session_id(str(uid))
        status, body, headers = post("/login/totp", {"token": forged,
                                                    "code": totp.code_at(secret, totp.current_step())})
        check("webui_session" not in headers.get("set-cookie", ""),
              "подпись сессии за пропуск не сходит")

        # 6. Верный код — сессия.
        code = totp.code_at(secret, totp.current_step())
        status, body, headers = post("/login/totp", {"token": token, "code": code})
        check(status == 303 and "webui_session" in headers.get("set-cookie", ""),
              f"верный код — вход, cookie сессии выдана (код {status})")
        count = db.query_one("SELECT count(*) AS n FROM sessions WHERE user_id = %s", (uid,))["n"]
        check(count == 1, "в базе ровно одна сессия")

        # 7. Тот же код ещё раз, с новым пропуском, — отказ.
        _, body, _ = post("/login", {"login": LOGIN, "password": PASSWORD})
        token2 = token_of(body)
        status, body, headers = post("/login/totp", {"token": token2, "code": code})
        check("webui_session" not in headers.get("set-cookie", ""),
              "тот же код второй раз не проходит")

        # 8. Смена пароля обесценивает выданный пропуск.
        _, body, _ = post("/login", {"login": LOGIN, "password": PASSWORD})
        token3 = token_of(body)
        db.execute("UPDATE users SET password_hash = %s WHERE id = %s",
                   (security.hash_password(PASSWORD + "-новый"), uid))
        db.execute("UPDATE users SET totp_last_step = 0 WHERE id = %s", (uid,))
        status, body, headers = post("/login/totp", {"token": token3,
                                                    "code": totp.code_at(secret, totp.current_step())})
        check("Войдите заново" in body and "webui_session" not in headers.get("set-cookie", ""),
              "после смены пароля старый пропуск не действует")

        # 9. Пользователь без второго фактора входит как прежде — одним паролем.
        db.execute("UPDATE users SET password_hash = %s, totp_enabled = false WHERE id = %s",
                   (security.hash_password(PASSWORD), uid))
        status, body, headers = post("/login", {"login": LOGIN, "password": PASSWORD})
        check(status == 303 and "webui_session" in headers.get("set-cookie", ""),
              "без второго фактора вход по паролю не сломан")

        # 10. Подключение — теми же нажатиями, что в браузере.
        cookie = headers.get("set-cookie", "").split(";")[0]
        db.execute("UPDATE users SET totp_secret = NULL, totp_last_step = 0 WHERE id = %s", (uid,))
        # Лишняя сессия — «чужая»: после включения её обязаны закрыть.
        other = security.new_session_id()
        db.execute("INSERT INTO sessions (id, user_id, expires_at, ip, user_agent) "
                   "VALUES (%s, %s, %s, %s, %s)",
                   (other, uid, security.session_expiry(), "203.0.113.7", "чужая сессия"))

        def as_user(method: str, path: str, fields: dict | None = None):
            data = urllib.parse.urlencode(fields).encode() if fields is not None else None
            req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data,
                                         headers={"Cookie": cookie}, method=method)
            try:
                with opener.open(req, timeout=15) as res:
                    return res.status, res.read().decode("utf-8", "replace"), dict(res.headers)
            except urllib.error.HTTPError as exc:
                return exc.code, exc.read().decode("utf-8", "replace"), dict(exc.headers)

        status, body, _ = as_user("GET", "/settings/totp")
        check(status == 200 and "Подключить" in body, "страница подключения открывается")
        status, _, _ = as_user("POST", "/settings/totp/start", {})
        row = db.query_one("SELECT totp_secret, totp_enabled FROM users WHERE id = %s", (uid,))
        check(bool(row["totp_secret"]) and not row["totp_enabled"],
              "«Подключить» заводит секрет, но НЕ включает второй фактор")
        new = row["totp_secret"]
        status, body, headers = as_user("GET", "/settings/totp")
        check("<svg" in body and totp.grouped(new) in body, "показаны QR-код и ключ для ручного ввода")
        check("no-store" in headers.get("cache-control", ""), "страница с секретом не кэшируется")

        wrong = str((int(totp.code_at(new, totp.current_step())) + 1) % 1000000).zfill(6)
        as_user("POST", "/settings/totp/enable", {"code": wrong})
        row = db.query_one("SELECT totp_enabled FROM users WHERE id = %s", (uid,))
        check(not row["totp_enabled"], "неверный код при подключении второй фактор не включает")

        as_user("POST", "/settings/totp/enable", {"code": totp.code_at(new, totp.current_step())})
        row = db.query_one("SELECT totp_enabled FROM users WHERE id = %s", (uid,))
        check(row["totp_enabled"], "верный код включает второй фактор")
        gone = db.query_one("SELECT 1 AS x FROM sessions WHERE id = %s", (other,))
        check(gone is None, "после включения прочие сессии закрыты")
        status, _, _ = as_user("GET", "/settings/totp")
        check(status == 200, "своя сессия после включения жива")

        # 11. Отключение: одной сессии мало — нужны пароль и код.
        as_user("POST", "/settings/totp/disable", {"password": "не тот", "code": ""})
        row = db.query_one("SELECT totp_enabled FROM users WHERE id = %s", (uid,))
        check(row["totp_enabled"], "без пароля и кода второй фактор не отключается")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        db.execute("DELETE FROM users WHERE login = %s", (LOGIN,))   # сессии уходят каскадом
        db.execute("DELETE FROM login_attempts WHERE login LIKE %s", (LOGIN + "%",))
        db.execute("DELETE FROM login_attempts WHERE ip = '127.0.0.1'")


def main() -> int:
    db.init_pool()
    print("Алгоритм:")
    check_pure()
    print("\nЖивой вход:")
    check_live()
    print()
    if FAILED:
        print(f"ПРОВАЛОВ: {len(FAILED)}")
        for item in FAILED:
            print(f"  - {item}")
        return 1
    print("Все проверки прошли.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
