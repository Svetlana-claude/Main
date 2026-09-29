"""Проверка предела загрузки файла: 512 МБ принимаются, лишнее отбивается.

Предел стоит в трёх местах, и ломается он тем, что они расходятся:

* **приложение рубит раньше обещанного** — файл в 100 МБ не принят, хотя
  в форме написано «до 512 МБ». Так и было до правки: предел был 64 МБ;
* **приложение не рубит вовсе** — файл сверх предела дописывается в
  `uploads/` целиком, и место на диске кончается молча. Здесь же проверяется,
  что от отбитой загрузки не остаётся ни записи в базе, ни обрезка на диске;
* **nginx рубит раньше приложения** — тело запроса не доходит, и вместо
  понятной надписи пользователь получает сухую ошибку 413. Значение из
  настроек nginx сверяется с пределом приложения, и крупное тело
  прогоняется через живой nginx по-настоящему. Заодно сверяется копия
  настроек в `deploy/`: правка на сервере без неё живёт до первой раскладки
  с нуля, а потом предел молча возвращается к прежнему.

Надписи формы сверяются с тем же числом: расхождение — это обещание,
которого приложение не выполняет.

Стенд поднимает свою копию приложения на свободном порту и заводит свой
проект; рабочая служба не трогается. Загрузка идёт потоком с диска, в память
полгигабайта не поднимается.

Запуск:  .venv/bin/python tests/check_upload_limit.py
"""
import io
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, db, security as auth          # noqa: E402

PROJECT_DIR = Path(__file__).resolve().parent.parent
NGINX_CONF = Path("/etc/nginx/sites-available/webui")
DEPLOY_CONF = PROJECT_DIR / "deploy/nginx-webui.conf"
LIVE_URL = "https://mokeevasky.ru/Claude"

MB = 1024 * 1024
LIMIT = config.MAX_UPLOAD_BYTES
# Крупный файл в пределах разрешённого: прежний предел (64 МБ) на нём падал
UNDER = 100 * MB
FAILED: list[str] = []


def check(ok: bool, what: str) -> None:
    if ok:
        print(f"  ok: {what}")
    else:
        FAILED.append(what)
        print(f"  ПРОВАЛ: {what}")


def plain(html: str) -> str:
    """Пробелы и переносы в разметке — один пробел: надпись в шаблоне может
    быть разбита на строки, а на странице читается слитно."""
    return re.sub(r"\s+", " ", html)


def make_file(path: Path, size: int) -> None:
    """Файл нужного размера, без полгигабайта в памяти."""
    block = b"\0" * MB
    with path.open("wb") as sink:
        left = size
        while left > 0:
            sink.write(block[: min(left, MB)])
            left -= MB


class ChainStream:
    """Тело запроса из нескольких частей: шапка, файл с диска, хвост.

    `http.client` читает отправляемое кусками по 8 КБ, поэтому достаточно
    метода `read` — собирать многочастное тело в отдельный файл и занимать
    вторую копию места на диске не нужно.
    """

    def __init__(self, parts):
        self.parts = list(parts)

    def read(self, amount: int = -1) -> bytes:
        while self.parts:
            chunk = self.parts[0].read(amount)
            if chunk:
                return chunk
            self.parts.pop(0).close()
        return b""


