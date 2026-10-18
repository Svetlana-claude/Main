#!/usr/bin/env python3
"""Проверка страницы /igra: открывается, без ошибок и сдвига вбок; «Играть» запускает игру.

    python proverka-stranicy.py [адрес] [каталог снимков]
"""
import sys
from playwright.sync_api import sync_playwright

adres = sys.argv[1] if len(sys.argv) > 1 else 'https://mokeevasky.ru/glavpryg/igra'
kuda = sys.argv[2] if len(sys.argv) > 2 else '/tmp'
oshibki = []
with sync_playwright() as p:
    b = p.chromium.launch()
    for imya, vp, mob in (('telefon', (390, 844), True), ('telefon-gor', (844, 390), True), ('kompyuter', (1440, 900), False)):
        c = b.new_context(viewport=dict(width=vp[0], height=vp[1]), is_mobile=mob, has_touch=mob)
        s = c.new_page()
        s.on('console', lambda m: m.type == 'error' and oshibki.append(f'{imya}: {m.text}'))
        s.on('pageerror', lambda e: oshibki.append(f'{imya}: {e}'))
        s.on('response', lambda r: r.status >= 400 and oshibki.append(f'{imya}: {r.status} {r.url}'))
        s.goto(adres, wait_until='networkidle')
        if s.evaluate('document.documentElement.scrollWidth > innerWidth'):
            oshibki.append(f'{imya}: страница шире экрана')
        s.screenshot(path=f'{kuda}/igra-stranica-{imya}.png', full_page=True)
        s.click('#igra-start')
        s.wait_for_timeout(1500)
        ramka = s.frame_locator('#igra-okno iframe')
        # сегодня по сводке нелётно — игра права, что не пускает; для проверки запуска берём «Ясно»
        if 'zapret' in (ramka.locator('#pogoda-opis').get_attribute('class') or ''):
            print(imya, 'по сводке прыжков нет — проверяю запуск на «Ясно»')
            ramka.locator('#pogoda button', has_text='Ясно').click()
        ramka.locator('#b-start').click()
        s.wait_for_timeout(4500)
        faza = s.frames[1].evaluate('s && s.faza') if len(s.frames) > 1 else None
        print(imya, 'фаза после «Играть» → «Прыгать!»:', faza)
        if faza not in ('padenie', 'samolet'):
            oshibki.append(f'{imya}: игра не запустилась ({faza})')
        s.screenshot(path=f'{kuda}/igra-stranica-{imya}-igra.png')
        c.close()
    b.close()
print('ошибки:', oshibki or 'нет')
sys.exit(1 if oshibki else 0)
