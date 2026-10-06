"""Архив вариантов сертификата → «Файлы проекта» (downloads/sertifikaty/).

Сайт кладёт по образцу каждого варианта (artisan sertifikaty:obrazcy), html-варианты
здесь же печатаются в PDF — чтобы всё открывалось без инструментов разработчика.

    webui/.venv/bin/python glavpryg-sayt/tools/sertifikaty-arkhiv.py
"""
import pathlib, subprocess
from playwright.sync_api import sync_playwright

KUDA = pathlib.Path(__file__).resolve().parents[1] / "downloads" / "sertifikaty"
subprocess.run(["/usr/bin/php8.4", "artisan", "sertifikaty:obrazcy", str(KUDA)],
               cwd="/var/www/glavpryg", check=True)
html = sorted(KUDA.glob("*.html"))
if html:
    with sync_playwright() as p:
        br = p.chromium.launch()
        st = br.new_page()
        for f in html:
            st.goto(f.as_uri(), wait_until="networkidle")
            st.emulate_media(media="print")
            st.pdf(path=str(f.with_suffix(".pdf")), prefer_css_page_size=True, print_background=True)
            print(f.name, "→", f.with_suffix(".pdf").name)
        br.close()
print("архив:", KUDA)
