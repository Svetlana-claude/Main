#!/usr/bin/env python3
"""Выгрузка макетов из Figma: опись кадров и картинки к ним.

Figma не отдаёт файл по ссылке — без ключа доступа там пустая оболочка
приложения. Ключ (personal access token) заводится в самой Figma:
аккаунт → Settings → Security → Personal access tokens → Generate new token,
права достаточно «File content: Read only». Готовый ключ кладётся в файл:

    ~/.config/figma.token

⚠️ Это пароль. Файл держать правами 600 и **в git не класть**.

Запуск:

    /usr/bin/python3 tools/figma-vygruzka.py <ссылка на макет> \\
        [--uzel 4:3] [--katalog exchange/figma] [--masshtab 2] [--tolko-opis]

Ссылку можно давать прямо из браузера — ключ файла и узел берутся из неё.
Без `--uzel` выгружается весь файл целиком. На выходе: `opis.md` с деревом
кадров и по PNG на каждый кадр верхнего уровня.
"""

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.figma.com/v1"
KLYUCH_PO_UMOLCHANIYU = Path.home() / ".config" / "figma.token"

# Типы узлов, которые имеет смысл показывать в описи: остальное — мелочь
# внутри кадра, от неё опись только разбухает.
KRUPNYE = {"CANVAS", "FRAME", "SECTION", "COMPONENT", "COMPONENT_SET", "GROUP"}


def vzyat_klyuch() -> str:
    """Ключ доступа — из переменной окружения или из файла."""
    iz_sredy = os.environ.get("FIGMA_TOKEN")
    if iz_sredy:
        return iz_sredy.strip()
    if KLYUCH_PO_UMOLCHANIYU.exists():
        return KLYUCH_PO_UMOLCHANIYU.read_text(encoding="utf-8").strip()
    sys.exit(
        f"нет ключа доступа к Figma: ни переменной FIGMA_TOKEN, ни файла "
        f"{KLYUCH_PO_UMOLCHANIYU}\n"
        f"как завести ключ — в шапке этого файла"
    )


def razobrat_ssylku(ssylka: str) -> tuple[str, str | None]:
    """Из ссылки браузера достаёт ключ файла и узел.

    Принимает и голый ключ файла — тогда узел не определяется.
    """
    if "/" not in ssylka:
        return ssylka, None
    sovpadenie = re.search(r"/(?:file|design|proto)/([A-Za-z0-9]+)", ssylka)
    if not sovpadenie:
        sys.exit(f"в ссылке не видно ключа файла: {ssylka}")
    fayl = sovpadenie.group(1)
    uzel = None
    zapros = urllib.parse.parse_qs(urllib.parse.urlparse(ssylka).query)
    if "node-id" in zapros:
        # В ссылке узел пишется через дефис, в запросах к API — через двоеточие.
        uzel = zapros["node-id"][0].replace("-", ":")
    return fayl, uzel


def sprosit(put: str, klyuch: str) -> dict:
    """Запрос к API с внятным разбором отказов."""
    zapros = urllib.request.Request(API + put, headers={"X-Figma-Token": klyuch})
    try:
        with urllib.request.urlopen(zapros, timeout=60) as otvet:
            return json.loads(otvet.read())
    except urllib.error.HTTPError as beda:
        telo = beda.read().decode("utf-8", "replace")[:400]
        if beda.code == 403:
            sys.exit("Figma отказала (403): ключ не подошёл или у него нет прав "
                     "на чтение файлов.\n" + telo)
        if beda.code == 404:
            sys.exit("Figma отвечает 404: файла нет либо у владельца ключа нет к "
                     "нему доступа. Макет нужно расшарить этому аккаунту.\n" + telo)
        if beda.code == 429:
            sys.exit("Figma просит подождать (429): слишком часто. Повторить позже.")
        sys.exit(f"Figma ответила {beda.code}: {telo}")
    except urllib.error.URLError as beda:
        sys.exit(f"не достучаться до api.figma.com: {beda.reason}")


def obkhod(uzel: dict, glubina: int, uroven: int = 0) -> list[tuple[int, dict]]:
    """Плоский список крупных узлов с их уровнем вложенности."""
    sobrano = []
    for rebenok in uzel.get("children", []):
        if rebenok.get("type") not in KRUPNYE:
            continue
        sobrano.append((uroven, rebenok))
        if uroven + 1 < glubina:
            sobrano += obkhod(rebenok, glubina, uroven + 1)
    return sobrano


