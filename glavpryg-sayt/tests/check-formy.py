#!/usr/bin/env python3
"""Проверка форм заявок нажатием: посетитель отправил — админка получила.

Смысл сайта — заявки. Открыть страницу и увидеть на ней форму (правило 14)
ещё ничего не значит: форма может не иметь ни адреса отправки, ни имён у
полей, и кнопка будет просто перезагружать страницу. Здесь проверка
действительно **заполняет и отправляет** форму, а потом заходит в админку и
убеждается, что заявка дошла, — после чего убирает свой след.

    webui/.venv/bin/python glavpryg-sayt/tests/check-formy.py \\
        --pochta <e-mail> --parol <пароль> [адрес]
"""

import argparse
import sys
import time

from playwright.sync_api import sync_playwright

# Страницы, на которых стоит блок «Сертификат на мечту» с полями ФИО и
# телефона. В поставке эта форма не отправляет ничего (см. ниже), и проверка
# перечисляет их все, чтобы размер беды был виден сразу.
STRANICY_S_FORMOY = ["", "services/tandem", "about", "vr-trainer"]


def opisat_formy(stranica) -> list[dict]:
    """Собрать со страницы все формы с их адресом отправки и именами полей."""
    return stranica.locator("form").evaluate_all(
        "u => u.map(f => ({"
        " action: f.getAttribute('action'),"
        " method: f.getAttribute('method'),"
        " polya: Array.from(f.querySelectorAll('input,textarea,select'))"
        "        .map(e => e.name).filter(Boolean)"
        "}))"
    )


def main() -> int:
    razbor = argparse.ArgumentParser()
    razbor.add_argument("adres", nargs="?", default="https://mokeevasky.ru/glavpryg")
    razbor.add_argument("--pochta", required=True)
    razbor.add_argument("--parol", required=True)
    dovody = razbor.parse_args()
    osnova = dovody.adres.rstrip("/")

    bed = 0
    metka = f"Проба оснастки {time.strftime('%d.%m %H:%M:%S')}"

    with sync_playwright() as p:
        brauzer = p.chromium.launch()
        kontekst = brauzer.new_context(viewport={"width": 1440, "height": 900})
        stranica = kontekst.new_page()

        # 1. Рабочая форма заявки: страница цен, блок «Забронировать прыжок».
        #    Отправляем по-настоящему — нажатием, как посетитель.
        stranica.goto(f"{osnova}/prices", wait_until="load", timeout=60000)
        forma = stranica.locator('form[action$="/leads/booking"]').first
        if forma.count() == 0:
            print("ОШИБКА  на странице цен нет формы заявки")
            brauzer.close()
            return 1

        forma.locator('input[name="name"]').first.fill(metka)
        forma.locator('input[name="phone"]').first.fill("+7 900 000-00-00")
        pole_teksta = forma.locator('textarea[name="message"]')
        if pole_teksta.count():
            pole_teksta.first.fill("Заявка проверки оснастки, удалить.")
        forma.locator('button[type="submit"]').first.click()
        stranica.wait_for_load_state("load", timeout=60000)
        print(f"ок      форма заявки отправлена нажатием → {stranica.url}")

        # 2. Пустышки: форма «Сертификат на мечту». Проверяем не вид, а суть —
        #    есть ли куда отправлять и как называются поля.
        for put in STRANICY_S_FORMOY:
            stranica.goto(f"{osnova}/{put}" if put else f"{osnova}/",
                          wait_until="load", timeout=60000)
            pustyshki = [f for f in opisat_formy(stranica)
                         if not f["action"] or not f["polya"]]
            if pustyshki:
                bed += 1
                print(f"ОШИБКА  /{put or ''}: форма без адреса отправки "
                      f"или без имён полей — заявка никуда не уйдёт")
            else:
                print(f"ок      /{put or ''}: у всех форм есть адрес и поля")

        # 3. Заявка дошла до админки. Вход — нажатием, а не запросом.
        stranica.goto(f"{osnova}/admin/login", wait_until="load", timeout=60000)
        stranica.fill('input[name="email"]', dovody.pochta)
        stranica.fill('input[name="password"]', dovody.parol)
        stranica.click('button[type="submit"]')
        stranica.wait_for_load_state("networkidle", timeout=60000)
        if "/admin/login" in stranica.url:
            print("ОШИБКА  вход в админку не прошёл — заявку не проверить")
            brauzer.close()
            return 1

        stranica.goto(f"{osnova}/admin/leads", wait_until="load", timeout=60000)
        doshla = metka in stranica.content()
        print(("ок      " if doshla else "ОШИБКА  ") + "заявка видна в админке")
        bed += 0 if doshla else 1

        # 4. Убираем свой след: проверка не должна оставлять заказчику мусор
        #    в списке заявок. Заодно это проверка кнопки «Удалить».
        if doshla:
            stranica.get_by_role("link", name=metka).first.click()
            stranica.wait_for_load_state("load", timeout=60000)
            stranica.get_by_role("button", name="Удалить").first.click()
            # ⚠️ Одного нажатия мало: Orchid переспрашивает окном, и в окне
            # кнопка называется так же — «Удалить». Первое нажатие только
            # открывает вопрос, удаляет второе, уже внутри окна. Проверка на
            # этом уже объявляла кнопку сломанной, хотя сама не дожала её
            # до конца (правило 13).
            okno = stranica.locator(".modal.show").first
            okno.wait_for(state="visible", timeout=15000)
            okno.get_by_role("button", name="Удалить").first.click()
            stranica.wait_for_load_state("networkidle", timeout=60000)
            stranica.goto(f"{osnova}/admin/leads", wait_until="load", timeout=60000)
            if metka in stranica.content():
                print(f"ОШИБКА  пробная заявка осталась в админке — удалите руками: {metka}")
                bed += 1
            else:
                print("ок      пробная заявка удалена")

        brauzer.close()

    print("\nВсё чисто." if bed == 0 else f"\nБед: {bed}")
    return 1 if bed else 0


if __name__ == "__main__":
    sys.exit(main())
