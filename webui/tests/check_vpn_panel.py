"""Проверка: панель VPN показывает клиентов и трафик и не отдаёт лишнего.

Четыре места, где это ломается незаметно или опасно:

* имя клиента из браузера уезжает в путь к файлу: `?name=../../.config/webui/webui.env`
  отдал бы `SECRET_KEY` и пароль базы — и именно через маршрут, который по замыслу
  раздаёт файлы с ключами;
* сводка от обёртки разбирается небрежно: строка не того вида превращается
  в клиента-призрака с нулевым трафиком, и панель врёт про расход;
* трафик и время последней связи считаются по-разному на странице и при опросе —
  числа расходятся сами по себе на глазах у смотрящего;
* страница не открывается вовсе: маршрут есть, а шаблон падает на живых данных.

Стенд поднимает второй экземпляр приложения на свободном порту (рабочую службу
не трогает), заводит себе сессию в базе и убирает её за собой.

Запуск:  .venv/bin/python tests/check_vpn_panel.py
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db, security                          # noqa: E402
from app.services import vpn                          # noqa: E402

PROJECT_DIR = Path(__file__).resolve().parent.parent
FAILED: list[str] = []


def check(ok: bool, what: str) -> None:
    if ok:
        print(f"  ok: {what}")
    else:
        FAILED.append(what)
        print(f"  ПРОВАЛ: {what}")


# ── Разбор и показ ────────────────────────────────────────────────────

def check_pure() -> None:
    check(vpn.human_bytes(0) == "0 Б", "нулевой объём пишется как «0 Б»")
    check(vpn.human_bytes(2048) == "2,0 КиБ", "2048 байт — это 2,0 КиБ")
    check(vpn.human_bytes(5 * 1024 ** 3).endswith("ГиБ"), "гигабайты не остаются байтами")

    now = time.time()
    check(vpn.human_since(0) == "не подключался", "нулевое рукопожатие — «не подключался»")
    check(vpn.human_since(int(now - 10), now) == "только что", "свежее рукопожатие — «только что»")
    check(vpn.human_since(int(now - 60), now) == "1 минуту назад", "минута согласована")
    check(vpn.human_since(int(now - 300), now) == "5 минут назад", "пять минут согласованы")
    check(vpn.human_since(int(now - 7200), now) == "2 часа назад", "часы согласованы")
    check(vpn.human_since(int(now - 3 * 86400), now) == "3 дня назад", "дни согласованы")

    # Имя приходит из браузера и уезжает в путь к файлу
    for bad in ["../../etc/passwd", "a b", "-flag", "", "x" * 33, "имя", "a/b"]:
        try:
            vpn.check_name(bad)
            check(False, f"негодное имя «{bad}» принято")
        except vpn.VpnError:
            check(True, f"негодное имя «{bad}» отвергнуто")
    try:
        vpn.check_name("phone-1_A")
        check(True, "годное имя принято")
    except vpn.VpnError:
        check(False, "годное имя отвергнуто")

    # Тот же образец должен закрывать и путь к конфигу
    try:
        vpn.conf_path("../../../home/mokeeva/.config/webui/webui.env")
        check(False, "путь наружу прошёл в conf_path")
    except vpn.VpnError:
        check(True, "путь наружу отвергнут в conf_path")

    sample = "\n".join([
        "beta\t10.8.0.3/32\tKEYB\t4096\t8192\t1757650000\t203.0.113.9:1234",
        "alpha\t10.8.0.2/32\tKEYA\t0\t0\t0\t",
        "строка не того вида",
        "",
    ])
    peers = vpn._parse_peers(sample)
    check(len(peers) == 2, "строка не того вида в сводку не попала")
    check([p.name for p in peers] == ["alpha", "beta"], "клиенты упорядочены по адресу")
    check(peers[1].rx == 4096 and peers[1].tx == 8192, "трафик разобран числами")
    check(peers[0].seen_text == "не подключался", "не подключавшийся так и подписан")
    check(peers[1].online is False, "рукопожатие 2026 года не считается живым")

    fresh = vpn.Peer("x", "10.8.0.9/32", "K", 0, 0, int(time.time()) - 30, "")
    check(fresh.online is True, "свежее рукопожатие считается живой связью")


# ── Живая страница ────────────────────────────────────────────────────

def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_ready(port: int, proc: subprocess.Popen, tries: int = 60) -> bool:
    """Ждём ответа порта, а не «процесс ещё жив»: живой процесс не значит,
    что приложение поднялось."""
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


STUB = """#!/bin/bash
# Заглушка обёртки webui-vpn: отдаёт заранее заданных клиентов с заданным
# трафиком. Нужна, чтобы отрисовка и опрос проверялись на непустых данных:
# на живом сервере клиентов может не быть вовсе, и «клиентов нет» прошло бы
# зелёным, ничего не проверив.
case "$1" in
    status) echo "interface: wg0"; echo "  public key: SRVKEY="; echo "  listening port: 51820" ;;
    peers)
        printf 'alpha\\t10.8.0.2/32\\tKEYA\\t0\\t0\\t0\\t\\n'
        printf 'beta\\t10.8.0.3/32\\tKEYB\\t4096\\t8192\\t%s\\t203.0.113.9:1234\\n' "$(date +%s)"
        ;;
    *) exit 1 ;;
