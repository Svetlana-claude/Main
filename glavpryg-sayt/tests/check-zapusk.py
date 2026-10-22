#!/usr/bin/env python3
"""Готовность сайта к открытому запуску: право, формы, кабинет, поиск, метрика.

    webui/.venv/bin/python glavpryg-sayt/tests/check-zapusk.py [адрес]

Что проверяется — по пунктам свода `glavpryg-sayt/zapusk/podgotovka-k-zapusku.md`:

1. Правовые документы: все шесть открываются, без заготовки «Заполнить в
   админке», ссылки на них — в подвале каждой страницы. Незаполненные
   реквизиты («[заполнить: …]») — предупреждение, а не ошибка: их даёт заказчик.
2. Согласие на обработку данных: заявка без галочки отклоняется сервером
   (422), с галочкой — проходит; на каждой форме заявки галочка есть и
   не стоит заранее.
3. Кабинет: восстановление пароля открывается, ссылка «Забыли пароль?» на входе.
4. Поиск: canonical и превью на открытых страницах, noindex на служебных,
   sitemap.xml с главной и статьями, robots.txt со ссылкой на карту.
5. Cookie и Метрика: плашка показывается, «Только необходимые» её убирает
   и запоминается; шрифтов из Google на страницах нет.

Пробная заявка из пункта 2 удаляется в конце через artisan.
"""

import argparse
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

from playwright.sync_api import sync_playwright

OTKRYTYE = ["", "about", "services/tandem", "services/samostoyatelnyy", "services/obuchenie",
            "services/sportivnye", "prices", "blog", "contacts", "certificate", "certificate/order",
            "test", "vr-trainer"]
SLUZHEBNYE = ["login", "register", "forgot-password", "igra"]
DOKUMENTY = ["privacy", "personal-data", "terms", "marketing", "cookies", "oferta"]
# Страница → какая форма заявки на ней должна быть с галочкой согласия
FORMY = {"prices": 'form[action$="/leads/booking"]', "register": 'form[action$="/register"]',
         "certificate/order": 'form[action$="/certificate/order"]'}

bed = 0
preduprezhdeniy = 0


def itog(ok: bool, chto: str, preduprezhdenie: bool = False) -> None:
    global bed, preduprezhdeniy
    if ok:
        print(f"ок      {chto}")
    elif preduprezhdenie:
        preduprezhdeniy += 1
        print(f"ВНИМАНИЕ {chto}")
    else:
        bed += 1
        print(f"ОШИБКА  {chto}")


def poluchit(url: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return r.status, r.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "ignore")


