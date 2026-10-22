#!/usr/bin/env python3
"""Проверка 3D-страниц нажатиями: обложка → «Покрутить в 3D» → метка → карточка.

    <venv с playwright>/bin/python proverka-3d.py <каталог dist или адрес …/model-3d> [--snimki каталог]

Проверяются обе системы (SISTEMY ниже), на компьютере и на телефоне.
Что проверяется:
- до нажатия страница не тянет ни модель, ни код показа (лёгкая загрузка);
- кнопка запускает показ без ошибок в консоли, обложка уходит;
- метки видны спереди, а метки задних деталей спереди скрыты (перекрытие работает);
- нажатие передней метки открывает карточку детали и отмечает её в списке;
- нажатие строки списка задней детали облетает к ней, и её метка становится видна;
- крестик закрывает карточку;
- на узком экране (телефон) всё то же без горизонтальной прокрутки.
С `--snimki` кладёт снимки шагов — смотреть глазами.
"""
import argparse
import functools
import http.server
import sys
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

TYAZHELOE = ("model.glb", "prosmotr-")
# HTML, стиль, лёгкий код и обложка — без распаковки; с запасом под правки текста
PREDEL = 48 * 1024

# что видно спереди, что сзади; передняя метка для нажатия и задняя деталь из списка
SISTEMY = {
    "sportivnaya-sistema": {"speredi": {10, 11, 12}, "szadi": {2, 3},
                            "metka": (10, "podushka", "Подушка отцепки"),
                            "spisok": ("bobyshka", 3, "Бобышка медузы")},
    "lesnik-3": {"speredi": {7, 8, 12}, "szadi": {2, 3},
                 "metka": (8, "kolco_zps", "Кольцо раскрытия запасного"),
                 "spisok": ("zamok", 2, "Двухконусный замок")},
}


def podnyat_server(dist):
    class Tihiy(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Tihiy, directory=str(dist)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{srv.server_port}"


def vidimye(st):
    return st.eval_on_selector_all(".m3d-metka:not(.skryta)", "els => els.map(e => +e.textContent)")


def progon(br, adres, shirina, vysota, snimki, metka_, zh):
    oshibki, zaprosy = [], []
    st = br.new_page(viewport={"width": shirina, "height": vysota})
    st.on("pageerror", lambda e: oshibki.append(str(e)))
    st.on("console", lambda m: m.type == "error" and oshibki.append(m.text))
    st.on("request", lambda r: zaprosy.append(r.url))
    st.goto(adres)
    st.wait_for_load_state("networkidle")
    proval = []

    def nado(uslovie, chto):
        print(("  ок   " if uslovie else "  СБОЙ ") + f"[{metka_}] {chto}")
        if not uslovie:
            proval.append(chto)

    lishnee = [u for u in zaprosy if any(t in u for t in TYAZHELOE)]
    nado(not lishnee, f"до нажатия модель и код показа не запрашиваются ({len(zaprosy)} запросов)")
    # вшитый в страницу код показа отдельным запросом не виден — меряем вес целиком
    ves = st.evaluate("performance.getEntriesByType('navigation').concat(performance.getEntriesByType('resource'))"
                      ".reduce((s, e) => s + e.decodedBodySize, 0)")
    nado(ves < PREDEL, f"страница до нажатия весит {ves // 1024} КБ (предел {PREDEL // 1024} КБ)")
    shir_doc = st.evaluate("document.documentElement.scrollWidth")
    nado(shir_doc <= shirina, f"нет горизонтальной прокрутки ({shir_doc} ≤ {shirina})")

    st.click(".m3d-zapusk")
    st.wait_for_selector("[data-gotovo]", timeout=60000)
    st.wait_for_timeout(700)
    nado(st.is_hidden(".m3d-zapusk"), "кнопка запуска ушла")
    v = vidimye(st)
    nado(zh["speredi"].issubset(v), f"спереди видны {sorted(zh['speredi'])}: {v}")
    nado(not (zh["szadi"] & set(v)), f"задние {sorted(zh['szadi'])} спереди скрыты")
    if snimki:
        st.screenshot(path=str(snimki / f"{metka_}-1-zapusk.png"))

    n, kl, nazv = zh["metka"]

    st.locator(f".m3d-metka:text-is('{n}')").first.click()
    st.wait_for_timeout(1000)
    imya = st.text_content(".m3d-k-imya")
    nado(imya == nazv, f"метка {n} → карточка «{imya}»")
    nado(st.locator(f'.m3d-spisok li.vybrana[data-detal="{kl}"]').count() == 1, f"в списке отмечена «{nazv}»")
    if snimki:
        st.screenshot(path=str(snimki / f"{metka_}-2-metka.png"))

    kl, n, nazv = zh["spisok"]
    st.click(f'.m3d-spisok [data-detal="{kl}"] button')
    # облёт 0,7 с и уточнение меток в покое; программный WebGL рисует медленно — ждём условие
    try:
        st.wait_for_function("[...document.querySelectorAll('.m3d-metka:not(.skryta)')]"
                             f".some(e => e.textContent === '{n}')", timeout=5000)
    except Exception:
        pass
    v = vidimye(st)
    nado(st.text_content(".m3d-k-imya") == nazv and n in v, f"список → «{nazv}», её метка видна: {v}")
    if snimki:
        st.screenshot(path=str(snimki / f"{metka_}-3-spisok.png"))

    st.click(".m3d-k-zakryt")
    st.wait_for_timeout(900)
    nado(st.is_hidden(".m3d-kartochka"), "крестик закрыл карточку")
    nado(not oshibki, f"консоль без ошибок {oshibki or ''}")
    st.close()
    return proval


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cel")
    ap.add_argument("--snimki")
    a = ap.parse_args()
    adres = a.cel if a.cel.startswith("http") else podnyat_server(Path(a.cel).resolve())
    snimki = Path(a.snimki) if a.snimki else None
    if snimki:
        snimki.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        br = p.chromium.launch(args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
        proval = []
        for sis, zh in SISTEMY.items():
            for shir, vys, kak in ((1280, 900, "компьютер"), (390, 844, "телефон")):
                proval += progon(br, f"{adres.rstrip('/')}/{sis}/index.html", shir, vys, snimki, f"{sis} {kak}", zh)
        br.close()
    print("Итог: " + ("всё в порядке" if not proval else f"сбоев {len(proval)}"))
    sys.exit(1 if proval else 0)


if __name__ == "__main__":
    main()
