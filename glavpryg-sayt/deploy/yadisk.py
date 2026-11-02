#!/usr/bin/env python3
"""Яндекс Диск Светланы — только папка приложения «Приложения → Claude Главпрыг».

Код доступа (~/.config/yandex-app-token) выдан с правом лишь на эту папку: остальной
Диск им не открыть (проверено 02.11.2026: disk:/ и её папки отвечают 403).

    yadisk.py zalit <файл> <путь-в-папке>         — загрузить файл
    yadisk.py sinhr <папка> <путь-в-папке> [--iskl шаблон ...]
                                                 — довести папку на Диске до местной:
                                                   новое и изменённое залить, лишнее удалить
    yadisk.py ostavit <путь-в-папке> <шаблон> <N>  — из файлов по шаблону оставить N новейших
"""
import fnmatch
import hashlib
import json
import os
import socket
import sys
import time
import urllib.parse
import urllib.request

# Только IPv4: по IPv6 Диск тянет загрузку еле-еле (02.11.2026: 140 КБ/с против мегабайт)
_gai = socket.getaddrinfo
socket.getaddrinfo = lambda host, port, family=0, *a, **k: _gai(host, port, socket.AF_INET, *a, **k)

API = "https://cloud-api.yandex.net/v1/disk/resources"
TOKEN = open(os.path.expanduser("~/.config/yandex-app-token")).read().strip()


def zapros(metod, put, dop=None, telo=None, ok=(200, 201, 202, 204)):
    params = {"path": "app:/" + put.strip("/")}
    params.update(dop or {})
    url = f"{API}{'/' + metod if metod in ('upload',) else ''}?{urllib.parse.urlencode(params)}"
    http = "GET" if metod in ("get", "upload") else metod
    for popytka in range(5):
        req = urllib.request.Request(url, method=http, headers={"Authorization": f"OAuth {TOKEN}"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                b = r.read()
                return r.status, (json.loads(b) if b else {})
        except urllib.error.HTTPError as e:
            if e.code in (404, 409) or e.code < 500 and e.code != 429:
                return e.code, {}
        except OSError:
            pass
        time.sleep(5 * (popytka + 1))
    raise SystemExit(f"Диск не отвечает: {metod} {put}")


def papka(put):
    chast = ""
    for p in put.strip("/").split("/"):
        chast = f"{chast}/{p}" if chast else p
        zapros("PUT", chast)


def zalit(fail, put):
    papka(os.path.dirname(put.strip("/"))) if "/" in put.strip("/") else None
    for popytka in range(5):
        kod, d = zapros("upload", put, {"overwrite": "true"})
        if kod == 200:
            with open(fail, "rb") as f:
                req = urllib.request.Request(d["href"], data=f, method="PUT",
                                             headers={"Content-Length": str(os.path.getsize(fail))})
                try:
                    with urllib.request.urlopen(req, timeout=3600) as r:
                        if r.status in (201, 202):
                            return
                except OSError:
                    pass
        time.sleep(10 * (popytka + 1))
    raise SystemExit(f"не загрузился: {fail}")


def spisok(put):
    """Все файлы под путём: {относительный путь: md5}."""
    vse, ochered = {}, [put.strip("/")]
    while ochered:
        p = ochered.pop()
        sdvig = 0
        while True:
            kod, d = zapros("get", p, {"limit": 1000, "offset": sdvig})
            if kod != 200:
                break
            items = d.get("_embedded", {}).get("items", [])
            for it in items:
                otn = it["path"].split("/Claude Главпрыг/", 1)[-1] if "Claude Главпрыг/" in it["path"] else it["path"].replace("app:/", "")
                otn = otn.replace("disk:/Приложения/Claude Главпрыг/", "")
                if it["type"] == "dir":
                    ochered.append(otn)
                else:
                    vse[otn] = it.get("md5")
            if len(items) < 1000:
                break
            sdvig += 1000
    return vse


def md5(fail):
    h = hashlib.md5()
    with open(fail, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def sinhr(mesto, put, iskl):
    put = put.strip("/")
    papka(put)
    na_diske = spisok(put)
    zdes = {}
    for koren, dirs, files in os.walk(mesto):
        for f in files:
            polnyy = os.path.join(koren, f)
            otn = os.path.relpath(polnyy, mesto)
            if any(fnmatch.fnmatch(otn, s) for s in iskl) or os.path.islink(polnyy):
                continue
            zdes[f"{put}/{otn}"] = polnyy
    zalito = 0
    for cel, polnyy in sorted(zdes.items()):
        if na_diske.get(cel) != md5(polnyy):
            zalit(polnyy, cel)
            zalito += 1
    udaleno = 0
    for cel in set(na_diske) - set(zdes):
        zapros("DELETE", cel, {"permanently": "true"})
        udaleno += 1
    print(f"{put}: файлов {len(zdes)}, залито {zalito}, удалено {udaleno}")


def ostavit(put, shablon, n):
    kod, d = zapros("get", put, {"limit": 1000, "sort": "-name"})
    imena = sorted((it["name"] for it in d.get("_embedded", {}).get("items", [])
                    if fnmatch.fnmatch(it["name"], shablon)), reverse=True)
    for im in imena[n:]:
        zapros("DELETE", f"{put.strip('/')}/{im}", {"permanently": "true"})


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["zalit"]:
        zalit(a[1], a[2])
    elif a[:1] == ["sinhr"]:
        iskl = a[a.index("--iskl") + 1:] if "--iskl" in a else []
        sinhr(a[1], a[2], iskl)
    elif a[:1] == ["ostavit"]:
        ostavit(a[1], a[2], int(a[3]))
    else:
        raise SystemExit(__doc__)
