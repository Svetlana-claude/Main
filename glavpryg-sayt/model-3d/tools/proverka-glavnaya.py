"""Проверка блока «Парашюты» на главной нажатиями: карточка → окно поверх сайта → 3D → закрытие.

    <venv с playwright>/bin/python proverka-glavnaya.py [адрес главной] [--snimki каталог]

По умолчанию — https://mokeevasky.ru/glavpryg/. Проверяется на компьютере и на телефоне:
- до нажатия ни модель, ни код показа не грузятся (превью — можно), превью загружены;
- нажатие карточки открывает модальное окно с заголовком системы, прокрутка сайта заперта;
- в окне встроенная страница: шапки и кнопки запуска не видно, 3D запущено само,
  метки видны, нажатие метки открывает карточку детали;
- окно не шире экрана, и сайт по горизонтали не едет;
- Esc и крестик закрывают окно, iframe убирается, фокус возвращается на карточку;
- в консоли (сайта и окна) нет ошибок.
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

TYAZHELOE = ("model.glb", "prosmotr-")
SISTEMY = (("sportivnaya-sistema", "Спортивная система"), ("lesnik-3", "Лесник-3"))
FLAGI = ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"]


def progon(br, adres, shirina, vysota, snimki, metka_):
    proval = []

    def nado(usl, chto):
        print(f"  {'ок ' if usl else 'НЕТ'} [{metka_}] {chto}")
        if not usl:
            proval.append(f"{metka_}: {chto}")

    kont = br.new_context(viewport={"width": shirina, "height": vysota})
    st = kont.new_page()
    oshibki, zaprosy = [], []
    st.on("console", lambda m: m.type == "error" and oshibki.append(m.text))
    st.on("pageerror", lambda e: oshibki.append(str(e)))
    st.on("request", lambda r: zaprosy.append(r.url))
    st.goto(adres, wait_until="networkidle")
    st.locator("#parashyuty").scroll_into_view_if_needed()
    st.wait_for_timeout(800)
    nado(not any(t in u for u in zaprosy for t in TYAZHELOE), "до нажатия модель и код показа не грузятся")
    nado(st.evaluate("document.documentElement.scrollWidth <= innerWidth"), "сайт не едет по горизонтали")
    for kl, nazv in SISTEMY:
        img = st.locator(f'[data-par*="/{kl}/"] img')
        img.scroll_into_view_if_needed()
        st.wait_for_timeout(300)
        nado(img.evaluate("i => i.complete && i.naturalWidth > 0 && new URL(i.src).pathname.endsWith('/prevyu.webp')"),
             f"{nazv}: превью на карточке загружено")

    for kl, nazv in SISTEMY:
        karta = st.locator(f'[data-par*="/{kl}/"]')
        karta.click()
        okno = st.locator(".gp-par-okno")
        nado(okno.evaluate("o => o.open && o.matches(':modal')"), f"{nazv}: окно открыто модально")
        nado(st.text_content("#gp-par-zagolovok") == nazv, f"{nazv}: заголовок окна")
        nado(st.evaluate("getComputedStyle(document.documentElement).overflow === 'hidden'"), f"{nazv}: прокрутка сайта заперта")
        r = okno.bounding_box()
        nado(r["x"] >= 0 and r["x"] + r["width"] <= shirina and r["y"] + r["height"] <= vysota, f"{nazv}: окно в пределах экрана {r}")

        fr = st.frame_locator(".gp-par-ramka iframe")
        try:
            fr.locator(".m3d-gotovo").wait_for(timeout=30000)
            gotovo = True
        except Exception:
            gotovo = False
        nado(gotovo, f"{nazv}: 3D запущено само, без кнопки")
        nado(fr.locator(".m3d-shapka h1").evaluate("e => e.getBoundingClientRect().width <= 1"), f"{nazv}: шапка страницы скрыта (заголовок даёт окно)")
        nado(not fr.locator(".m3d-zapusk").is_visible(), f"{nazv}: кнопки «Покрутить в 3D» нет")
        st.wait_for_timeout(1500)
        vidny = fr.locator(".m3d-metka:not(.skryta)").count()
        nado(vidny >= 3, f"{nazv}: метки видны ({vidny})")
        fr.locator(".m3d-metka:not(.skryta)").first.click()
        st.wait_for_timeout(800)
        imya = fr.locator(".m3d-k-imya").text_content()
        nado(bool(imya), f"{nazv}: метка → карточка «{imya}»")
        if snimki:
            st.screenshot(path=str(snimki / f"{metka_}-{kl}.png"))

        # закрытие: спорт — Esc, лесник — крестик
        if kl == "lesnik-3":
            st.click(".gp-par-zakryt")
        else:
            st.keyboard.press("Escape")
        st.wait_for_timeout(300)
        nado(not okno.evaluate("o => o.open"), f"{nazv}: окно закрыто ({'крестик' if kl == 'lesnik-3' else 'Esc'})")
        nado(st.locator(".gp-par-ramka iframe").count() == 0, f"{nazv}: iframe убран")
        nado(karta.evaluate("e => e === document.activeElement"), f"{nazv}: фокус вернулся на карточку")
        nado(st.evaluate("getComputedStyle(document.documentElement).overflow !== 'hidden'"), f"{nazv}: прокрутка сайта вернулась")

    nado(not oshibki, f"консоль без ошибок {oshibki}")
    kont.close()
    return proval


def main():
    argi = sys.argv[1:]
    snimki = None
    if "--snimki" in argi:
        i = argi.index("--snimki")
        snimki = Path(argi[i + 1])
        snimki.mkdir(parents=True, exist_ok=True)
        del argi[i:i + 2]
    adres = argi[0] if argi else "https://mokeevasky.ru/glavpryg/"
    with sync_playwright() as p:
        br = p.chromium.launch(args=FLAGI)
        proval = progon(br, adres, 1280, 900, snimki, "компьютер") + progon(br, adres, 390, 844, snimki, "телефон")
        br.close()
    if proval:
        print("Итог: НЕ в порядке\n  " + "\n  ".join(proval))
        sys.exit(1)
    print("Итог: всё в порядке")


if __name__ == "__main__":
    main()