def main() -> int:
    razbor = argparse.ArgumentParser()
    razbor.add_argument("adres", nargs="?", default="https://mokeevasky.ru/glavpryg")
    osnova = razbor.parse_args().adres.rstrip("/")
    metka = f"Проба запуска {time.strftime('%d.%m %H:%M:%S')}"

    # 1. Правовые документы
    for slug in DOKUMENTY:
        kod, html = poluchit(f"{osnova}/legal/{slug}")
        itog(kod == 200 and "Заполнить в админке" not in html, f"/legal/{slug} — {kod}, текст на месте")
        if kod == 200 and "[заполнить:" in html:
            pusto = sorted(set(re.findall(r"\[заполнить: ([^\]]+)\]", html)))
            itog(False, f"/legal/{slug}: не заполнены реквизиты — {', '.join(pusto)}", preduprezhdenie=True)

    # 4. Поиск: разметка открытых и служебных страниц
    for put in OTKRYTYE:
        kod, html = poluchit(f"{osnova}/{put}")
        nado = [
            ('rel="canonical"' in html, "canonical"),
            ('property="og:image"' in html, "превью og"),
            ('name="robots" content="noindex' not in html, "не закрыта от поиска"),
            (all(f"/legal/{d}" in html for d in DOKUMENTY), "все документы в подвале"),
            ("fonts.googleapis.com" not in html, "без шрифтов Google"),
            ('id="cookie-plashka"' in html, "плашка cookie"),
        ]
        net = [podpis for ok, podpis in nado if not ok]
        itog(kod == 200 and not net, f"/{put} — {kod}" + (f": нет — {', '.join(net)}" if net else ""))
    for put in SLUZHEBNYE:
        kod, html = poluchit(f"{osnova}/{put}")
        itog(kod == 200 and 'name="robots" content="noindex' in html, f"/{put} закрыта от поиска (noindex)")

    kod, karta = poluchit(f"{osnova}/sitemap.xml")
    itog(kod == 200 and f"<loc>{osnova}/</loc>" in karta and "/blog/" in karta and "/legal/oferta" in karta,
         f"sitemap.xml — {kod}, главная, статьи и документы в карте")
    kod, robots = poluchit(f"{osnova}/robots.txt")
    itog(kod == 200 and "Sitemap:" in robots and "Disallow: /admin" in robots, "robots.txt — ссылка на карту, админка закрыта")

    # 3. Кабинет
    kod, html = poluchit(f"{osnova}/forgot-password")
    itog(kod == 200 and 'name="email"' in html, f"/forgot-password — {kod}, форма восстановления пароля")
    kod, html = poluchit(f"{osnova}/login")
    itog("/forgot-password" in html, "на входе есть ссылка «Забыли пароль?»")

    with sync_playwright() as p:
        brauzer = p.chromium.launch()
        st = brauzer.new_context(viewport={"width": 1440, "height": 900}).new_page()

        # 2. Галочка согласия на формах: есть, обязательна, не стоит заранее
        for put, selektor in FORMY.items():
            st.goto(f"{osnova}/{put}", wait_until="load", timeout=60000)
            galochka = st.locator(f'{selektor} input[name="soglasie"], {selektor} input[name="consent"]')
            ok = galochka.count() == 1 and galochka.first.evaluate("e => e.required && !e.checked")
            itog(ok, f"/{put}: галочка согласия есть, обязательна и не отмечена заранее")

        # 2. Сервер: без согласия — 422, с согласием — заявка принята
        st.goto(f"{osnova}/prices", wait_until="load", timeout=60000)
        otvet = st.evaluate(
            """async ([adres, metka, soglasie]) => {
                const f = new FormData();
                f.append('_token', document.querySelector('input[name=_token]').value);
                f.append('name', metka); f.append('phone', '+7 900 000-00-00');
                if (soglasie) f.append('soglasie', '1');
                const r = await fetch(adres, {method: 'POST', body: f, headers: {'Accept': 'application/json'}});
                return r.status;
            }""", [f"{osnova}/leads/booking", metka, False])
        itog(otvet == 422, f"заявка без галочки согласия отклонена сервером ({otvet})")
        otvet = st.evaluate(
            """async ([adres, metka]) => {
                const f = new FormData();
                f.append('_token', document.querySelector('input[name=_token]').value);
                f.append('name', metka); f.append('phone', '+7 900 000-00-00'); f.append('soglasie', '1');
                const r = await fetch(adres, {method: 'POST', body: f, headers: {'Accept': 'application/json'}});
                return r.status;
            }""", [f"{osnova}/leads/booking", metka])
        itog(otvet in (200, 302), f"заявка с галочкой принята ({otvet})")

        # 5. Плашка cookie: видна, «Только необходимые» убирает, выбор помнится
        st.goto(f"{osnova}/contacts", wait_until="load", timeout=60000)
        plashka = st.locator("#cookie-plashka")
        vidna = plashka.is_visible()
        st.locator('#cookie-plashka [data-cookie="net"]').click()
        skryta = plashka.is_hidden()
        st.reload(wait_until="load")
        pomnit = st.locator("#cookie-plashka").is_hidden()
        metrika = st.evaluate("() => typeof window.ym === 'function'")
        itog(vidna and skryta and pomnit and not metrika,
             "плашка cookie: показана, «Только необходимые» убирает и помнится, Метрика не грузится")
        brauzer.close()

    # Убрать пробную заявку и проверить, что согласие записано
    r = subprocess.run(
        ["php8.4", "artisan", "tinker", "--execute",
         f'$l = App\\Models\\Lead::where("name", {json.dumps(metka, ensure_ascii=False)})->first();'
         ' echo $l ? ($l->soglasie_at ? "est" : "net") : "propala"; App\\Models\\Lead::where("name", '
         f'{json.dumps(metka, ensure_ascii=False)})->delete();'],
        cwd="/var/www/glavpryg", capture_output=True, text=True)
    itog(r.stdout.strip().endswith("est"), f"у принятой заявки записано время согласия ({r.stdout.strip() or r.stderr.strip()[:80]})")

    print(f"\nВсё готово к запуску." if bed == 0 and preduprezhdeniy == 0 else
          f"\nОшибок: {bed}, предупреждений: {preduprezhdeniy}")
    return 1 if bed else 0


if __name__ == "__main__":
    sys.exit(main())
