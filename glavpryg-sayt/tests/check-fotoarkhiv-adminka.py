#!/usr/bin/env python3
"""Фотоархив в админке — проверка нажатиями (правило 14).

Вход, сводка архива, отбор списка по подразделу, правка подраздела у слайда с
сохранением и возвратом, **загрузка снимка кнопкой**. Последнее здесь главное:
Orchid собирает адрес загрузки склейкой «хост + метка dashboard-prefix + путь»,
и на сайте в подпути (`/glavpryg`) подпуть из этой склейки выпадал — не
работало ни одно поле загрузки во всей админке. Починка живёт в
`public/js/adminka-podput.js`, и ломается она молча, поэтому проверяется и сама
метка, и настоящая загрузка файла.

    webui/.venv/bin/python glavpryg-sayt/tests/check-fotoarkhiv-adminka.py \\
        --pochta <e-mail> --parol <пароль> [адрес]

⚠️ Посев идёт под именем `samoproverka-*`: убирается ровно он, чужие снимки
проверка не трогает.
"""

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

SAYT = Path("/var/www/glavpryg")
HRANILISHCHE = SAYT / "storage/app/public"
ARKHIV = HRANILISHCHE / "fotoarkhiv"
PHP = "/usr/bin/php8.4"
METKA = "samoproverka"
POSEV = {"tandem": 3, "sportivnyy": 2}
# Экран списка отдаёт постранично — см. paginate() в GalleryItemListScreen.
NA_STRANICE = 50

besedy: list[str] = []
bedy: list[str] = []


def proverit(uslovie: bool, chto: str) -> None:
    (besedy if uslovie else bedy).append(("  ок  " if uslovie else "ПРОВАЛ") + "  " + chto)


def artisan(*dovody: str) -> str:
    gotovo = subprocess.run(
        ["sudo", "-u", "mokeeva", PHP, "artisan", *dovody],
        cwd=SAYT, capture_output=True, text=True, check=True)
    return gotovo.stdout


def kadr(put: Path, podpis: str) -> None:
    from PIL import Image, ImageDraw

    im = Image.new("RGB", (1200, 800), (40, 70, 120))
    risunok = ImageDraw.Draw(im)
    risunok.rectangle([40, 40, 1160, 760], outline=(255, 255, 255), width=6)
    risunok.text((80, 360), podpis, fill=(255, 255, 255))
    im.save(put, quality=85)


def zhdat_adres(st, chast: str, ushli: bool = False, srok: int = 45000) -> None:
    """Дождаться, пока адрес страницы придёт к нужному виду.

    ⚠️ Ждать в админке `wait_for_load_state` нельзя. Orchid ходит по страницам
    через Turbo: тот забирает новую страницу запросом в фоне и подменяет
    содержимое, полной загрузки окна при этом не происходит. Ожидание
    возвращается мгновенно — и на **прежней** странице, с прежним адресом.
    Проверка после этого краснела восемью случаями разом на приложении,
    которое работает: вход, пункт меню, сводка, сохранение карточки.

    Поймали это так: правка меток подпути включила Turbo на ссылках админки
    (раньше он считал их внешними и грузил страницы целиком, потому ожидание
    и срабатывало). Продукт стал работать лучше, а проверка — хуже.

    Поэтому ждём дело: сам адрес. `ushli=True` — дождаться, когда адрес
    перестанет содержать строку (ушли со страницы входа).
    """
    st.wait_for_function(
        "([chast, ushli]) => ushli"
        " ? !location.href.includes(chast)"
        " : location.href.includes(chast)",
        arg=[chast, ushli],
        timeout=srok,
    )


def slaydov_v_baze() -> dict[str, int]:
    """Сколько слайдов уже заведено: всего (ключ «») и по подразделам.

    ⚠️ Проверка идёт по боевому сайту с настоящими снимками заказчика. Считать
    можно только прибавку от своего посева: иначе каждая новая фотография в
    галерее красит проверку ни за что.
    """
    vyvod = artisan("tinker", "--execute", """
        echo 'SVOD:=' . App\\Models\\GalleryItem::count();
        foreach (App\\Models\\GalleryItem::whereNotNull('razdel')
                 ->selectRaw('razdel, count(*) n')->groupBy('razdel')->get() as $r) {
            echo ',' . $r->razdel . '=' . $r->n;
        }
        echo PHP_EOL;
    """)
    stroka = next(s for s in vyvod.splitlines() if s.startswith("SVOD:"))
    bylo = {}
    for kusok in stroka[len("SVOD:"):].split(","):
        imya, _, skolko = kusok.partition("=")
        bylo[imya] = int(skolko)
    return bylo


