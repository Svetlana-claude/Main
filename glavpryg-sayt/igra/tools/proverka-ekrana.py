#!/usr/bin/env python3
"""Проверка экрана игры: кнопки по устройствам, «свернуть / развернуть», полный экран.

    python proverka-ekrana.py [адрес /igra] [каталог снимков]

Компьютер: экранных кнопок нет, внизу подсказка клавиш, крестик и «свернуть» на месте.
Телефон: кнопки есть; «Играть» → окно во весь экран; «свернуть» → полный экран снят
(виден браузер), игра на месте; «развернуть» → снова во весь экран; крестик закрывает.
"""
import sys
from playwright.sync_api import sync_playwright

adres = sys.argv[1] if len(sys.argv) > 1 else 'https://mokeevasky.ru/glavpryg/igra'
kuda = sys.argv[2] if len(sys.argv) > 2 else '/tmp'
oshibki, provaly = [], []


def proverit(uslovie, chto):
    print(('ок    ' if uslovie else 'ПРОВАЛ') + ' — ' + chto)
    if not uslovie: provaly.append(chto)


def vidno(ramka, sel):
    return ramka.locator(sel).count() > 0 and ramka.locator(sel).is_visible()


with sync_playwright() as p:
    b = p.chromium.launch()
    for imya, vp, mob in (('kompyuter', (1440, 900), False), ('telefon-gor', (844, 390), True)):
        c = b.new_context(viewport=dict(width=vp[0], height=vp[1]), is_mobile=mob, has_touch=mob)
        s = c.new_page()
        s.on('pageerror', lambda e: oshibki.append(f'{imya}: {e}'))
        s.goto(adres, wait_until='networkidle')
        s.click('#igra-start') if not mob else s.tap('#igra-start')
        s.wait_for_timeout(500)
        polnyy = s.evaluate("!!document.fullscreenElement")
        r = s.frame_locator('#igra-okno iframe')
        r.locator('#b-start').wait_for(timeout=15000)
        r.locator('#b-start').click()
        fr = s.frames[1]
        fr.wait_for_function("s && s.faza === 'padenie'", timeout=15000)
        s.screenshot(path=f'{kuda}/ekran-{imya}.png')
        proverit(vidno(r, '#k-zakryt'), f'{imya}: крестик на экране')
        if not mob:
            proverit(not vidno(r, '#k-levo') and not vidno(r, '#k-pravo') and not vidno(r, '#k-raskryt'),
                     f'{imya}: экранных кнопок управления нет')
            proverit(vidno(r, '#klavishi'), f'{imya}: подсказка клавиш внизу')
        else:
            proverit(vidno(r, '#k-levo') and vidno(r, '#k-pravo') and vidno(r, '#k-raskryt'),
                     f'{imya}: кнопки управления на месте')
            proverit(polnyy, f'{imya}: «Играть» — во весь экран')
            proverit(vidno(r, '#k-ekran'), f'{imya}: кнопка «свернуть» на экране')
            if vidno(r, '#k-ekran'):
                r.locator('#k-ekran').tap(); s.wait_for_timeout(500)
                proverit(not s.evaluate("!!document.fullscreenElement") and fr.evaluate("s.faza") != 'itog',
                         f'{imya}: «свернуть» — полный экран снят, игра идёт')
                r.locator('#k-ekran').tap(); s.wait_for_timeout(500)
                proverit(s.evaluate("!!document.fullscreenElement"), f'{imya}: «развернуть» — снова во весь экран')
            r.locator('#k-zakryt').tap(); s.wait_for_timeout(500)
            proverit(s.locator('#igra-start').is_visible() and not s.evaluate("!!document.fullscreenElement"),
                     f'{imya}: крестик закрыл игру и снял полный экран')
        c.close()
    b.close()
print('ошибки:', oshibki or 'нет')
sys.exit(1 if oshibki or provaly else 0)
