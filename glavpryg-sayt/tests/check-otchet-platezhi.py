#!/usr/bin/env python3
"""Проверка нажатиями «Отчёта по платежам» в админке: кнопка на главной, три таблицы,
внести платёж через окно (срок услуги сдвигается), удалить его, правка услуги и возврат.

    webui/.venv/bin/python glavpryg-sayt/tests/check-otchet-platezhi.py --pochta <e-mail> --parol <пароль> [адрес]
"""
import argparse
import sys

from playwright.sync_api import sync_playwright

oshibki = []


def proverit(usl, tekst):
    print(("OK   " if usl else "FAIL ") + tekst, flush=True)
    if not usl:
        oshibki.append(tekst)


def stroka(pg, tekst):
    return pg.locator("tr", has_text=tekst).first


def main():
    a = argparse.ArgumentParser()
    a.add_argument("adres", nargs="?", default="https://mokeevasky.ru/glavpryg")
    a.add_argument("--pochta", required=True)
    a.add_argument("--parol", required=True)
    d = a.parse_args()
    osn = d.adres.rstrip("/")
    with sync_playwright() as p:
        br = p.chromium.launch()
        pg = br.new_context(viewport={"width": 1440, "height": 900}).new_page()
        konsol = []
        pg.on("pageerror", lambda e: konsol.append(str(e)))
        pg.on("dialog", lambda dl: dl.accept())
        pg.goto(f"{osn}/admin/login", wait_until="load")
        pg.fill('input[name="email"]', d.pochta)
        pg.fill('input[name="password"]', d.parol)
        pg.click('button[type="submit"]')
        # Вход уходит через Turbo: networkidle наступает раньше перехода — ждём сам переход
        pg.wait_for_url("**/admin/main", timeout=30000)

        # 1. Кнопка на главной админки
        pg.goto(f"{osn}/admin/main")
        pg.get_by_role("link", name="ОТЧЁТ ПО ПЛАТЕЖАМ", exact=True).click()
        pg.wait_for_url("**/admin/payment-report")
        pg.wait_for_load_state("networkidle")
        proverit(True, "кнопка «ОТЧЁТ ПО ПЛАТЕЖАМ» открывает отчёт")
        for z in ("Оплаты", "История платежей", "Работа сайта"):
            proverit(pg.get_by_text(z, exact=True).count() >= 1, f"таблица «{z}»")
        for u in ("Домен glavprig.ru", "Домен главпрыг.рф", "Хостинг сайта", "Хранилище копий сайта"):
            proverit(pg.get_by_text(u, exact=True).count() >= 1, f"строка «{u}»")
        proverit(pg.locator("tr", has_text="Страница /certificate/order").count() >= 1, "в «Работе сайта» есть строки проверки")
        pg.screenshot(path="/tmp/otchet-platezhi.png", full_page=True)

        # 2. Внести платёж за хранилище копий кнопкой в строке
        stroka(pg, "Хранилище копий сайта").get_by_role("button", name="Внести платёж").click()
        okno = pg.locator(".modal.show")
        okno.wait_for()
        okno.locator('input[name="platezh[summa]"]').fill("12345")
        okno.locator('input[name="platezh[srok]"]').fill("проверка")
        okno.locator('input[name="platezh[zametka]"]').fill("проверка-удалить")
        okno.locator('input[name="platezh[oplacheno_do]"]').fill("2030-01-15")
        okno.get_by_role("button", name="Сохранить").click()
        pg.get_by_text("Платёж внесён").wait_for(timeout=15000)
        pg.wait_for_load_state("networkidle")
        proverit(pg.locator("tr", has_text="проверка-удалить").count() == 1, "платёж появился в истории")
        t = stroka(pg, "Хранилище копий сайта").inner_text()
        proverit("15.01.2030" in t, "срок хранилища сдвинулся на 15.01.2030")
        proverit("12 345 ₽" in t, "последний платёж — 12 345 ₽")

        # 3. Удалить платёж
        stroka(pg, "проверка-удалить").get_by_role("button", name="Удалить").click()
        pg.wait_for_timeout(800)
        conf = pg.locator(".modal.show button", has_text="Удалить")
        if conf.count():
            conf.first.click()
        pg.get_by_text("Платёж удалён").wait_for(timeout=15000)
        pg.wait_for_load_state("networkidle")
        proverit(pg.locator("tr", has_text="проверка-удалить").count() == 0, "платёж удалён")

        # 4. Изменить услугу: поставщика на время сменить и вернуть, срок очистить
        for postavshchik in ("Проверка-хостинг", "Selectel"):
            stroka(pg, "Хранилище копий сайта").get_by_role("button", name="Изменить").click()
            okno = pg.locator(".modal.show")
            okno.wait_for()
            pg.wait_for_timeout(500)
            okno.locator('input[name="usluga[postavshchik]"]').fill(postavshchik)
            proverit(okno.locator('input[name="usluga[oplacheno_do]"]').input_value() != "" or postavshchik == "Selectel",
                     "в окне «Изменить» подставлен текущий срок")
            okno.locator('input[name="usluga[oplacheno_do]"]').fill("")
            okno.get_by_role("button", name="Сохранить").click()
            okno.wait_for(state="hidden")
            pg.get_by_text("Сохранено").first.wait_for(timeout=15000)
            pg.wait_for_load_state("networkidle")
            pg.reload()
            pg.wait_for_load_state("networkidle")
            proverit(postavshchik in stroka(pg, "Хранилище копий сайта").inner_text(),
                     f"поставщик сменился на «{postavshchik}»")
        proverit("срок неизвестен" in stroka(pg, "Хранилище копий сайта").inner_text(), "срок хранилища снова пустой")
        # Правка не задела соседние услуги (01.11.2026: окно сохраняло в чужую строку)
        proverit(pg.get_by_text("Хранилище копий сайта", exact=True).count() == 1, "строка хранилища одна")
        proverit("01.11.2027" in stroka(pg, "Домен glavprig.ru").inner_text(), "домен glavprig.ru не тронут")
        proverit(not konsol, f"консоль без ошибок {konsol}")
        br.close()
    print("ИТОГ:", f"провалов {len(oshibki)}" if oshibki else "всё OK")
    return 1 if oshibki else 0


if __name__ == "__main__":
    sys.exit(main())
