#!/usr/bin/env python3
"""Обложка 3D-просмотрщика: снимок первого кадра модели → `oblozhka.webp`.

Обложка — то, что видит посетитель до нажатия «Покрутить в 3D», поэтому она
снимается с той же сцены и той же камеры, что и живая модель: при запуске
картинка подменяется 3D без скачка. Метки и подсказка на снимок не попадают.

    <venv с playwright>/bin/python oblozhka.py <dist> <система>
"""
import functools
import http.server
import io
import sys
import threading
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

SHIR, VYS = 900, 1000


def main():
    dist = Path(sys.argv[1]).resolve()
    sistema = sys.argv[2]
    class Tihiy(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

    obr = functools.partial(Tihiy, directory=str(dist))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), obr)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    adres = f"http://127.0.0.1:{srv.server_port}/{sistema}/index.html"
    oshibki = []
    with sync_playwright() as p:
        br = p.chromium.launch(args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
        st = br.new_page(viewport={"width": 1400, "height": 1300}, device_scale_factor=1.5)
        st.on("pageerror", lambda e: oshibki.append(str(e)))
        # обложки ещё нет — её 404 и есть причина запуска, остальное — ошибка
        st.on("response", lambda r: r.status >= 400 and "oblozhka" not in r.url
              and oshibki.append(f"{r.status} {r.url}"))
        st.goto(adres)
        st.add_style_tag(content=".m3d-metki,.m3d-podskazka{display:none!important}")
        st.click(".m3d-zapusk")
        st.wait_for_selector("[data-gotovo]", timeout=60000)
        st.wait_for_timeout(800)
        png = st.locator(".m3d-okno").screenshot()
        br.close()
    srv.shutdown()
    if oshibki:
        sys.exit("Ошибки на странице:\n" + "\n".join(oshibki))
    img = Image.open(io.BytesIO(png)).convert("RGB").resize((SHIR, VYS), Image.LANCZOS)
    put = dist / sistema / "oblozhka.webp"
    img.save(put, "WEBP", quality=78, method=6)
    print(f"{sistema}/{put.name}: {put.stat().st_size // 1024} КБ")


if __name__ == "__main__":
    main()
