"""Снимки макетов: страница открывается в Chromium, нужные блоки снимаются в PNG.

Нужно, чтобы показать варианты тому, кто не открывает HTML: картинка ложится
в письмо, в PDF и в «Файлы проекта». Снимается именно элемент, а не окно, —
размер PNG получается ровно по макету, без полей страницы.

Запуск:  .venv/bin/python maket/shot.py
Выход:   downloads/variant-d.png, variant-e.png, variant-f.png, shrifty.png
"""
import os

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "downloads")

# Файл страницы → CSS-селектор → имя снимка
SHOTS = [
    ("sertifikat-varianty.html", "#var-d .b-cert", "variant-d.png"),
    ("sertifikat-varianty.html", "#var-e .e-cert", "variant-e.png"),
    ("sertifikat-varianty.html", "#var-f .f-cert", "variant-f.png"),
    ("sertifikat-varianty.html", "#fonts .fonts-grid", "shrifty-varianty.png"),
]

SCALE = 2  # ретинный масштаб: на экране и в печати видно мелкие подписи


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1400, "height": 1000},
                                device_scale_factor=SCALE)
        opened = None
        for source, selector, name in SHOTS:
            path = os.path.abspath(os.path.join(HERE, source))
            if path != opened:
                page.goto("file://" + path)
                page.wait_for_timeout(1200)  # веб-шрифты
                opened = path
            page.locator(selector).screenshot(path=os.path.join(OUT, name))
            print(name)
        browser.close()
