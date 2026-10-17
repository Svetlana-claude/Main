#!/usr/bin/env python3
"""Проверка облачных слоёв и выбора погоды.

    python proverka-oblakov.py <адрес index.html> <каталог снимков>

Старт: погода выбирается первой, выбор запоминается. «Низкая сплошная» — выброска на 2000 м
под слоем. «Мощные кучевые»: сверху облака видны (белое на кадре), внутри облака — белая мгла
и «В ОБЛАКЕ» на приборе, раскрытие в облаке — ×0,5 в разборе. «Облачность 600 м» — прыжка нет.
"""
import sys
from playwright.sync_api import sync_playwright

adres, kuda = sys.argv[1], sys.argv[2]
oshibki, provaly = [], []


def proverit(uslovie, chto):
    print(('ок    ' if uslovie else 'ПРОВАЛ') + ' — ' + chto)
    if not uslovie: provaly.append(chto)


def pogoda(s, imya):
    s.locator('#pogoda button', has_text=imya).click()


def belizna(s):
    """Доля почти белых точек в кадре игры."""
    return s.evaluate("""() => { const d = ctx.getImageData(0, 0, holst.width, holst.height).data; let n = 0;
      for (let i = 0; i < d.length; i += 16) if (d[i] > 215 && d[i+1] > 215 && d[i+2] > 215) n++; return n / (d.length / 16); }""")


with sync_playwright() as p:
    b = p.chromium.launch()
    c = b.new_context(viewport={'width': 1440, 'height': 900})
    s = c.new_page()
    s.on('pageerror', lambda e: oshibki.append(str(e)))
    s.on('console', lambda m: m.type == 'error' and oshibki.append(m.text))
    s.goto(adres); s.wait_for_timeout(800)
    karta = s.inner_text('#e-start .karta').lower()
    proverit(karta.index('погода') < karta.index('уровень'), 'погода — первым выбором на старте, до уровня')
    proverit(s.locator('#pogoda button').count() >= 7, f'вариантов погоды: {s.locator("#pogoda button").count()}')
    s.screenshot(path=f'{kuda}/oblaka-start.png')

    # нелётная
    pogoda(s, 'Облачность 600 м'); s.click('#b-start'); s.wait_for_timeout(400)
    proverit(s.is_visible('#e-start') and 'отменён' in s.inner_text('#pogoda-opis'), 'облачность 600 м — прыжок отменён')

    # низкая сплошная: выброска под слоем
    pogoda(s, 'Низкая сплошная'); s.click('#urovni button >> nth=0'); s.click('#b-start')
    s.wait_for_function("s && s.faza === 'samolet'", timeout=15000)
    proverit(s.evaluate("s.h") == 2000, f'низкая сплошная (от 2300 м) — выброска на {s.evaluate("s.h")} м')
    s.reload(); s.wait_for_timeout(800)
    proverit(s.get_attribute('#pogoda button[aria-pressed="true"]', 'aria-label').startswith('Погода: Низкая'),
             'выбор погоды запомнился после перезагрузки')

    # мощные кучевые: сверху видно, внутри — мгла
    pogoda(s, 'Мощные кучевые'); s.click('#b-start')
    s.wait_for_function("s && s.faza === 'padenie'", timeout=15000)
    # над самым высоким облаком у центра
    s.evaluate("""() => { const L = s.sloi[0], o = L.oblaka.reduce((a, b) => b.verh > a.verh ? b : a);
      window._o = o; const [x, y] = o.kuski[0]; s.x = x + s.tuchiSdvig[0] + 300; s.y = y + s.tuchiSdvig[1]; s.h = 3900;
      s.trevogaBylo.r1 = s.trevogaBylo.r2 = 1; }""")
    s.wait_for_timeout(300)
    bel = belizna(s)
    s.screenshot(path=f'{kuda}/oblaka-sverhu.png')
    proverit(bel > 0.08, f'над кучевыми — облака на кадре (белого {bel:.0%})')
    s.evaluate("() => { const [x, y] = _o.kuski[0]; s.x = x + s.tuchiSdvig[0]; s.y = y + s.tuchiSdvig[1]; s.h = (s.sloi[0].niz + _o.verh) / 2; }")
    s.wait_for_timeout(600)
    bel = belizna(s)
    s.screenshot(path=f'{kuda}/oblaka-vnutri.png')
    proverit(s.evaluate("!!s.vOblake") and bel > 0.6 and 'ОБЛАКЕ' in s.inner_text('#oblaka-cifra'),
             f'внутри облака — мгла (белого {bel:.0%}), на приборе «{s.inner_text("#oblaka-cifra")}»')
    proverit('облаке' in s.inner_text('#soobshenie'), f'сообщение: «{s.inner_text("#soobshenie")}»')
    s.keyboard.press('Space')
    proverit(s.evaluate("s.raskrytVOblake") is True, 'раскрытие в облаке отмечено')
    s.wait_for_function("s.faza === 'kupol'", timeout=15000)
    s.evaluate("s.h = 25; s.x = 0; s.y = 0")
    s.wait_for_selector('#e-itog.vidno', timeout=60000)
    razbor = s.inner_text('#itog-razbor').replace('\n', ' ')
    proverit('в облаке' in razbor and 'Мощные кучевые' in razbor, f'разбор: {razbor[:160]}')
    c.close()
    b.close()
print('ошибки:', oshibki or 'нет')
sys.exit(1 if oshibki or provaly else 0)