def upload(url: str, cookie: str, project_id: int, path: Path, name: str):
    """Отправка файла формой загрузки. Возвращает конечный адрес и страницу."""
    boundary = "granitsa" + uuid.uuid4().hex
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="upload"; filename="{name}"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode()
    tail = f"\r\n--{boundary}--\r\n".encode()

    body = ChainStream([io.BytesIO(head), path.open("rb"), io.BytesIO(tail)])
    req = urllib.request.Request(
        f"{url}/projects/{project_id}/upload", data=body, method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    req.add_header("Content-Length", str(len(head) + path.stat().st_size + len(tail)))
    req.add_header("Cookie", f"{config.COOKIE_NAME}={cookie}")
    with urllib.request.urlopen(req, timeout=900) as res:
        return res.geturl(), res.read().decode("utf-8", "replace")


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
            time.sleep(0.3)
    return False


# ── Загрузка через настоящий запрос ──────────────────────────────────────

def check_upload(port: int, cookie: str, project_id: int, tmp: Path) -> None:
    url = f"http://127.0.0.1:{port}"
    mb = LIMIT // MB

    page = urllib.request.urlopen(urllib.request.Request(
        f"{url}/projects?id={project_id}",
        headers={"Cookie": f"{config.COOKIE_NAME}={cookie}"}), timeout=30
    ).read().decode("utf-8", "replace")
    check(f"До {mb} МБ" in plain(page), f"форма обещает «До {mb} МБ»")

    # Крупный файл в пределах разрешённого: на прежнем пределе не проходил
    big = tmp / "крупный.bin"
    make_file(big, UNDER)
    where, _ = upload(url, cookie, project_id, big, "крупный.bin")
    check("err=big" not in where, f"файл {UNDER // MB} МБ принят")

    row = db.query_one(
        "SELECT stored_name, size_bytes FROM files WHERE project_id = %s "
        "ORDER BY id DESC LIMIT 1", (project_id,))
    check(bool(row) and row["size_bytes"] == UNDER,
          "в базе записан полный размер принятого файла")
    if row:
        saved = config.UPLOADS_DIR / row["stored_name"]
        check(saved.is_file() and saved.stat().st_size == UNDER,
              "файл лёг на диск целиком")

    big.unlink()

    # Сверх предела: отбить, ничего не записать и обрезок не оставить
    wasRows = db.query_one(
        "SELECT count(*) AS n FROM files WHERE project_id = %s", (project_id,))["n"]
    wasFiles = len(list(config.UPLOADS_DIR.glob("*")))

    over = tmp / "сверх-предела.bin"
    make_file(over, LIMIT + MB)
    where, page = upload(url, cookie, project_id, over, "сверх-предела.bin")
    over.unlink()

    check("err=big" in where, f"файл больше {mb} МБ отбит")
    check(f"Файл больше {mb} МБ" in plain(page),
          "сообщение называет тот же предел")
    nowRows = db.query_one(
        "SELECT count(*) AS n FROM files WHERE project_id = %s", (project_id,))["n"]
    check(nowRows == wasRows, "отбитая загрузка не оставила записи в базе")
    check(len(list(config.UPLOADS_DIR.glob("*"))) == wasFiles,
          "отбитая загрузка не оставила обрезок на диске")


# ── nginx: тело должно доходить до приложения ────────────────────────────

def nginx_limit_bytes(conf: Path = NGINX_CONF) -> int | None:
    if not conf.is_file():
        return None
    found = re.search(r"^\s*client_max_body_size\s+(\d+)([kmg]?);",
                      conf.read_text(encoding="utf-8"),
                      re.IGNORECASE | re.MULTILINE)
    if not found:
        return None
    size = int(found.group(1))
    return size * {"": 1, "k": 1024, "m": MB, "g": 1024 * MB}[found.group(2).lower()]


def check_nginx(tmp: Path) -> None:
    nginxMax = nginx_limit_bytes()
    if nginxMax is None:
        check(False, "в настройках nginx не нашлось client_max_body_size")
    else:
        check(nginxMax >= LIMIT,
              f"nginx пропускает тело не меньше предела приложения "
              f"({nginxMax // MB} МБ против {LIMIT // MB} МБ)")

    # Копия настроек nginx в репозитории: правка на сервере без неё живёт
    # до первой раскладки с нуля, а потом предел молча возвращается к прежнему
    inRepo = nginx_limit_bytes(DEPLOY_CONF)
    check(inRepo is not None and inRepo == nginxMax,
          "копия настроек nginx в deploy/ называет тот же предел")

    # По-настоящему: тело крупнее прежних 70 МБ должно дойти до приложения.
    # Адрес входа выбран нарочно — он ничего не меняет и ничего не пишет
    body = tmp / "telo-v-nginx.bin"
    make_file(body, 80 * MB)
    req = urllib.request.Request(f"{LIVE_URL}/login", data=body.open("rb"), method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("Content-Length", str(body.stat().st_size))
    try:
        with urllib.request.urlopen(req, timeout=300) as res:
            code = res.status
    except urllib.error.HTTPError as err:
        code = err.code
    except Exception as err:                           # noqa: BLE001
        check(False, f"живой nginx не ответил на крупное тело: {err}")
        body.unlink()
        return
    finally:
        body.unlink(missing_ok=True)
    check(code != 413, f"живой nginx не рубит тело в 80 МБ (ответ {code})")


def main() -> int:
    db.init_pool()
    user = db.query_one("SELECT id FROM users ORDER BY id LIMIT 1")
    if not user:
        print("ПРОВАЛ: в базе нет пользователя — некому загружать файл")
        return 1

    mark = uuid.uuid4().hex[:8]
    session_id = auth.new_session_id()
    db.execute(
        "INSERT INTO sessions (id, user_id, expires_at, ip, user_agent) "
        "VALUES (%s, %s, %s, %s, %s)",
        (session_id, user["id"], auth.session_expiry(), "127.0.0.1", "check_upload_limit"),
    )
    project = db.query_one(
        "INSERT INTO projects (name, slug, workdir) VALUES (%s, %s, %s) RETURNING id",
        (f"Стенд предела {mark}", f"stend-predela-{mark}", "/tmp/stend-predela"),
    )
    project_id = project["id"]

    port = free_port()
    # ROOT_PATH пустой: стенд слушает без nginx, и запрос по «/Claude/...»
    # получал бы 404 — провал лёг бы на продукт (правило 13)
    env = dict(os.environ, ROOT_PATH="")
    proc = subprocess.Popen(
        [str(PROJECT_DIR / ".venv/bin/python"), "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=str(PROJECT_DIR), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        if not wait_ready(port, proc):
            print("ПРОВАЛ: стенд приложения не поднялся")
            return 1
        with tempfile.TemporaryDirectory() as tmp:
            workDir = Path(tmp)
            print("Загрузка:")
            check_upload(port, auth.sign_session_id(session_id), project_id, workDir)
            print("nginx:")
            check_nginx(workDir)
    finally:
        proc.terminate()
        proc.wait(timeout=20)
        # Загруженное стендом убирается вместе с его проектом
        for row in db.query(
                "SELECT stored_name FROM files WHERE project_id = %s", (project_id,)):
            (config.UPLOADS_DIR / row["stored_name"]).unlink(missing_ok=True)
        db.execute("DELETE FROM projects WHERE id = %s", (project_id,))
        db.execute("DELETE FROM sessions WHERE id = %s", (session_id,))

    if FAILED:
        print(f"ПРОВАЛ ({len(FAILED)}):")
        for what in FAILED:
            print(" -", what)
        return 1

    print(f"OK: до {LIMIT // MB} МБ принимается, сверх — отбивается, "
          f"nginx тело пропускает, надписи совпадают")
    return 0


if __name__ == "__main__":
    sys.exit(main())
