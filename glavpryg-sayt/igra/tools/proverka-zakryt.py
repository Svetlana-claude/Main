#!/usr/bin/env python3
"""Проверка крестика «Закрыть игру»: во встроенном окне /igra и в отдельной игре.

    python proverka-zakryt.py [адрес /igra] [каталог снимков]

Встроенное окно: «Играть» → крестик → обложка вернулась, полного экрана нет,
«Играть» снова запускает игру. В прыжке крестик не наезжает на колдун.
Отдельно: со страницы /igra переход в игру → крестик → снова /igra.
"""
import sys
from playwright.sync_api import sync_playwright

adres = sys.argv[1] if len(sys.argv) > 1 else 'https://mokeevasky.ru/glavpryg/igra'
kuda = sys.argv[2] if len(sys.argv) > 2 else '/tmp'
oshibki = []


def peresek(a, b):
    return not (a['x'] + a['width'] <= b['x'] or b['x'] + b['width'] <= a['x'] or
                a['y'] + a['height'] <= b['y'] or b['y'] + b['height'] <= a['y'])


with sync_playwright() as p:
    b = p.chromium.launch()
    for imya, vp, mob in (('telefon-gor', (844, 390), True), ('kompyuter', (1440, 900), False)):
        c = b.new_context(viewport=dict(width=vp[0], height=vp[1]), is_mobile=mob, has_touch=mob)
        s = c.new_page()
        s.on('pageerror', lambda e: oshibki.append(f'{imya}: {e}'))
        s.goto(adres, wait_until='networkidle')
        s.click('#igra-start')
        s.wait_for_timeout(1500)
        ramka = s.frame_locator('#igra-okno iframe')
        if ramka.locator('#k-zakryt').count() == 0:
            oshibki.append(f'{imya}: в игре нет крестика'); c.close(); continue
        # в прыжке: крестик и колдун не пересекаются
        ramka.locator('#b-start').click()
        s.wait_for_timeout(3000)
        kr, kol = ramka.locator('#k-zakryt').bounding_box(), ramka.locator('#koldun').bounding_box()
        if peresek(kr, kol):
            oshibki.append(f'{imya}: крестик наезжает на колдун')
        s.screenshot(path=f'{kuda}/igra-zakryt-{imya}-do.png')
        ramka.locator('#k-zakryt').tap() if mob else ramka.locator('#k-zakryt').click()
        s.wait_for_timeout(800)
        ost = s.evaluate("[!!document.querySelector('#igra-okno iframe'), !!document.fullscreenElement, !!document.getElementById('igra-start')]")
        print(imya, 'после крестика: рамка, полный экран, «Играть» —', ost)
        if ost != [False, False, True]:
            oshibki.append(f'{imya}: окно не закрылось {ost}')
        s.screenshot(path=f'{kuda}/igra-zakryt-{imya}-posle.png')
        s.click('#igra-start')
        s.wait_for_timeout(1200)
        if not s.evaluate("!!document.querySelector('#igra-okno iframe')"):
            oshibki.append(f'{imya}: повторный запуск не открыл игру')
        # отдельная игра: переход со страницы, крестик возвращает на /igra
        s.goto(adres, wait_until='networkidle')
        igra = s.evaluate("new URL(document.querySelector('a[href*=\"igra-app\"]').href).href")
        s.evaluate(f"location.href = {igra!r}")
        s.wait_for_url('**/igra-app/**')
        s.wait_for_timeout(800)
        s.locator('#k-zakryt').click()
        s.wait_for_timeout(1500)
        print(imya, 'отдельно, после крестика:', s.url)
        if not s.url.rstrip('/').endswith('/igra'):
            oshibki.append(f'{imya}: отдельная игра не вернула на /igra ({s.url})')
        c.close()
    b.close()
print('ошибки:', oshibki or 'нет')
sys.exit(1 if oshibki else 0)
