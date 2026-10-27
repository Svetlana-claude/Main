#!/usr/bin/env python3
"""Проверка экрана игры: кнопки по устройствам, «свернуть / развернуть», полный экран.

    python proverka-ekrana.py [адрес /igra] [каталог снимков]

Компьютер: экранных кнопок нет, внизу подсказка клавиш, крестик и «свернуть» на месте.
Телефон: кнопки есть; «Играть» → окно во весь экран; «свернуть» → полный экран снят
(виден браузер), игра на месте; «развернуть» → снова во весь экран; крестик закрывает.
iPhone (полного экрана нет): окно растягивается поверх страницы, подсказка «смахни вверх»,
та же «свернуть / развернуть» и крестик.
"""
import sys
from playwright.sync_api import sync_playwright


def nelyotno(r):
    """Сегодня по сводке нелётно — игра права, что не пускает; для проверки экрана берём «Ясно»."""
    if 'zapret' in (r.locator('#pogoda-opis').get_attribute('class') or ''):
        r.locator('#pogoda button', has_text='Ясно').click()

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
        nelyotno(r)
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

    # iPhone: полного экрана для страниц нет — окно растягивается поверх страницы, смахнуть вверх прячет панели
    UA = ('Mozilla/5.0 (iPhone; CPU iPhone OS 17_5_1 like Mac OS X) AppleWebKit/605.1.15 '
          '(KHTML, like Gecko) Version/17.5.1 Mobile/21F90 Safari/604.1')
    imya = 'iphone'
    # панели Safari видны: окно ниже короткой стороны экрана
    c = b.new_context(viewport={'width': 844, 'height': 340}, screen={'width': 390, 'height': 844},
                      is_mobile=True, has_touch=True, user_agent=UA)
    c.add_init_script("delete Element.prototype.requestFullscreen; delete Element.prototype.webkitRequestFullscreen;"
                      "Object.defineProperty(Element.prototype,'requestFullscreen',{value:undefined});")
    s = c.new_page()
    s.on('pageerror', lambda e: oshibki.append(f'{imya}: {e}'))
    s.goto(adres, wait_until='networkidle')
    # плашка cookie у нижнего края закрывает низ окна игры — сперва ответить на неё, как сделает человек
    if s.locator('[data-cookie="net"]').is_visible(): s.tap('[data-cookie="net"]')
    s.tap('#igra-start'); s.wait_for_timeout(500)
    ok = s.locator('#igra-okno').bounding_box()
    proverit(s.evaluate("document.getElementById('igra-okno').classList.contains('psevdo')")
             and ok['x'] == 0 and ok['y'] == 0 and ok['width'] == 844 and ok['height'] == 340,
             f'{imya}: «Играть» — окно игры на весь экран поверх страницы ({ok})')
    proverit(s.locator('#igra-svayp').is_visible(), f'{imya}: подсказка «Проведите пальцем вверх»')
    s.screenshot(path=f'{kuda}/ekran-iphone-svayp.png')
    s.set_viewport_size({'width': 844, 'height': 390}); s.wait_for_timeout(400)   # смахнул — панели спрятались
    proverit(not s.locator('#igra-svayp').is_visible(), f'{imya}: панели спрятаны — подсказка ушла')
    r = s.frame_locator('#igra-okno iframe')
    r.locator('#b-start').wait_for(timeout=15000)
    nelyotno(r)
    r.locator('#b-start').tap()
    fr = s.frames[1]
    fr.wait_for_function("s && s.faza === 'padenie'", timeout=15000)
    s.screenshot(path=f'{kuda}/ekran-iphone.png')
    proverit(vidno(r, '#k-zakryt') and vidno(r, '#k-ekran') and vidno(r, '#k-levo'), f'{imya}: крестик, «свернуть» и кнопки на месте')
    r.locator('#k-ekran').tap(); s.wait_for_timeout(500)
    ok = s.locator('#igra-okno').bounding_box()
    proverit(not s.evaluate("document.getElementById('igra-okno').classList.contains('psevdo')") and ok['width'] < 844
             and fr.evaluate("s.faza") != 'itog', f'{imya}: «свернуть» — окно снова на странице, игра идёт')
    proverit(fr.evaluate("document.getElementById('k-ekran').getAttribute('aria-label')") == 'Во весь экран', f'{imya}: кнопка стала «Во весь экран»')
    r.locator('#k-ekran').tap(); s.wait_for_timeout(500)
    proverit(s.evaluate("document.getElementById('igra-okno').classList.contains('psevdo')"), f'{imya}: «развернуть» — снова на весь экран')
    r.locator('#k-zakryt').tap(); s.wait_for_timeout(500)
    proverit(s.locator('#igra-start').is_visible() and not s.evaluate("document.documentElement.classList.contains('igra-psevdo')"),
             f'{imya}: крестик закрыл игру, страница прежняя')
    c.close()
    b.close()
print('ошибки:', oshibki or 'нет')
sys.exit(1 if oshibki or provaly else 0)
