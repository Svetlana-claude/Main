#!/usr/bin/env python3
"""Проверка посадки видом сбоку.

    python proverka-posadki.py <адрес index.html> <каталог снимков>

Ниже 50 м — вид сбоку (небо сверху кадра, шкала клевант вместо табло режимов). Поза: при полном ходе кисти
выше плеч, в среднем режиме — у груди, в подушке — внизу; ноги вместе. Исход касания — от работы клевантами:
без подушки — перекат ×0,5; «раз-два» по шкале — красиво на ноги +10; подушка на 3 м — пробежка +5;
рано (9 м) — падение назад; при встречном 7 м/с подушка на 6 м — ветер утаскивает назад.
Итог — после того как досмотрели посадку. Последний случай — настоящими клавишами ↓ и пробел.
"""
import sys
from playwright.sync_api import sync_playwright

adres, kuda = sys.argv[1], sys.argv[2]
oshibki, provaly = [], []


def proverit(uslovie, chto):
    print(('ок    ' if uslovie else 'ПРОВАЛ') + ' — ' + chto)
    if not uslovie: provaly.append(chto)


NACH = """([W, h]) => { pauza = true; vybranaPogoda = 0; noviyPryzhok(0); s.faza = 'kupol'; knopkaPodushka(true); kR.classList.add('vidno');
  s.W = W; s.kurs = s.veterKuda + 180; s.h = h; s.x = 0; s.y = 0; s.v = F.kupolGor; s.vzK = F.kupolVert;
  Object.assign(s.trevogaBylo, { k1:1, k2:1, k3:1 }); document.getElementById('e-start').classList.remove('vidno'); }"""
DO = """([h, plan]) => { const [raz, dva] = razDva(s.W); plan = plan.map(([hh, r]) => [hh === 'raz' ? raz : hh === 'dva' ? dva : hh, r]);
  let n = 0; while (s.faza === 'kupol' && s.h > h && n < 30000) {
    nazh.podushka = false; nazh.vniz = false; for (const [hh, r] of plan) if (s.h <= hh) { nazh.vniz = r === 'sr'; nazh.podushka = r === 'pod'; }
    shag(1/60); n++; }
  nazh.podushka = nazh.vniz = false; risovat(); obnovitPribory(); return s.faza; }"""

with sync_playwright() as p:
    b = p.chromium.launch()
    s = b.new_context(viewport={'width': 1440, 'height': 900}).new_page()
    s.on('pageerror', lambda e: oshibki.append(str(e)))
    s.on('console', lambda m: m.type == 'error' and oshibki.append(m.text))
    s.goto(adres); s.wait_for_timeout(1200)

    # вид сбоку и поза
    s.evaluate(NACH, [0, 60]); s.evaluate(DO, [55, []])
    proverit(not s.evaluate("bokVid()"), 'выше 50 м — вид сверху')
    s.evaluate(DO, [30, []]); s.evaluate("() => { for (let i = 0; i < 40; i++) shag(1/60); risovat(); obnovitPribory(); }")
    nebo = s.evaluate("() => { const d = ctx.getImageData(Math.round(SH / 2), 4, 1, 1).data; return d[2] > d[0] + 40; }")
    proverit(s.evaluate("bokVid()") and nebo and not s.is_visible('#rezhim'), 'ниже 50 м — вид сбоку: сверху небо, вместо табло режимов — шкала клевант')
    s.screenshot(path=f'{kuda}/posadka-bok-30.png')
    kisti = s.evaluate("""() => [0, 0.5, 1].map(b => { const J = sustavy(pozaVozduh([0, 5], b, 0)); return +(J.ruka[1][1] - J.pl[1]).toFixed(2); })""")
    proverit(kisti[0] > 0.3 and -0.15 < kisti[1] < 0.15 and kisti[2] < -0.3, f'кисти относительно плеч: полный ход {kisti[0]}, средний {kisti[1]}, подушка {kisti[2]} м')
    nogi = s.evaluate("() => { const J = sustavy(pozaVozduh([0, 5], 0, 0)); return +Math.hypot(J.nogi[0][1][0] - J.nogi[1][1][0], J.nogi[0][1][1] - J.nogi[1][1][1]).toFixed(2); }")
    proverit(nogi < 0.06, f'ноги вместе: между стопами {nogi} м')

    # исходы
    sluchai = [
        ('без подушки', 0, [], 'Перекат', '×0,5'),
        ('раз-два по шкале', 0, [['raz', 'sr'], ['dva', 'pod']], 'Красиво на ноги', '+10'),
        ('подушка на 3 м', 0, [[3, 'pod']], 'пробежкой', '+5'),
        ('подушка на 9 м', 0, [[9, 'pod']], 'Упал назад', 'рано'),
        ('ветер 7 м/с, подушка на 6 м', 7, [[6, 'pod']], 'Упал назад', 'утащил назад'),
        ('ветер 7 м/с, раз-два по шкале', 7, [['raz', 'sr'], ['dva', 'pod']], 'Красиво на ноги', '+10'),
    ]
    for imya, W, plan, zhdu, i2 in sluchai:
        s.evaluate("document.getElementById('e-itog').classList.remove('vidno')")
        s.evaluate(NACH, [W, 45]); s.evaluate(DO, [-1, plan])
        s.evaluate("pauza = false")
        t0 = s.evaluate("performance.now()")
        s.wait_for_selector('#e-itog.vidno', timeout=8000)
        zhdali = (s.evaluate("performance.now()") - t0) / 1000
        if imya == 'без подушки': s.evaluate("pauza = true; s.posadka.t = 0.5; risovat()"); s.screenshot(path=f'{kuda}/posadka-perekat.png')
        razbor = s.inner_text('#itog-razbor').replace('\n', ' ')
        stroka = next((x for x in razbor.split('  ') if zhdu in x), razbor)
        proverit(zhdu in razbor and i2 in razbor and zhdali > 2, f'{imya}: {stroka[:110]} (итог через {zhdali:.1f} с)')

    # настоящими клавишами: ↓ на «раз», пробел на «два»
    s.evaluate("document.getElementById('e-itog').classList.remove('vidno')")
    s.evaluate(NACH, [0, 14]); s.evaluate("pauza = false")
    s.wait_for_function("s.h < razDva(s.W)[0]", polling=10, timeout=20000); s.keyboard.down('ArrowDown')
    s.wait_for_function("s.h < razDva(s.W)[1]", polling=10, timeout=20000)
    s.screenshot(path=f'{kuda}/posadka-raz.png')
    s.keyboard.up('ArrowDown'); s.keyboard.down('Space')
    s.wait_for_function("s.posadka && s.posadka.t > 0.3", polling=10, timeout=20000)
    s.screenshot(path=f'{kuda}/posadka-nogi.png')
    s.keyboard.up('Space')
    s.wait_for_selector('#e-itog.vidno', timeout=8000)
    razbor = s.inner_text('#itog-razbor').replace('\n', ' ')
    proverit('на ноги' in razbor, f'клавишами ↓ и пробел: {razbor[:200]}')
    b.close()
print('ошибки:', oshibki or 'нет')
sys.exit(1 if oshibki or provaly else 0)
