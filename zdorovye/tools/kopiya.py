"""Зашифрованные копии «Здоровья»: база и бланки.

Шифр — открытым ключом (gpg). На сервере лежит только открытая половина: ею
можно запереть, но нельзя открыть. Закрытую половину (ключ) Светлана скачивает
один раз на странице «Доступы», после чего она удаляется с сервера.

    .venv/bin/python tools/kopiya.py klyuch          — создать ключ (один раз)
    .venv/bin/python tools/kopiya.py sdelat          — копия сейчас (так её делает cron каждую ночь)
    .venv/bin/python tools/kopiya.py proverit KLYUCH [КОПИЯ]
                                                     — открыть копию ключом и проверить базу
    .venv/bin/python tools/kopiya.py vosstanovit KLYUCH КОПИЯ ПАПКА
                                                     — распаковать копию в папку

Копии — ~/backups/zdorovye/ (14 последних) и в хранилище Selectel S3, папка
zdorovye-kopii/ (14 последних), если на сервере есть ключ хранилища.
Журнал — ~/backups/zdorovye/kopiya.log.
"""
import os
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import config  # noqa: E402

H = Path.home()
OUT = Path(os.environ.get("ZD_KOPII", H / "backups/zdorovye"))
PUB_HOME = config.DATA_DIR.parent / "zdorovye-kopii-gnupg"     # только открытая половина ключа
HRANIT = 14
LOG = OUT / "kopiya.log"
RCLONE = H / "tools/restic/rclone"
S3_ENV = H / "main/infra/obraz/s3-env.sh"
S3_CHISTKA = H / "main/infra/obraz/s3-chistka.py"
S3_PY = H / "tools/restic/.venv/bin/python"


def log(text: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True, mode=0o700)
    stamp = datetime.now(ZoneInfo("Europe/Moscow")).strftime("%d.%m.%Y %H:%M по Москве")
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(f"{stamp}  {text}\n")


def gpg(home: Path, *args: str, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(["gpg", "--homedir", str(home), "--batch", "--yes", "--quiet", *args],
                          check=True, capture_output=True, **kw)


def recipient() -> str:
    return (PUB_HOME / "poluchatel").read_text().strip()


def make_key() -> None:
    """Пара ключей: открытая — в PUB_HOME, закрытая — файлом KEY_FILE до скачивания."""
    if (PUB_HOME / "poluchatel").exists():
        sys.exit("Ключ уже создан. Новый сделает старые копии нечитаемыми — так не делаю.")
    tmp = Path(tempfile.mkdtemp(prefix="zd-klyuch-"))
    try:
        tmp.chmod(0o700)
        gpg(tmp, "--pinentry-mode", "loopback", "--passphrase", "",
            "--quick-gen-key", "Здоровье семьи — ключ от копий", "default", "default", "never")
        fpr = next(line.split(":")[9] for line in gpg(tmp, "--with-colons", "--list-keys").stdout.decode().splitlines()
                   if line.startswith("fpr:"))
        secret = gpg(tmp, "--armor", "--pinentry-mode", "loopback", "--passphrase", "",
                     "--export-secret-keys", fpr).stdout
        public = gpg(tmp, "--armor", "--export", fpr).stdout
        PUB_HOME.mkdir(parents=True, exist_ok=True, mode=0o700)
        gpg(PUB_HOME, "--import", input=public)
        (PUB_HOME / "poluchatel").write_text(fpr + "\n")
        fd = os.open(config.KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(secret)
        print(f"ключ создан: {fpr}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def make_copy() -> Path:
    OUT.mkdir(parents=True, exist_ok=True, mode=0o700)
    work = Path(tempfile.mkdtemp(prefix="zd-kopiya-"))
    try:
        # База — снимком, чтобы не поймать её посреди записи
        src = sqlite3.connect(config.DB_PATH)
        dst = sqlite3.connect(work / "zdorovye.db")
        with dst:
            src.backup(dst)
        src.close()
        dst.close()
        tar_path = work / "kopiya.tar"
        with tarfile.open(tar_path, "w") as tar:
            tar.add(work / "zdorovye.db", arcname="zdorovye.db")
            if config.FILES_DIR.is_dir():
                tar.add(config.FILES_DIR, arcname="files")
        name = f"zdorovye-{datetime.now(timezone.utc):%Y%m%d-%H%M}.tar.gpg"
        target = OUT / name
        gpg(PUB_HOME, "--trust-model", "always", "--encrypt", "--recipient", recipient(),
            "--output", str(target), str(tar_path))
        target.chmod(0o600)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    for old in sorted(OUT.glob("zdorovye-*.tar.gpg"))[:-HRANIT]:
        old.unlink()
    return target


def to_s3(path: Path) -> str:
    if not (H / ".config/selectel-s3.json").is_file() or not RCLONE.is_file():
        return "в хранилище не ушла: нет ключа хранилища"
    cmd = (f'source "{S3_ENV}" && "{RCLONE}" copyto "{path}" ":s3:$S3_BAKET/zdorovye-kopii/{path.name}" --retries 5 '
           f'&& "{S3_PY}" "{S3_CHISTKA}" ostavit zdorovye-kopii/ {HRANIT}')
    res = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
    return "в хранилище — да" if res.returncode == 0 else f"в хранилище не ушла: {res.stderr.strip()[-200:]}"


def open_copy(key_file: Path, copy: Path, into: Path) -> None:
    """Расшифровать копию ключом и распаковать."""
    home = Path(tempfile.mkdtemp(prefix="zd-otkryt-"))
    try:
        home.chmod(0o700)
        gpg(home, "--import", str(key_file))
        tar_path = home / "kopiya.tar"
        gpg(home, "--pinentry-mode", "loopback", "--passphrase", "", "--output", str(tar_path),
            "--decrypt", str(copy))
        into.mkdir(parents=True, exist_ok=True)
        with tarfile.open(tar_path) as tar:
            tar.extractall(into, filter="data")
    finally:
        shutil.rmtree(home, ignore_errors=True)


def check(key_file: Path, copy: Path) -> str:
    into = Path(tempfile.mkdtemp(prefix="zd-proverka-"))
    try:
        open_copy(key_file, copy, into)
        con = sqlite3.connect(into / "zdorovye.db")
        ok = con.execute("PRAGMA integrity_check").fetchone()[0]
        people = con.execute("SELECT count(*) FROM members").fetchone()[0]
        con.close()
        files = len(list((into / "files").glob("*"))) if (into / "files").is_dir() else 0
        return f"копия открывается: база {ok}, людей {people}, бланков {files}"
    finally:
        shutil.rmtree(into, ignore_errors=True)


def main() -> None:
    what = sys.argv[1] if len(sys.argv) > 1 else ""
    if what == "klyuch":
        make_key()
    elif what == "sdelat":
        try:
            path = make_copy()
        except Exception as exc:                               # noqa: BLE001
            log(f"ОШИБКА: копия не сделана: {exc}")
            sys.exit(1)
        log(f"копия {path.name}, {path.stat().st_size // 1024} КБ; {to_s3(path)}")
    elif what == "proverit" and len(sys.argv) >= 3:
        copy = Path(sys.argv[3]) if len(sys.argv) > 3 else sorted(OUT.glob("zdorovye-*.tar.gpg"))[-1]
        print(check(Path(sys.argv[2]), copy))
    elif what == "vosstanovit" and len(sys.argv) == 5:
        open_copy(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]))
        print(f"распаковано в {sys.argv[4]}: zdorovye.db и папка files")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
