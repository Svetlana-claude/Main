"""Работа с VPN-сервером WireGuard.

Приложение не трогает `/etc/wireguard` и не вызывает `wg` напрямую: доступа туда
у него нет и быть не должно. Единственная дверь к root — обёртка `webui-vpn`
с закрытым набором команд (`infra/webui-vpn.sh`), ей и только ей разрешён
беспарольный `sudo`. Здесь — вызов обёртки и разбор её вывода.

Имя клиента сверяется с образцом и здесь, хотя обёртка проверяет его сама.
Это не лишнее: имя приходит из браузера и по дороге попадает в путь к файлу
конфига, а проверка у самой границы дешевле рассуждений о том, всякий ли путь
к файлу проходит через обёртку.
"""
from __future__ import annotations

import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from .. import config

SUDO = "/usr/bin/sudo"
WRAPPER = "webui-vpn"
IFACE = "wg0"

# Чем вызывается обёртка. Переопределяется только проверками из `tests/`:
# подставив заглушку, стенд показывает панели вымышленных клиентов с заданным
# трафиком и не трогает работающий сервер. На безопасность это не влияет —
# кто может задать окружение службы, тот и так распоряжается приложением.
CMD = os.environ.get("WEBUI_VPN_CMD", "").split() or [SUDO, "-n", WRAPPER]

# Первым знаком буква или цифра: разреши ведущий дефис — и имя стало бы
# неотличимо от флага для обёртки.
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$")

# Куда обёртка кладёт конфиги клиентов. Каталог не версионируется.
CLIENTS_DIR = config.REPO_ROOT / "exchange" / "vpn"

# Подсказка, когда обёртка стоит старая: панель просит переставить копию.
OLD_WRAPPER_HINT = (
    "Обёртка webui-vpn не знает команду «peers» — установлена прежняя копия. "
    "Выполните с паролем: sudo bash infra/install-root-helpers.sh"
)


class VpnError(RuntimeError):
    """Обёртка отказала. Текст берётся из её вывода и показывается как есть."""


def plural(n: int, one: str, few: str, many: str) -> str:
    """Русское согласование: 1 минута, 2 минуты, 5 минут."""
    n = abs(n)
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def human_bytes(n: int) -> str:
    """Объём по-человечески. Разряды двоичные — как их считает сам wg."""
    if n < 1024:
        return f"{n} Б"
    value = float(n)
    for unit in ("КиБ", "МиБ", "ГиБ", "ТиБ"):
        value /= 1024
        if value < 1024:
            return f"{value:.1f} {unit}".replace(".", ",")
    return f"{value:.1f} ПиБ".replace(".", ",")


def human_since(epoch: int, now: float | None = None) -> str:
    """Сколько прошло с рукопожатия. 0 — клиент ни разу не подключался."""
    if not epoch:
        return "не подключался"
    delta = int((time.time() if now is None else now) - epoch)
    if delta < 0:
        delta = 0
    if delta < 60:
        return "только что"
    minutes = delta // 60
    if minutes < 60:
        return f"{minutes} {plural(minutes, 'минуту', 'минуты', 'минут')} назад"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} {plural(hours, 'час', 'часа', 'часов')} назад"
    days = hours // 24
    return f"{days} {plural(days, 'день', 'дня', 'дней')} назад"


@dataclass
class Peer:
    name: str
    ip: str
    pubkey: str
    rx: int
    tx: int
    handshake: int          # секунды от начала эпохи, 0 — ни разу не подключался
    endpoint: str

    @property
    def has_conf(self) -> bool:
        return conf_path(self.name) is not None

    @property
    def online(self) -> bool:
        """Связь считается живой, если рукопожатие было недавно: WireGuard
        обновляет его примерно раз в две минуты, пока туннель работает."""
        return bool(self.handshake) and (time.time() - self.handshake) < 180

    @property
    def rx_text(self) -> str:
        return human_bytes(self.rx)

    @property
    def tx_text(self) -> str:
        return human_bytes(self.tx)

    @property
    def seen_text(self) -> str:
        return human_since(self.handshake)


@dataclass
class State:
    installed: bool = False
    active: bool = False
    endpoint: str = ""
    port: str = ""
    pubkey: str = ""
    peers: list[Peer] = field(default_factory=list)
    note: str = ""          # почему данных нет, если их нет

    @property
    def rx_total(self) -> int:
        return sum(p.rx for p in self.peers)

    @property
    def tx_total(self) -> int:
        return sum(p.tx for p in self.peers)

    @property
    def rx_total_text(self) -> str:
        return human_bytes(self.rx_total)

    @property
    def tx_total_text(self) -> str:
        return human_bytes(self.tx_total)


