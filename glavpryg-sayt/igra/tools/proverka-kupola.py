#!/usr/bin/env python3
"""Проверка управления куполом: сваливание и подушка.

    python proverka-kupola.py <адрес index.html> <каталог снимков>

1) Глубокое торможение (кнопка «Подушка») на высоте дольше нескольких секунд — сваливание.
2) Резкий разворот ниже 40 м — сваливание и «жёсткое приземление».
3) Подушка на 5 м с полной скорости — красиво на ноги, +10.
4) Без подушки — перекат, без бонуса.
"""
import sys
from playwright.sync_api import sync_playwright

adres, kuda = sys.argv[1], sys.argv[2]
oshibki, provaly = [], []


def do_kupola(s, h):
    """Новый прыжок, раскрытие сразу и купол на высоте h над центром круга."""
    s.click('#b-start') if s.is_visible('#b-start') else s.click('#b-eshe')
    s.wait_for_function("s && s.faza === 'padenie'", timeout=15000)
    s.evaluate("raskryt()")
    s.wait_for_function("s.faza === 'kupol'", timeout=15000)
    s.evaluate(f"s.h = {h}; s.x = 0; s.y = 0; s.trevogaBylo.k1 = s.trevogaBylo.k2 = 1")


def itog(s):
    s.wait_for_function("s.faza === 'itog'", timeout=60000)
    s.wait_for_selector('#e-itog.vidno', timeout=5000)
    return s.inner_text('#zag-itog'), s.inner_text('#itog-razbor').replace('\n', ' ')


def proverit(uslovie, chto):
    print(('ок    ' if uslovie else 'ПРОВАЛ') + ' — ' + chto)
    if not uslovie: provaly.append(chto)


with sync_playwright() as p:
    b = p.chromium.launch()
    # сенсорный экран: средняя кнопка «Подушка» есть только на телефоне и планшете
    s = b.new_context(viewport={'width': 844, 'height': 390}, is_mobile=True, has_touch=True).new_page()
    s.on('pageerror', lambda e: oshibki.append(str(e)))
    s.on('console', lambda m: m.type == 'error' and oshibki.append(m.text))
    s.goto(adres); s.wait_for_timeout(800)
    s.click('#urovni button >> nth=0')

    # 1. перетянутые клеванты на высоте
    do_kupola(s, 600)
    proverit(s.inner_text('#k-raskryt') == 'ПОДУШКА', 'под куполом средняя кнопка — «ПОДУШКА»')
    kn = s.locator('#k-raskryt').bounding_box()
    # ход клевант — в игровом времени (с перемоткой ×6 они и ходят вшестеро быстрее по часам):
    # запись [s.t, s.dL] с самого нажатия; полный ход — не быстрее 0,5 с игрового времени
    s.evaluate("window.zapis = []; window.zapisId = setInterval(() => zapis.push([s.t, s.dL]), 2)")
    s.mouse.move(kn['x'] + kn['width'] / 2, kn['y'] + kn['height'] / 2); s.mouse.down()
    s.wait_for_function("s.dL >= 0.999", timeout=5000); s.wait_for_timeout(100)
    zap = s.evaluate("clearInterval(zapisId), zapis")
    t0 = max(t for t, d in zap if d == 0); t1 = min(t for t, d in zap if d >= 0.999)
    proverit(t1 - t0 >= 0.5, f'клеванты затягиваются не мгновенно (полный ход за {t1 - t0:.2f} с игрового времени)')
    s.wait_for_function("s.svalT > 0", timeout=8000)
    s.screenshot(path=f'{kuda}/kupol-svalivanie.png')
    proverit('svalivanie' in s.get_attribute('#rezhim', 'class'), 'в сваливании на приборе — «СВАЛИВАНИЕ»')
    s.mouse.up()
    s.wait_for_function("s.svalT <= 0", timeout=8000)
    proverit(s.evaluate("s.h") > 400, 'отпустил клеванты — купол восстановился на высоте')
    # 2. резкий разворот у земли
    s.evaluate("s.h = 38")
    s.keyboard.down('ArrowRight')
    zag, razbor = itog(s)
    s.keyboard.up('ArrowRight')
    proverit('жёсткое' in zag, f'резкий разворот на 38 м — {zag}')
    # 3. подушка вовремя
    do_kupola(s, 45)
    s.wait_for_function("s.h < 5", timeout=60000, polling=16)
    s.evaluate("nazh.podushka = true")
    zag, razbor = itog(s)
    s.evaluate("nazh.podushka = false")
    proverit('на ноги' in razbor and '+10' in razbor, f'подушка на 5 м — {razbor[:120]}')
    # 4. без подушки
    do_kupola(s, 45)
    zag, razbor = itog(s)
    proverit('без подушки' in razbor, f'без подушки — {razbor[:120]}')
    b.close()
print('ошибки:', oshibki or 'нет')
sys.exit(1 if oshibki or provaly else 0)
