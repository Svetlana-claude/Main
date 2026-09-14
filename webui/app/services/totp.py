"""Второй фактор входа: одноразовые коды из приложения-аутентификатора (TOTP).

Зачем. С 14.09.2026 у агента беспарольный `sudo` на всё, приложение работает от
`mokeeva`, а у проекта «Веб-интерфейс» поднят `allow_bash`. Значит, пароль панели
в одиночку отделял бы интернет от root на сервере. Код из телефона добавляет
второй секрет, который не подобрать по сети и не узнать из утёкшего пароля.

Алгоритм — RFC 6238 (TOTP поверх HOTP из RFC 4226): HMAC-SHA1 от номера
30-секундного отрезка, 6 цифр. Написан здесь, а не взят библиотекой: это два
десятка строк, а каждая зависимость на пути входа — ещё одно место, которому
приходится доверять. Верность сверена с контрольными значениями из самого RFC
(см. `tests/check_totp.py`).

Три решения, на которых держится защита:

* **окно ±1 отрезок** — часы телефона расходятся с сервером на секунды, но не на
  минуты; шире окно — больше кодов принимается одновременно, и перебор проще;
* **повтор запрещён** — принятый отрезок запоминается, и тот же код второй раз не
  проходит: подсмотренный через плечо или перехваченный код одноразовый на деле;
* **секрет включается только после ввода верного кода** — иначе ошибка при
  сканировании QR-кода закрывала бы вход своему же хозяину.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import subprocess
import time
from urllib.parse import quote

STEP = 30          # секунд в отрезке — стандарт, его ждут все приложения
DIGITS = 6
WINDOW = 1         # сколько соседних отрезков принимать в каждую сторону
ISSUER = "Рабочее место mokeevasky.ru"


class TotpError(RuntimeError):
    """Неверный код или ошибка построения QR. Текст показывается пользователю."""


def new_secret() -> str:
    """160 бит случайности в base32 — длина, которую RFC 4226 рекомендует для SHA1."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii")


def _key(secret: str) -> bytes:
    # Приложения и люди пишут секрет по-разному: пробелы группами, строчные
    # буквы, без хвостовых «=». Приводим к виду, который понимает b32decode.
    clean = secret.replace(" ", "").upper()
    clean += "=" * (-len(clean) % 8)
    return base64.b32decode(clean)


def hotp(key: bytes, counter: int, digits: int = DIGITS) -> str:
    """RFC 4226, раздел 5.3: динамическое усечение HMAC-SHA1."""
    mac = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    value = struct.unpack(">I", mac[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % (10 ** digits)).zfill(digits)


def current_step(now: float | None = None) -> int:
    return int((time.time() if now is None else now) // STEP)


def code_at(secret: str, step: int) -> str:
    return hotp(_key(secret), step)


def match(secret: str, code: str, last_step: int, now: float | None = None) -> int | None:
    """Номер отрезка, которому соответствует код, или None.

    Отрезки не новее уже принятого (`last_step`) не рассматриваются вовсе — так
    повтор кода отвергается ещё до сравнения. Сравнение строк — постоянного
    времени: по времени ответа не угадать, сколько цифр совпало.
    """
    code = (code or "").replace(" ", "")
    if len(code) != DIGITS or not code.isdigit():
        return None
    try:
        key = _key(secret)
    except (ValueError, TypeError):
        return None
    base = current_step(now)
    for step in range(base - WINDOW, base + WINDOW + 1):
        if step <= last_step:
            continue
        if hmac.compare_digest(hotp(key, step), code):
            return step
    return None


def provisioning_uri(secret: str, login: str) -> str:
    """Адрес otpauth:// — его и кодирует QR, который сканирует приложение."""
    label = quote(f"{ISSUER}:{login}")
    return (
        f"otpauth://totp/{label}?secret={secret}"
        f"&issuer={quote(ISSUER)}&algorithm=SHA1&digits={DIGITS}&period={STEP}"
    )


def qr_svg(uri: str) -> str:
    """QR-код в SVG тем же qrencode, что рисует коды у VPN."""
    try:
        done = subprocess.run(
            ["/usr/bin/qrencode", "-t", "SVG", "-o", "-", "-m", "1"],
            input=uri, capture_output=True, text=True, timeout=10, check=False,
        )
    except FileNotFoundError as exc:
        raise TotpError("не установлен qrencode") from exc
    if done.returncode != 0:
        raise TotpError((done.stderr or "qrencode не смог построить код").strip())
    return done.stdout


def grouped(secret: str) -> str:
    """Секрет группами по четыре — чтобы его можно было ввести руками."""
    return " ".join(secret[i:i + 4] for i in range(0, len(secret), 4))
