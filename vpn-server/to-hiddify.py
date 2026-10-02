#!/usr/bin/env python3
"""Конфиг WireGuard → ссылка и профиль для Hiddify.

Hiddify — клиент на sing-box, и WireGuard он понимает двумя способами:
ссылкой `wireguard://` и профилем sing-box в JSON. Скрипт делает оба из
обычного `.conf`, выданного `add-client.sh`.

Зачем скрипт, а не руки: в ссылке закрытый ключ едет в части userinfo, а
ключи WireGuard в base64 и почти всегда содержат `/`, `+` и `=`. Без
процентного кодирования ссылка молча ломается — клиент берёт обрезанный
ключ и не подключается, ничего не сообщая. Руками это получается правильно
через раз и проверить глазами нельзя: верная и порванная ссылки выглядят
одинаково, отличие в трёх знаках посреди шестидесяти.

    ./to-hiddify.py exchange/vpn/Comp.conf              # ссылка и путь к JSON
    ./to-hiddify.py exchange/vpn/Comp.conf --tolko-ssylka
    ./to-hiddify.py --proverka                          # самопроверка

Имена параметров ссылки в разных сборках Hiddify разбираются по-разному,
поэтому JSON-профиль — не «запасной», а равноправный путь: в нём имена
полей заданы самим sing-box и двояко не читаются.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit

# MTU туннеля на сервере (`ip link show wg0`). В `.conf` строки MTU нет —
# официальный клиент берёт это значение сам, а sing-box без него ставит 1408.
# Разница небольшая, но пусть обе стороны считают одинаково.
MTU = 1420


class OshibkaRazbora(ValueError):
    """Конфиг не похож на выданный WireGuard."""


def razobrat_conf(text: str) -> dict[str, str]:
    """Поля из `.conf`. Разделы не различаем: имена полей и так не пересекаются."""
    polya: dict[str, str] = {}
    for stroka in text.splitlines():
        stroka = stroka.split("#", 1)[0].strip()
        if not stroka or stroka.startswith("["):
            continue
        if "=" not in stroka:
            continue
        klyuch, znachenie = stroka.split("=", 1)
        polya[klyuch.strip().lower()] = znachenie.strip()

    obyazatelno = ("privatekey", "address", "publickey", "endpoint")
    ne_hvataet = [k for k in obyazatelno if k not in polya]
    if ne_hvataet:
        raise OshibkaRazbora("в конфиге нет полей: " + ", ".join(ne_hvataet))
    if ":" not in polya["endpoint"]:
        raise OshibkaRazbora("Endpoint без порта: " + polya["endpoint"])
    return polya


def _adres(polya: dict[str, str]) -> list[str]:
    return [a.strip() for a in polya["address"].split(",") if a.strip()]


def ssylka(polya: dict[str, str], imya: str) -> str:
    """Ссылка `wireguard://`. Ключи кодируются целиком — `safe=""`, иначе
    `/` в ключе останется как есть и разделит путь."""
    server, port = polya["endpoint"].rsplit(":", 1)
    zapros = [
        ("address", ",".join(_adres(polya))),
        ("publickey", polya["publickey"]),
    ]
    if polya.get("presharedkey"):
        zapros.append(("presharedkey", polya["presharedkey"]))
    zapros.append(("mtu", str(MTU)))
    if polya.get("persistentkeepalive"):
        zapros.append(("keepalive", polya["persistentkeepalive"]))

    hvost = "&".join(f"{k}={quote(v, safe='')}" for k, v in zapros)
    klyuch = quote(polya["privatekey"], safe="")
    return f"wireguard://{klyuch}@{server}:{port}?{hvost}#{quote(imya, safe='')}"


def profil(polya: dict[str, str], imya: str) -> dict:
    """Профиль sing-box. Имена полей — как у самого sing-box, не наши."""
    server, port = polya["endpoint"].rsplit(":", 1)
    out: dict = {
        "type": "wireguard",
        "tag": imya,
        "server": server,
        "server_port": int(port),
        "local_address": _adres(polya),
        "private_key": polya["privatekey"],
        "peer_public_key": polya["publickey"],
        "mtu": MTU,
    }
    if polya.get("presharedkey"):
        out["pre_shared_key"] = polya["presharedkey"]
    return {"outbounds": [out]}


def razobrat_ssylku(url: str) -> dict[str, str]:
    """Разбор своей же ссылки — для проверки кругового превращения."""
    chasti = urlsplit(url)
    if chasti.scheme != "wireguard":
        raise OshibkaRazbora("не wireguard://")
    if chasti.username is None:
        raise OshibkaRazbora("в ссылке нет закрытого ключа")
    zapros = parse_qs(chasti.query, keep_blank_values=True)
    polya = {
        "privatekey": unquote(chasti.username),
        "endpoint": f"{chasti.hostname}:{chasti.port}",
        "address": zapros.get("address", [""])[0],
        "publickey": zapros.get("publickey", [""])[0],
    }
    if "presharedkey" in zapros:
        polya["presharedkey"] = zapros["presharedkey"][0]
    return polya


def otkrytyy_klyuch(zakrytyy: str) -> str | None:
    """Открытый ключ из закрытого — считает сам `wg`. None, если его нет."""
    try:
        gotovo = subprocess.run(
            ["wg", "pubkey"], input=zakrytyy + "\n",
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    return gotovo.stdout.strip() or None


# --- самопроверка ---------------------------------------------------------
#
# Проверяется то, из-за чего ссылка и ломалась: ключ со знаками `/`, `+`, `=`
# должен дойти до клиента дословно. Образец взят с настоящими знаками внутри.

OBRAZEC = """\
[Interface]
PrivateKey = wO/Hwjnu2T3+fBhWyugSEBP2aSwIm302bKwqgOXN/HQ=
Address = 10.8.0.9/32
DNS = 1.1.1.1, 8.8.8.8

