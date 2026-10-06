"""Заказ сертификата: нажатие кнопок (правило 14) — выбор программы и тарифа, стрелки, количество, зависимости шагов, синий выбор.
Пока оплата отключена (CERTIFICATE_PAYMENT): шага оплаты нет, заказ оформляется кнопкой и даёт сертификат для распечатки;
пробный заказ после проверки удаляется. На прежнем шаблоне падает (правило 12).

    webui/.venv/bin/python glavpryg-sayt/tests/check-zakaz-sertifikata.py
"""
from playwright.sync_api import sync_playwright
ADRES = "https://mokeevasky.ru/glavpryg/certificate/order"
oshibki, plohie = [], []
def proverit(uslovie, chto):
    print(("ок   " if uslovie else "СБОЙ ") + chto)
    if not uslovie: plohie.append(chto)
def oformit(st):
    """Заказ кнопкой «Оформить заказ» → «Заявка принята» → «Сертификат для распечатки»."""
    import re, subprocess
    st.goto(ADRES, wait_until="networkidle")
    st.click('label.option-card:has(input[value="gift"])')
    st.click('label.option-card:has(input[value="pickup"])')
    st.fill('input[name="customer_name"]', "Проверка Заказчик")
    st.fill('input[name="customer_phone"]', "+7 900 000-00-00")
    st.fill('input[name="gift_recipient_name"]', "Проверка Получатель")
    st.fill('textarea[name="gift_text"]', "С днём рождения!")
    st.check('input[name="consent"]')
    st.click("#payBtn")
    st.wait_for_load_state("networkidle")
    m = re.search(r"/certificate/order/(\d+)/thanks", st.url)
    proverit(m is not None, f"заказ оформлен без оплаты: {st.url}")
    if not m:
        return
    try:
        with st.expect_popup() as okno:
            st.click("text=Сертификат для распечатки")
        pech = okno.value
        pech.wait_for_load_state("networkidle")
        tekst = re.sub(r"\s+", " ", pech.locator("body").inner_text())
        nomer = "ГП-" + m.group(1).zfill(6)
        proverit("Проверка Получатель" in tekst and nomer in tekst, f"на сертификате владелец и номер {nomer}")
        proverit("именной" in tekst.lower() and "Действует до" in tekst, "на сертификате: именной, срок действия")
        proverit(pech.locator(".sheet").count() == 1, "лист на экземпляр")
    finally:
        subprocess.run(["/usr/bin/php8.4", "artisan", "tinker", "--execute",
                        f"App\\Models\\CertificateOrder::whereKey({m.group(1)})->delete();"],
                       cwd="/var/www/glavpryg", check=False, capture_output=True)
        print(f"пробный заказ {m.group(1)} удалён")

with sync_playwright() as p:
    br = p.chromium.launch()
    for shir in (1440, 390):
        st = br.new_context(viewport={"width": shir, "height": 900}).new_page()
        st.on("console", lambda m: m.type == "error" and oshibki.append(m.text))
        st.on("pageerror", lambda e: oshibki.append(str(e)))
        st.goto(ADRES, wait_until="networkidle")
        import re
        t = lambda sel: re.sub(r"\s+", " ", st.locator(sel).inner_text()).strip()
        print(f"--- {shir}")
        proverit(t("#sTier") == "Тандем" and t("#sTotal") == "22 500 ₽", f"начально: {t('#sTier')} {t('#sTotal')}")
        n = st.locator("[data-format-card]").count()
        proverit(n == 3, f"тарифов тандема три, как в макете: {n}")
        st.click('[data-tier-step="1"]')
        proverit(st.locator('#tierInput').input_value() == "samostoyatelnyy" and st.locator('#tandemFormats').is_hidden(), "стрелка → : самостоятельный, тарифы тандема скрыты")
        st.click('[data-tier-step="-1"]'); st.click('[data-tier-step="-1"]')
        proverit(st.locator('#tierInput').input_value() == "sportivnye", "стрелка ← дважды: по кругу на спортивные")
        st.click('[data-slug="tandem"]')
        st.click('[data-key="tandem_operator"]')
        proverit(st.locator('#tierInput').input_value() == "tandem_operator" and t("#sTotal") == "30 000 ₽", f"тариф 3: {t('#sTotal')}")
        kol = st.evaluate("getComputedStyle(document.querySelector('[data-pointer=format]')).getPropertyValue('--kolonka')").strip()
        proverit(kol == "3", f"указатель под тарифом 3: --kolonka={kol}")
        st.click('[data-qty="1"]'); st.click('[data-qty="1"]')
        proverit(t("#sQty") == "3" and t("#sTotal") == "90 000 ₽", f"количество +2: {t('#sQty')} {t('#sTotal')}")
        st.click('label.option-card:has(input[value="digital"])')
        proverit(st.locator('#shippingBlock').is_hidden() and t("#sDelivery") == "Электронный" and t("#sShipping") == "На e-mail", "электронный: доставка скрыта")
        st.click('label.option-card:has(input[value="self"])')
        proverit(st.locator('#giftBlock').is_hidden(), "себе: блок подарка скрыт")
        st.click('label.option-card:has(input[value="box"])')
        proverit(st.locator('input[type=radio][name="payment_type"]').count() == 0 and t("#payBtnText").lower() == "оформить заказ",
                 f"оплата отключена: шага оплаты нет, кнопка «{t('#payBtnText')}»")
        proverit("именной" in t("#certForm aside").lower(), "в заказе сказано: сертификат именной")
        st.wait_for_timeout(400)
        aktiv = st.evaluate("getComputedStyle(document.querySelector('label.option-card.is-active')).borderTopColor")
        proverit(aktiv == "rgb(33, 150, 243)", f"выбранный вариант синий: {aktiv}")
        shir_dok = st.evaluate("document.documentElement.scrollWidth")
        proverit(shir_dok <= shir, f"страница не едет вбок: {shir_dok}")
        if shir == 1440:
            oformit(st)
        st.context.close()
    br.close()
proverit(not oshibki, f"консоль: {oshibki}")
raise SystemExit(1 if plohie else 0)