def _run(*args: str, timeout: int = 30) -> tuple[int, str, str]:
    try:
        done = subprocess.run(
            [*CMD, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        return 127, "", "не найден sudo"
    except subprocess.TimeoutExpired:
        return 124, "", "обёртка не ответила вовремя"
    return done.returncode, done.stdout, done.stderr


def check_name(name: str) -> str:
    if not NAME_RE.match(name or ""):
        raise VpnError(
            "Имя может состоять из латиницы, цифр, дефиса и подчёркивания, "
            "первым знаком буква или цифра, до 32 знаков."
        )
    return name


def conf_path(name: str) -> Path | None:
    """Путь к конфигу клиента или None. Имя сверено с образцом, поэтому в путь
    не уедет ни «..», ни слеш."""
    check_name(name)
    path = CLIENTS_DIR / f"{name}.conf"
    return path if path.is_file() else None


def service_active() -> bool:
    done = subprocess.run(
        [SUDO, "-n", "/usr/bin/systemctl", "is-active", f"wg-quick@{IFACE}"],
        capture_output=True, text=True, check=False,
    )
    return done.stdout.strip() == "active"


def _parse_status(text: str) -> tuple[str, str]:
    """Открытый ключ сервера и порт из вывода `wg show`."""
    pubkey = port = ""
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("public key:"):
            pubkey = line.split(":", 1)[1].strip()
        elif line.startswith("listening port:"):
            port = line.split(":", 1)[1].strip()
    return pubkey, port


def _parse_peers(text: str) -> list[Peer]:
    peers: list[Peer] = []
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) != 7:
            continue
        name, ip, pubkey, rx, tx, handshake, endpoint = parts
        peers.append(
            Peer(
                name=name,
                ip=ip,
                pubkey=pubkey,
                rx=int(rx) if rx.isdigit() else 0,
                tx=int(tx) if tx.isdigit() else 0,
                handshake=int(handshake) if handshake.isdigit() else 0,
                endpoint=endpoint,
            )
        )
    peers.sort(key=lambda p: p.ip)
    return peers


def state() -> State:
    """Состояние сервера и клиентов. Ошибки не поднимает: панель должна
    открыться и тогда, когда сервера нет, — и сказать, чего не хватает."""
    st = State()
    rc, out, err = _run("status")
    if rc != 0:
        st.note = (err or out).strip() or "обёртка webui-vpn недоступна"
        return st
    st.installed = True
    st.active = service_active()
    st.pubkey, st.port = _parse_status(out)

    rc, out, err = _run("peers")
    if rc != 0:
        message = (err or out).strip()
        st.note = OLD_WRAPPER_HINT if "неизвестная команда" in message else message
        return st
    st.peers = _parse_peers(out)
    return st


def add(name: str, split: bool = False) -> Path:
    check_name(name)
    args = ["add", name] + (["--split"] if split else [])
    rc, out, err = _run(*args)
    if rc != 0:
        raise VpnError((err or out).strip() or "не удалось завести клиента")
    path = CLIENTS_DIR / f"{name}.conf"
    if not path.is_file():
        raise VpnError(f"клиент заведён, но файла {path} нет")
    return path


def remove(name: str) -> None:
    check_name(name)
    rc, out, err = _run("remove", name)
    if rc != 0:
        raise VpnError((err or out).strip() or "не удалось отозвать клиента")
    # Конфиг в каталоге выдачи обёртка не трогает — он лежит у пользователя.
    # Убираем сами, иначе отозванный клиент остаётся скачиваемым из панели.
    path = CLIENTS_DIR / f"{name}.conf"
    if path.is_file():
        path.rename(path.with_suffix(".conf.revoked"))


def conf_text(name: str) -> str:
    path = conf_path(name)
    if path is None:
        raise VpnError(
            f"Файла конфига для «{name}» нет в {CLIENTS_DIR}. "
            "Так бывает у клиентов, заведённых не из панели: закрытый ключ "
            "остался только у них, восстановить его нельзя — заведите заново."
        )
    return path.read_text(encoding="utf-8")


def qr_svg(name: str) -> str:
    """QR-код конфига в SVG. Картинка рисуется здесь, а не обёрткой: qrencode
    не требует root, а гонять двоичный файл через sudo незачем."""
    text = conf_text(name)
    try:
        done = subprocess.run(
            ["/usr/bin/qrencode", "-t", "SVG", "-o", "-", "-m", "1"],
            input=text, capture_output=True, text=True, timeout=10, check=False,
        )
    except FileNotFoundError as exc:
        raise VpnError("не установлен qrencode") from exc
    if done.returncode != 0:
        raise VpnError((done.stderr or "qrencode не смог построить код").strip())
    return done.stdout