[Peer]
PublicKey = 0OTDwUBq8Q3k5mqk6AKhTthniGy3IOzcjDKSPXVNYk0=
PresharedKey = 2klR13H+zw2wPABcmHt1z9OKgSKfw0XZcUr2ikTz3yw=
Endpoint = 46.8.178.196:51820
AllowedIPs = 0.0.0.0/0
PersistentKeepalive = 25
"""


def samoproverka() -> int:
    oshibki: list[str] = []

    def ravno(chto: str, bylo, stalo):
        if bylo != stalo:
            oshibki.append(f"{chto}: ждали {bylo!r}, получили {stalo!r}")

    polya = razobrat_conf(OBRAZEC)
    url = ssylka(polya, "proba")

    # Главное: ключи в ссылке закодированы, а не оставлены как есть.
    # Схему отрезаем: в самой `wireguard://` два слеша, и без этого проверка
    # ругается на исправный код — на чём и попалась при первом прогоне.
    userinfo = url.split("://", 1)[1].split("@", 1)[0]
    if "/" in userinfo:
        oshibki.append("слеш в закрытом ключе не закодирован — ссылка порвётся")
    if "+" in url.split("?", 1)[1]:
        oshibki.append("плюс в параметрах не закодирован — станет пробелом")

    # И круговое превращение: что положили, то и достаётся. Разбор обёрнут
    # нарочно: на неработающем кодировании ссылка рассыпается, разбор бросает
    # исключение — и без обёртки падение уносит уже найденные нарушения,
    # оставляя пустой вывод вместо отчёта.
    try:
        tuda_obratno = razobrat_ssylku(url)
    except OshibkaRazbora as exc:
        oshibki.append(f"своя же ссылка не разбирается обратно: {exc}")
        tuda_obratno = {}
    for pole in ("privatekey", "publickey", "presharedkey", "endpoint", "address"):
        ravno(pole, polya[pole], tuda_obratno.get(pole))

    prof = profil(polya, "proba")["outbounds"][0]
    ravno("private_key в профиле", polya["privatekey"], prof["private_key"])
    ravno("peer_public_key", polya["publickey"], prof["peer_public_key"])
    ravno("local_address", ["10.8.0.9/32"], prof["local_address"])
    ravno("server_port", 51820, prof["server_port"])

    # Конфиг без обязательного поля должен отвергаться, а не молча проходить.
    try:
        razobrat_conf("[Interface]\nAddress = 10.8.0.9/32\n")
        oshibki.append("конфиг без PrivateKey принят")
    except OshibkaRazbora:
        pass

    for s in oshibki:
        print("ПЛОХО:", s)
    print("Проверок не прошло:", len(oshibki)) if oshibki else print("Всё сошлось.")
    return 1 if oshibki else 0


def main() -> int:
    razbor = argparse.ArgumentParser(description="Конфиг WireGuard → Hiddify")
    razbor.add_argument("conf", nargs="?", help="путь к .conf")
    razbor.add_argument("--imya", help="подпись профиля; по умолчанию имя файла")
    razbor.add_argument("--tolko-ssylka", action="store_true",
                        help="напечатать одну ссылку и больше ничего")
    razbor.add_argument("--json-v", metavar="ПУТЬ", help="куда положить профиль sing-box")
    razbor.add_argument("--proverka", action="store_true", help="самопроверка")
    dovody = razbor.parse_args()

    if dovody.proverka:
        return samoproverka()
    if not dovody.conf:
        razbor.error("нужен путь к .conf (или --proverka)")

    put = Path(dovody.conf)
    polya = razobrat_conf(put.read_text(encoding="utf-8"))
    imya = dovody.imya or put.stem
    url = ssylka(polya, imya)

    if dovody.tolko_ssylka:
        print(url)
        return 0

    print(url)
    pub = otkrytyy_klyuch(polya["privatekey"])
    if pub:
        print(f"\nОткрытый ключ этого клиента: {pub}", file=sys.stderr)
        print("Он должен быть среди пиров сервера (webui-vpn peers).", file=sys.stderr)

    if dovody.json_v:
        cel = Path(dovody.json_v)
        cel.write_text(json.dumps(profil(polya, imya), indent=2, ensure_ascii=False) + "\n",
                       encoding="utf-8")
        cel.chmod(0o600)        # внутри закрытый ключ
        print(f"Профиль sing-box: {cel}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
