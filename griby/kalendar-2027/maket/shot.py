"""Снимки и PDF вариантов календаря.

Запуск:  /home/mokeeva/main/exchange/pwenv/bin/python maket/shot.py
Выход — в «Файлы проекта», griby/downloads/kalendar-2027/ (не версионируется):
  variant-X-sborka.png — вся сборка «трио», variant-X-shapka.png — шапка крупно,
  variant-X.pdf — сборка векторным PDF 297×728 мм (под печать нужен CMYK и вылеты,
  см. opisanie-variantov.md).
"""
import os

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
VYDACHA = os.path.abspath(os.path.join(HERE, "..", "..", "downloads", "kalendar-2027"))
VARIANTY = os.environ.get("VARIANTY", "abcdef")
PAGE = "file://" + os.path.join(HERE, "index.html")

if __name__ == "__main__":
    os.makedirs(VYDACHA, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for scale, sel, imya in ((1.4, ".trio", "sborka"), (2.6, ".shapka", "shapka")):
            page = browser.new_page(viewport={"width": 1300, "height": 1000}, device_scale_factor=scale)
            page.goto(PAGE)
            page.wait_for_function("document.body.classList.contains('gotovo')")
            page.wait_for_timeout(800)
            for v in VARIANTY:
                put = os.path.join(VYDACHA, f"variant-{v}-{imya}.png")
                page.locator(f"#var-{v} {sel}").screenshot(path=put)
                print(put)
            page.close()
        page = browser.new_page()
        for v in VARIANTY:
            page.goto(PAGE + "?v=" + v)
            page.wait_for_function("document.body.classList.contains('gotovo')")
            page.wait_for_timeout(800)
            put = os.path.join(VYDACHA, f"variant-{v}.pdf")
            page.pdf(path=put, width="297mm", height="728mm", print_background=True,
                     margin={"top": "0", "right": "0", "bottom": "0", "left": "0"})
            print(put)
        browser.close()