def razmer(uzel: dict) -> str:
    korobka = uzel.get("absoluteBoundingBox") or {}
    if not korobka:
        return ""
    return f"{round(korobka.get('width', 0))}×{round(korobka.get('height', 0))}"


def bezopasnoe_imya(imya: str) -> str:
    """Имя кадра — в имя файла: без косых, пробелов и прочего неудобного."""
    chistoe = re.sub(r"[^\w\-. ]", "", imya, flags=re.UNICODE).strip()
    return re.sub(r"\s+", "-", chistoe).lower()[:60] or "kadr"


def main() -> int:
    razbor = argparse.ArgumentParser(description="Выгрузка макетов из Figma")
    razbor.add_argument("ssylka", help="ссылка на макет из браузера или ключ файла")
    razbor.add_argument("--uzel", help="узел вида 4:3; по умолчанию — из ссылки")
    razbor.add_argument("--katalog", default="exchange/figma",
                        help="куда складывать (по умолчанию exchange/figma)")
    razbor.add_argument("--masshtab", type=float, default=2.0,
                        help="масштаб картинок, 1–4 (по умолчанию 2)")
    razbor.add_argument("--glubina", type=int, default=2,
                        help="на сколько уровней расписывать опись")
    razbor.add_argument("--tolko-opis", action="store_true",
                        help="не качать картинки, только опись")
    dovody = razbor.parse_args()

    klyuch = vzyat_klyuch()
    fayl, uzel_iz_ssylki = razobrat_ssylku(dovody.ssylka)
    uzel = dovody.uzel or uzel_iz_ssylki

    if uzel:
        dannye = sprosit(f"/files/{fayl}/nodes?ids={urllib.parse.quote(uzel)}", klyuch)
        gnezdo = dannye.get("nodes", {}).get(uzel)
        if not gnezdo:
            sys.exit(f"узла {uzel} в файле нет")
        koren = gnezdo["document"]
        nazvanie = dannye.get("name") or koren.get("name", "")
    else:
        dannye = sprosit(f"/files/{fayl}?depth={dovody.glubina + 1}", klyuch)
        koren = dannye["document"]
        nazvanie = dannye.get("name", "")

    kadry = obkhod(koren, dovody.glubina)
    if not kadry:
        # Узел указан точечно — сам он и есть кадр.
        kadry = [(0, koren)]

    katalog = Path(dovody.katalog)
    katalog.mkdir(parents=True, exist_ok=True)

    print(f"файл: {nazvanie} ({fayl})")
    print(f"кадров в описи: {len(kadry)}")

    # Картинки — только для верхнего уровня: вложенные всё равно видны на них.
    verkhnie = [u for uroven, u in kadry if uroven == 0]
    kartinki: dict[str, str] = {}
    if not dovody.tolko_opis and verkhnie:
        # Figma отдаёт ссылки пачками; больше сотни за раз она не любит.
        for nachalo in range(0, len(verkhnie), 50):
            kusok = verkhnie[nachalo:nachalo + 50]
            ids = ",".join(u["id"] for u in kusok)
            otvet = sprosit(
                f"/images/{fayl}?ids={urllib.parse.quote(ids)}"
                f"&format=png&scale={dovody.masshtab}", klyuch)
            kartinki.update({k: v for k, v in (otvet.get("images") or {}).items() if v})

    stroki = [f"# Макеты Figma: {nazvanie}", "",
              f"Файл `{fayl}`" + (f", узел `{uzel}`" if uzel else ""), "",
              "| Кадр | Размер | Картинка |", "|---|---|---|"]

    for nomer, (uroven, u) in enumerate(kadry, 1):
        otstup = "&nbsp;&nbsp;" * uroven
        imya_fayla = ""
        ssylka_kartinki = kartinki.get(u["id"])
        if ssylka_kartinki:
            imya_fayla = f"{nomer:02d}-{bezopasnoe_imya(u['name'])}.png"
            put = katalog / imya_fayla
            try:
                with urllib.request.urlopen(ssylka_kartinki, timeout=120) as istochnik:
                    put.write_bytes(istochnik.read())
                print(f"  скачано: {imya_fayla}")
            except urllib.error.URLError as beda:
                print(f"  НЕ СКАЧАЛОСЬ: {imya_fayla} — {beda.reason}", file=sys.stderr)
                imya_fayla = ""
        stroki.append(f"| {otstup}{u['name']} | {razmer(u)} | "
                      f"{f'`{imya_fayla}`' if imya_fayla else '—'} |")

    (katalog / "opis.md").write_text("\n".join(stroki) + "\n", encoding="utf-8")
    print(f"опись: {katalog / 'opis.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