esac
"""


def check_live() -> None:
    user = db.query_one("SELECT id FROM users ORDER BY id LIMIT 1")
    if not user:
        check(False, "в базе нет ни одного пользователя — некому открыть панель")
        return

    session_id = security.new_session_id()
    db.execute(
        "INSERT INTO sessions (id, user_id, expires_at, ip, user_agent) "
        "VALUES (%s, %s, %s, %s, %s)",
        (session_id, user["id"], security.session_expiry(), "127.0.0.1", "check_vpn_panel"),
    )
    cookie = f"webui_session={security.sign_session_id(session_id)}"

    stub_dir = tempfile.mkdtemp(prefix="vpn-stub-")
    stub = Path(stub_dir) / "webui-vpn-stub"
    stub.write_text(STUB, encoding="utf-8")
    stub.chmod(0o755)

    port = free_port()
    env = dict(os.environ, WEBUI_VPN_CMD=str(stub))
    proc = subprocess.Popen(
        [str(PROJECT_DIR / ".venv/bin/python"), "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=str(PROJECT_DIR),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        if not wait_ready(port, proc):
            check(False, "второй экземпляр не поднялся")
            return

        def get(path: str) -> tuple[int, str]:
            req = urllib.request.Request(f"http://127.0.0.1:{port}{path}",
                                         headers={"Cookie": cookie})
            try:
                with urllib.request.urlopen(req, timeout=10) as res:
                    return res.status, res.read().decode("utf-8", "replace")
            except urllib.error.HTTPError as exc:
                return exc.code, exc.read().decode("utf-8", "replace")

        status, body = get("/vpn")
        check(status == 200, f"страница /vpn отвечает 200 (получили {status})")
        check("Новый клиент" in body, "на странице есть форма нового клиента")
        check('data-peer="alpha"' in body and 'data-peer="beta"' in body,
              "оба клиента показаны в таблице")
        check("4,0 КиБ" in body and "8,0 КиБ" in body,
              "трафик клиента виден на странице человеческим объёмом")
        # Итог берётся из своих ячеек, а не «есть ли такая строка на странице»:
        # те же числа стоят и в строке клиента, и проверка была бы ни о чём.
        check('id="vpn-rx-total">4,0 КиБ<' in body, "итог принятого сложен по всем клиентам")
        check('id="vpn-tx-total">8,0 КиБ<' in body, "итог переданного сложен по всем клиентам")
        check("не подключался" in body, "клиент без рукопожатия так и подписан")
        check("dot--done" in body and "dot--empty" in body,
              "кружки связи разные: один на связи, другой нет")
        check("51820" in body, "порт сервера показан")

        status, body = get("/vpn/state")
        check(status == 200, f"опрос состояния отвечает 200 (получили {status})")
        data = json.loads(body)
        check(data.get("ok") is True, "опрос отвечает ok")
        check(len(data.get("peers", [])) == 2, "опрос отдаёт обоих клиентов")
        by_name = {p["name"]: p for p in data.get("peers", [])}
        check(by_name.get("beta", {}).get("rx_text") == "4,0 КиБ",
              "опрос отдаёт готовую строку трафика, а не сырые числа")
        check(by_name.get("beta", {}).get("online") is True,
              "свежее рукопожатие в опросе считается живой связью")
        check(by_name.get("alpha", {}).get("seen_text") == "не подключался",
              "опрос и страница подписывают неподключавшегося одинаково")
        check(data.get("rx_total_text") == "4,0 КиБ", "итог принятого в опросе сходится")

        # Маршруты с закрытым ключом: имя сверяется до всякого обращения к диску
        status, _ = get("/vpn/conf/..%2F..%2F.config%2Fwebui%2Fwebui.env")
        check(status == 404, f"путь наружу в /vpn/conf отбит (получили {status})")

        # Без входа панель не показывается
        req = urllib.request.Request(f"http://127.0.0.1:{port}/vpn")
        opener = urllib.request.build_opener(NoRedirect())
        try:
            with opener.open(req, timeout=10) as res:
                check(False, f"панель открылась без входа ({res.status})")
        except urllib.error.HTTPError as exc:
            check(exc.code == 303, f"без входа уводит на вход (получили {exc.code})")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)
        db.execute("DELETE FROM sessions WHERE id = %s", (session_id,))
        shutil.rmtree(stub_dir, ignore_errors=True)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):      # noqa: D102
        return None


def check_real() -> None:
    """Что отвечает настоящая обёртка. Отдельно от подставных данных: иначе
    стенд остаётся зелёным и тогда, когда панель на живом сервере пуста."""
    state = vpn.state()
    if state.peers:
        check(True, f"настоящая обёртка отдала клиентов: {len(state.peers)}")
        return
    check(
        state.note == vpn.OLD_WRAPPER_HINT,
        "клиентов нет, и причина названа понятной подсказкой "
        f"(сказано: {state.note or 'ничего'})",
    )
    print("  ВНИМАНИЕ: трафик на живом сервере не проверен — нужна новая копия обёртки")


def main() -> int:
    db.init_pool()
    try:
        print("Разбор и показ:")
        check_pure()
        print("Живая страница:")
        check_live()
        print("Настоящая обёртка:")
        check_real()
    finally:
        db.close_pool()

    if FAILED:
        print(f"\nПровалов: {len(FAILED)}")
        return 1
    print("\nВсе проверки пройдены.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