def poseyannyy_slayd(razdel: str) -> int:
    """Номер своего посеянного слайда: править настоящий снимок заказчика нельзя."""
    vyvod = artisan("tinker", "--execute", f"""
        $vl = Orchid\\Attachment\\Models\\Attachment::where('name', 'like', '{METKA}-%')->pluck('id');
        echo 'SLAYD:' . App\\Models\\GalleryItem::whereIn('image_id', $vl)
            ->where('razdel', '{razdel}')->value('id') . PHP_EOL;
    """)
    return int(next(s for s in vyvod.splitlines() if s.startswith("SLAYD:"))[len("SLAYD:"):])


def mimo_arkhiva() -> set[str]:
    """Файлы хранилища вне архива — датированные папки, куда Orchid кладёт загруженное."""
    return {
        str(f.relative_to(HRANILISHCHE))
        for f in HRANILISHCHE.rglob("*")
        if f.is_file() and not f.is_relative_to(ARKHIV)
    }


def posev() -> None:
    for papka, skolko in POSEV.items():
        (ARKHIV / papka).mkdir(parents=True, exist_ok=True)
        for n in range(1, skolko + 1):
            kadr(ARKHIV / papka / f"{METKA}-{n}.jpg", f"{papka} {n}")
    subprocess.run(["sudo", "chgrp", "-R", "www-data", str(ARKHIV)], check=True)
    subprocess.run(["sudo", "chmod", "-R", "g+rw", str(ARKHIV)], check=True)
    artisan("glavpryg:fotoarkhiv")


def ubrat() -> None:
    artisan("tinker", "--execute", f"""
        $vl = Orchid\\Attachment\\Models\\Attachment::where('name', 'like', '{METKA}-%')->pluck('id');
        App\\Models\\GalleryItem::whereIn('image_id', $vl)->delete();
        Orchid\\Attachment\\Models\\Attachment::whereIn('id', $vl)->forceDelete();
    """)
    for fayl in ARKHIV.glob(f"*/{METKA}-*.jpg"):
        subprocess.run(["sudo", "rm", "-f", str(fayl)], check=True)


