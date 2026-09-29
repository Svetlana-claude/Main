#!/usr/bin/env python3
"""Проверка админки нажатиями: вход, переходы по разделам, правка настройки.

Открыть окно — ещё не проверить его (правило 14). Здесь проверка заходит под
администратором, открывает разделы и действительно **сохраняет** правку, а потом
убеждается, что она видна на самом сайте и возвращает прежнее значение назад.

    webui/.venv/bin/python glavpryg-sayt/tests/check-adminka.py \
        --pochta <e-mail> --parol <пароль> [адрес]
"""

import argparse
import sys

from playwright.sync_api import sync_playwright

RAZDELY = [
    ("Заявки", "admin/leads"),
    ("Блог", "admin/blog/posts"),
    ("Услуги", "admin/services"),
    ("Цены", "admin/prices"),
    ("Настройки сайта", "admin/settings"),
    ("Наши фотографии", "admin/gallery"),
]


def sohranit(stranica) -> None:
    """Нажать «Сохранить» и дождаться, пока правка действительно уйдёт.

    ⚠️ Одного `networkidle` мало: админка Orchid отправляет форму через Turbo,
    и страница успевает «успокоиться» раньше, чем ответ сервера записан в базу.
    Проверка из-за этого уходила на сайт слишком рано и объявляла дефектом
    собственную спешку. Ждём именно подтверждения «Настройки сохранены».
    """
    stranica.get_by_role("button", name="Сохранить").first.click()
    stranica.get_by_text("Настройки сохранены").first.wait_for(timeout=30000)
    stranica.wait_for_load_state("networkidle", timeout=60000)


def main() -> int:
    razbor = argparse.ArgumentParser()
    razbor.add_argument("adres", nargs="?", default="https://mokeevasky.ru/glavpryg")
    razbor.add_argument("--pochta", required=True)
    razbor.add_argument("--parol", required=True)
    dovody = razbor.parse_args()
    osnova = dovody.adres.rstrip("/")

    bed = 0
    with sync_playwright() as p:
        brauzer = p.chromium.launch()
        stranica = brauzer.new_context(viewport={"width": 1440, "height": 900}).new_page()

        # 1. Вход именно нажатием кнопки, а не запросом
        stranica.goto(f"{osnova}/admin/login", wait_until="load", timeout=60000)
        stranica.fill('input[name="email"]', dovody.pochta)
        stranica.fill('input[name="password"]', dovody.parol)
        stranica.click('button[type="submit"]')
        stranica.wait_for_load_state("networkidle", timeout=60000)
        if "/admin/login" in stranica.url:
            print("ОШИБКА  вход не прошёл — остались на странице входа")
            return 1
        print(f"ок      вход выполнен → {stranica.url}")

        # 2. Разделы открываются и не роняют приложение
        for imya, put in RAZDELY:
            otvet = stranica.goto(f"{osnova}/{put}", wait_until="load", timeout=60000)
            kod = otvet.status if otvet else 0
            # Orchid показывает свою страницу ошибки с кодом 200, поэтому
            # смотрим ещё и на содержимое.
            razmetka = stranica.content()
            sryv = any(s in razmetka for s in ("Server Error", "Whoops", "Ошибка сервера"))
            if kod != 200 or sryv:
                print(f"ОШИБКА  {imya}: {kod}{' — страница ошибки' if sryv else ''}")
                bed += 1
            else:
                print(f"ок      {imya} открывается")

        # 3. Правка сохраняется и доходит до сайта — вся цепочка «админка →
        #    база → вёрстка», а не только запись в базу.
        #
        #    ⚠️ Берём адрес аэродрома и смотрим его на странице цен. Телефон
        #    для этого не годится, хотя он и просится первым: в поставке он
        #    зашит в разметку девяти шаблонов, и настройка «Телефон в шапке»
        #    на сайт не влияет вовсе (доходит только до страницы оплаты
        #    сертификата). На этом проверка уже падала — обвиняя не того;
        #    дефект записан в current_questions.md. Страница цен —
        #    единственная, где сведения из настроек действительно выводятся.
        stranica.goto(f"{osnova}/admin/settings", wait_until="load", timeout=60000)
        # Поля разложены по вкладкам: в разметке они есть все, но скрытое поле
        # не заполнить — до него сперва надо добраться нажатием, как человеку.
        stranica.get_by_role("tab", name="Общее").first.click()
        pole = stranica.locator('input[name="setting[address]"]').first
        if pole.count() == 0:
            print("ОШИБКА  в настройках не найдено поле «Адрес»")
            return 1
        bylo = pole.input_value()
        proba = "Проба связи админки и сайта"
        pole.fill(proba)
        sohranit(stranica)

        stranica.goto(f"{osnova}/prices", wait_until="load", timeout=60000)
        vidno = proba in stranica.content()
        print(("ок      " if vidno else "ОШИБКА  ") + "правка из админки видна на сайте")
        bed += 0 if vidno else 1

        # Возвращаем как было — проверка не должна оставлять следов
        stranica.goto(f"{osnova}/admin/settings", wait_until="load", timeout=60000)
        stranica.get_by_role("tab", name="Общее").first.click()
        stranica.locator('input[name="setting[address]"]').first.fill(bylo)
        sohranit(stranica)
        print(f"ок      прежний адрес возвращён: {bylo}")

        brauzer.close()

    print("\nВсё чисто." if bed == 0 else f"\nБед: {bed}")
    return 1 if bed else 0


if __name__ == "__main__":
    sys.exit(main())
