"""Снимки вариантов «Глубины» в PNG и сборка их в один PDF.

Каждый вариант снимается как элемент (секция целиком), поэтому страница PDF
получается ровно по размеру варианта, без полей и разрывов посреди плиток.

Запуск (нужны Playwright и Pillow — берутся из venv SkyCenter):
         ../sc-parashyuty/.venv/bin/python maket/shot.py
Выход:   downloads/glubina-a.png, -b.png, -c.png и downloads/glubina-varianty.pdf
"""
import os
import sys

from PIL import Image
from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "downloads")
SCALE = 2  # ретинный масштаб: мелкие подписи читаются и в PDF

# CSS-селектор → имя снимка
SHOTS = [
    ("#var-a", "glubina-a.png"),
    ("#var-b", "glubina-b.png"),
    ("#var-c", "glubina-c.png"),
]


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    paths, errors = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 1000},
                                device_scale_factor=SCALE)
        page.on("console", lambda m: m.type == "error" and errors.append(m.text))
        page.on("requestfailed", lambda r: errors.append("не загрузилось: " + r.url))
        page.goto("file://" + os.path.join(HERE, "index.html"))
        page.evaluate("document.fonts.ready")
        page.wait_for_timeout(800)
        for selector, name in SHOTS:
            path = os.path.join(OUT, name)
            page.locator(selector).screenshot(path=path)
            paths.append(path)
            print(name)
        browser.close()

    # По странице PDF на вариант; снимок 2× при 192 dpi — натуральная величина
    pages = [Image.open(x).convert("RGB") for x in paths]
    pdf = os.path.join(OUT, "glubina-varianty.pdf")
    pages[0].save(pdf, save_all=True, append_images=pages[1:], resolution=96 * SCALE)
    print(os.path.basename(pdf), os.path.getsize(pdf) // 1024, "КБ")

    for e in errors:
        print("ОШИБКА:", e)
    sys.exit(1 if errors else 0)