def main() -> int:
    razbor = argparse.ArgumentParser()
    razbor.add_argument("adres", nargs="?", default="https://mokeevasky.ru/glavpryg")
    razbor.add_argument("--pochta", required=True)
    razbor.add_argument("--parol", required=True)
    dovody = razbor.parse_args()
    osnova = dovody.adres.rstrip("/")

    bylo = slaydov_v_baze()          # мерка снимается до посева
    posev()
    try:
        with sync_playwright() as p:
            br = p.chromium.launch()
            st = br.new_context(viewport={"width": 1440, "height": 1100}).new_page()
            nedano: list[str] = []
            st.on("response", lambda r: nedano.append(f"{r.status} {r.url}") if r.status >= 400 else None)

            st.goto(f"{osnova}/admin/login", wait_until="load", timeout=60000)
            st.fill('input[name="email"]', dovody.pochta)
            st.fill('input[name="password"]', dovody.parol)
            st.click('button[type="submit"]')
            zhdat_adres(st, "/admin/login", ushli=True)
            proverit("/admin/login" not in st.url, "вход в админку")

            # --- Пункт меню открывается нажатием, а не переходом по адресу ---
            st.get_by_role("link", name="Фотоархив").first.click()
            zhdat_adres(st, "/admin/fotoarkhiv")
            st.wait_for_timeout(1500)       # Turbo дорисовывает содержимое
            proverit(st.url.endswith("/admin/fotoarkhiv"), f"пункт меню ведёт в архив ({st.url})")

            telo = st.inner_text("body")
            for nazvanie in ("Тандем", "Самостоятельный", "Спортивный", "VR"):
                proverit(nazvanie in telo, f"в сводке есть подраздел «{nazvanie}»")
            proverit("fotoarkhiv/tandem" in telo, "в сводке показан путь папки на сервере")

            # --- Подпуть в метке: без него не работает ни одно поле загрузки ---
            prefiks = st.get_attribute('meta[name="dashboard-prefix"]', "content")
            put_sayta = osnova.split("//", 1)[-1].partition("/")[2]
            proverit(prefiks == f"/{put_sayta}/admin" if put_sayta else prefiks == "/admin",
                     f"метка dashboard-prefix знает о подпути: «{prefiks}»")

            # --- Загрузка снимка кнопкой ---
            bylo_mimo = mimo_arkhiva()
            with tempfile.TemporaryDirectory() as vremenno:
                fayl = Path(vremenno) / f"{METKA}-zagruzka.jpg"
                kadr(fayl, "загрузка через админку")
                st.select_option('select[name="razdel"]', "sportivnyy")
                st.locator('input[type="file"]').first.set_input_files(str(fayl))
                st.wait_for_timeout(6000)
                prinyato = st.eval_on_selector_all("[name^=fotki]", "els => els.length")
                proverit(prinyato > 0, f"снимок принят полем загрузки (полей {prinyato})")

                st.get_by_role("button", name="Положить в архив").first.click()
                st.wait_for_load_state("networkidle", timeout=60000)
                st.wait_for_timeout(4000)       # Turbo дорисовывает сводку

            v_papke = sorted(f.name for f in (ARKHIV / "sportivnyy").glob("*.jpg"))
            proverit(f"{METKA}-zagruzka.jpg" in v_papke,
                     f"снимок лёг в папку архива под своим именем: {v_papke}")

            # Снимок лежит в архиве — значит в датированной папке Orchid его
            # больше быть не должно: иначе хранилище копит по дублю на загрузку.
            lishnee = sorted(mimo_arkhiva() - bylo_mimo)
            proverit(not lishnee, f"исходник не остался мимо архива (лишних файлов {len(lishnee)}): {lishnee}")

            # --- Список слайдов: колонка и отбор ---
            # Посев добавил свои слайды плюс один загруженный кнопкой — ждём
            # прибавку к тому, что лежало. Экран отдаёт по 50 строк на страницу.
            st.goto(f"{osnova}/admin/gallery", wait_until="networkidle", timeout=60000)
            vsego = st.locator("table tbody tr").count()
            ozhidaem = min(bylo.get("", 0) + sum(POSEV.values()) + 1, NA_STRANICE)
            proverit(vsego == ozhidaem, f"в списке {vsego} слайдов, ждали {ozhidaem}")
            proverit("Подраздел" in st.inner_text("table thead"), "в списке есть колонка «Подраздел»")

            st.goto(f"{osnova}/admin/gallery?razdel=tandem", wait_until="networkidle", timeout=60000)
            otobrano = st.locator("table tbody tr").count()
            zhdyom_tandem = min(bylo.get("tandem", 0) + POSEV["tandem"], NA_STRANICE)
            proverit(otobrano == zhdyom_tandem,
                     f"отбор «Тандем» дал {otobrano} строк, ждали {zhdyom_tandem}")

            # --- Правка подраздела: сохранить и вернуть обратно ---
            # Правим свой посеянный слайд: настоящие снимки заказчика трогать
            # нельзя, а оборвись проверка посередине — слайд остался бы не в
            # своём подразделе.
            svoy = poseyannyy_slayd("tandem")
            st.goto(f"{osnova}/admin/gallery/{svoy}/edit", wait_until="networkidle", timeout=60000)
            vybor = st.locator('select[name="item[razdel]"]')
            proverit(vybor.count() == 1, "в карточке слайда есть поле «Подраздел»")
            proverit(vybor.input_value() == "tandem", f"в поле стоит подраздел слайда ({vybor.input_value()})")

            vybor.select_option("vr")
            st.get_by_role("button", name="Сохранить").first.click()
            # Сохранение уводит на список (`redirect()->route('platform.gallery')`),
            # так что уход с «/edit» и есть признак, что правка записана.
            zhdat_adres(st, "/edit", ushli=True)

            st.goto(f"{osnova}/admin/gallery?razdel=vr", wait_until="networkidle", timeout=60000)
            stalo = st.locator("table tbody tr").count()
            zhdyom_vr = min(bylo.get("vr", 0) + 1, NA_STRANICE)
            proverit(stalo == zhdyom_vr, f"после правки в «VR» {stalo} строк, ждали {zhdyom_vr}")

            st.goto(f"{osnova}/admin/gallery/{svoy}/edit", wait_until="networkidle", timeout=60000)
            st.locator('select[name="item[razdel]"]').select_option("tandem")
            st.get_by_role("button", name="Сохранить").first.click()
            zhdat_adres(st, "/edit", ushli=True)

            st.goto(f"{osnova}/admin/gallery?razdel=tandem", wait_until="networkidle", timeout=60000)
            vernulos = st.locator("table tbody tr").count()
            proverit(vernulos == zhdyom_tandem,
                     f"после возврата в «Тандеме» {vernulos} строк, ждали {zhdyom_tandem}")

            proverit(not nedano, f"ни один запрос админки не отказал (отказов {len(nedano)}): {nedano[:3]}")
            br.close()
    finally:
        ubrat()

    for stroka in besedy + bedy:
        print(stroka)
    print(f"\nпроверок {len(besedy) + len(bedy)}, провалов {len(bedy)}")
    return 1 if bedy else 0


if __name__ == "__main__":
    sys.exit(main())
