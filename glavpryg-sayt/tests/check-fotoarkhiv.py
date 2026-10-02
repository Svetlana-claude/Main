#!/usr/bin/env python3
"""Фотоархив и подразделы блока «Наши фотографии» — проверка нажатиями.

Открыть страницу — ещё не проверить её (правило 14). Проверка сама кладёт
снимки в папки архива, разбирает их командой, жмёт каждую вкладку подраздела
и смотрит, что в слайдере остались только снимки этого подраздела, счётчик
показывает их число и стрелки перелистывают. В конце всё посеянное убирается.

    webui/.venv/bin/python glavpryg-sayt/tests/check-fotoarkhiv.py [адрес]

⚠️ Посев идёт под именем `samoproverka-*`: убирается ровно он, чужие снимки
проверка не трогает.
"""

import argparse
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

SAYT = Path("/var/www/glavpryg")
ARKHIV = SAYT / "storage/app/public/fotoarkhiv"
PHP = "/usr/bin/php8.4"
METKA = "samoproverka"

# Подраздел → сколько снимков посеять. Числа разные нарочно: при 4 и больше
# лента превью едет бесконечной прокруткой, при меньшем — просто подсвечивает
# активный слайд, и оба случая надо задеть.
POSEV = {"tandem": 5, "samostoyatelnyy": 4, "sportivnyy": 2, "vr": 3}

besedy: list[str] = []
bedy: list[str] = []


def proverit(uslovie: bool, chto: str) -> None:
    (besedy if uslovie else bedy).append(("  ок  " if uslovie else "ПРОВАЛ") + "  " + chto)


def artisan(*dovody: str) -> str:
    gotovo = subprocess.run(
        ["sudo", "-u", "mokeeva", PHP, "artisan", *dovody],
        cwd=SAYT, capture_output=True, text=True, check=True)
    return gotovo.stdout


def posev() -> None:
    from PIL import Image, ImageDraw

    for papka, skolko in POSEV.items():
        (ARKHIV / papka).mkdir(parents=True, exist_ok=True)
        for n in range(1, skolko + 1):
            kadr = Image.new("RGB", (1200, 800), (30 + 40 * n, 60, 110))
            risunok = ImageDraw.Draw(kadr)
            risunok.rectangle([40, 40, 1160, 760], outline=(255, 255, 255), width=6)
            risunok.text((80, 360), f"{papka} {n}", fill=(255, 255, 255))
            kadr.save(ARKHIV / papka / f"{METKA}-{n}.jpg", quality=85)
    subprocess.run(["sudo", "chgrp", "-R", "www-data", str(ARKHIV)], check=True)
    subprocess.run(["sudo", "chmod", "-R", "g+rw", str(ARKHIV)], check=True)
    artisan("glavpryg:fotoarkhiv")


def ubrat() -> None:
    """Снести ровно посеянное — слайды, вложения и файлы с меткой."""
    artisan("tinker", "--execute", f"""
        $vl = Orchid\\Attachment\\Models\\Attachment::where('name', 'like', '{METKA}-%')->pluck('id');
        App\\Models\\GalleryItem::whereIn('image_id', $vl)->delete();
        Orchid\\Attachment\\Models\\Attachment::whereIn('id', $vl)->forceDelete();
    """)
    for fayl in ARKHIV.glob(f"*/{METKA}-*.jpg"):
        subprocess.run(["sudo", "rm", "-f", str(fayl)], check=True)


def proverka_v_brauzere(adres: str) -> None:
    vsego = sum(POSEV.values())

    with sync_playwright() as p:
        br = p.chromium.launch()
        st = br.new_context(viewport={"width": 1440, "height": 1000}).new_page()
        oshibki: list[str] = []
        st.on("console", lambda m: oshibki.append(m.text) if m.type == "error" else None)
        st.on("pageerror", lambda e: oshibki.append(str(e)))

        st.goto(adres, wait_until="networkidle", timeout=60000)
        st.locator("#photos").scroll_into_view_if_needed()
        st.wait_for_timeout(1500)

        vkladki = st.locator("[data-photo-tab]")
        proverit(vkladki.count() == len(POSEV) + 1,
                 f"вкладок {vkladki.count()}, ждали {len(POSEV) + 1} (Все и четыре подраздела)")

        for razdel, skolko in [("", vsego)] + list(POSEV.items()):
            st.locator(f'[data-photo-tab="{razdel}"]').click()
            st.wait_for_timeout(1200)
            imya = razdel or "Все"

            # Собственные слайды, без копий, которые Swiper штампует для ленты
            svoi = st.eval_on_selector_all(
                ".photo-main .swiper-slide:not(.swiper-slide-duplicate)",
                "els => els.map(e => e.dataset.razdel)")
            proverit(len(svoi) == skolko, f"{imya}: слайдов {len(svoi)}, ждали {skolko}")
            if razdel:
                proverit(all(r == razdel for r in svoi),
                         f"{imya}: все слайды своего подраздела (нашлось {sorted(set(svoi))})")

            schetchik = st.locator("[data-photo-counter]").inner_text()
            proverit(schetchik.endswith(f"/ {skolko}"), f"{imya}: счётчик «{schetchik}»")

            # Картинка должна грузиться, а не висеть битой ссылкой
            gotova = st.eval_on_selector(".photo-main .swiper-slide-active img",
                                         "e => e.complete && e.naturalWidth > 0")
            proverit(bool(gotova), f"{imya}: картинка активного слайда загрузилась")

            if skolko > 1:
                bylo = schetchik
                st.locator("[data-photo-next]").click()
                st.wait_for_timeout(1200)
                stalo = st.locator("[data-photo-counter]").inner_text()
                proverit(bylo != stalo, f"{imya}: стрелка «вперёд» перелистнула ({bylo} → {stalo})")

        st.locator('[data-photo-tab=""]').click()
        st.wait_for_timeout(1200)
        vernulos = st.locator("[data-photo-counter]").inner_text()
        proverit(vernulos.endswith(f"/ {vsego}"), f"возврат на «Все»: счётчик «{vernulos}»")

        proverit(not oshibki, f"консоль чистая (ошибок {len(oshibki)}): {oshibki[:3]}")
        br.close()


def main() -> int:
    razbor = argparse.ArgumentParser()
    razbor.add_argument("adres", nargs="?", default="https://mokeevasky.ru/glavpryg/")
    dovody = razbor.parse_args()

    posev()
    try:
        proverka_v_brauzere(dovody.adres)
    finally:
        ubrat()

    for stroka in besedy + bedy:
        print(stroka)
    print(f"\nпроверок {len(besedy) + len(bedy)}, провалов {len(bedy)}")
    return 1 if bedy else 0


if __name__ == "__main__":
    sys.exit(main())
