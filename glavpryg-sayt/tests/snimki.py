#!/usr/bin/env python3
"""Снимки страниц сайта «Главпрыг» в настоящем браузере и разбор жалоб консоли.

Открытием страницы проверка не ограничивается: собираются сообщения консоли и
неудавшиеся запросы — именно они показывают, что вёрстка ссылается мимо файла.

    webui/.venv/bin/python glavpryg-sayt/tests/snimki.py [адрес] [--katalog путь]
"""

import argparse
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

STRANICY = [
    ("glavnaya", ""),
    ("uslugi", "services/tandem"),
    ("ceny", "prices"),
    ("sertifikat", "certificate"),
    ("zakaz-sertifikata", "certificate/order"),
    ("blog", "blog"),
    ("o-nas", "about"),
    ("vr-trenazher", "vr-trainer"),
    ("kontakty", "contacts"),
    ("vhod-v-adminku", "admin/login"),
]

# Чужие домены сайту не подчиняются: шрифты Google, карты и счётчики могут
# не ответить с сервера, и их молчание к вёрстке отношения не имеет.
SVOI = "mokeevasky.ru"


def prokrutit(stranica) -> None:
    """Пролистать страницу до низа и вернуться наверх.

    ⚠️ Разделы сайта появляются по прокрутке: до неё у блока `opacity: 0`,
    и класс `is-visible` ему ставит скрипт, когда блок попадает в окно.
    Снимок всей страницы прокрутки не делает — половина полосы выходила
    белой, и это выглядело как пропавшие блоки. Листаем сами.
    """
    vysota = stranica.evaluate("window.innerHeight")
    vsego = stranica.evaluate("document.body.scrollHeight")
    y = 0
    while y < vsego:
        stranica.evaluate(f"window.scrollTo(0, {y})")
        stranica.wait_for_timeout(120)
        y += int(vysota * 0.8)
    stranica.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    stranica.wait_for_timeout(400)
    stranica.evaluate("window.scrollTo(0, 0)")
    stranica.wait_for_timeout(200)


def main() -> int:
    razbor = argparse.ArgumentParser()
    razbor.add_argument("adres", nargs="?", default="https://mokeevasky.ru/glavpryg")
    razbor.add_argument("--katalog", default=None, help="куда класть снимки")
    dovody = razbor.parse_args()

    osnova = dovody.adres.rstrip("/")
    katalog = Path(dovody.katalog or Path(__file__).resolve().parent.parent / "snimki")
    katalog.mkdir(parents=True, exist_ok=True)

    bed = 0
    with sync_playwright() as p:
        brauzer = p.chromium.launch()
        for shirina, podpis in ((1440, "shirokiy"), (390, "telefon")):
            kontekst = brauzer.new_context(
                viewport={"width": shirina, "height": 900},
                device_scale_factor=1,
            )
            for imya, put in STRANICY:
                stranica = kontekst.new_page()
                zhaloby: list[str] = []
                promahi: list[str] = []
                stranica.on(
                    "console",
                    lambda s, z=zhaloby: z.append(f"{s.type}: {s.text}")
                    if s.type in ("error", "warning")
                    else None,
                )
                stranica.on(
                    "requestfailed",
                    lambda z, p=promahi: p.append(f"{z.url} — {z.failure}")
                    if SVOI in z.url
                    else None,
                )
                stranica.on(
                    "response",
                    lambda o, p=promahi: p.append(f"{o.url} — {o.status}")
                    if (o.status >= 400 and SVOI in o.url)
                    else None,
                )

                # ⚠️ Ждём именно `load`, а не `networkidle`. На страницах сайта
                # есть внешние ресурсы, которые с сервера не открываются вовсе
                # (карта, счётчики): сеть «успокаивается» раньше, чем браузер
                # дочитал разметку, и снимок выходит с недостающими блоками.
                # Проверка на этом уже объявляла сайт сломанным — а виновата
                # была она сама: при `load` все блоки на месте (правило 13).
                adres = f"{osnova}/{put}" if put else f"{osnova}/"
                otvet = stranica.goto(adres, wait_until="load", timeout=60000)
                kod = otvet.status if otvet else 0
                stranica.wait_for_timeout(600)
                prokrutit(stranica)
                fayl = katalog / f"{imya}-{podpis}.png"
                stranica.screenshot(path=str(fayl), full_page=(podpis == "shirokiy"))

                itog = "ок" if kod == 200 and not promahi else "ОШИБКА"
                if itog == "ОШИБКА":
                    bed += 1
                print(f"{itog:7} {podpis:9} {adres} → {kod}")
                for stroka in promahi:
                    print(f"          не отдано: {stroka}")
                for stroka in zhaloby:
                    print(f"          консоль: {stroka}")
                stranica.close()
            kontekst.close()
        brauzer.close()

    print(f"\nСнимки: {katalog}")
    print("Всё чисто." if bed == 0 else f"Страниц с бедой: {bed}")
    return 1 if bed else 0


if __name__ == "__main__":
    sys.exit(main())
