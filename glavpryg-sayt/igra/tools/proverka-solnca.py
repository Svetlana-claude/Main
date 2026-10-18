#!/usr/bin/env python3
"""Проверка солнца и времени суток.

    python proverka-solnca.py <адрес index.html> <каталог снимков>

Положение солнца над Грызловом сверяется с известными значениями (полдень, восход, закат).
Прыжок в ?vremya=… утром, днём и вечером: время суток определено, утро и вечер теплее и темнее дня,
тени облаков ложатся от солнца (утром — на запад, вечером — на восток), в виде сбоку на закате
небо у горизонта тёплое. Ночь переносится на светлое время. На старте — строка о солнце.
"""
import sys
from playwright.sync_api import sync_playwright

adres, kuda = sys.argv[1], sys.argv[2]
oshibki, provaly = [], []


def proverit(uslovie, chto):
    print(('ок    ' if uslovie else 'ПРОВАЛ') + ' — ' + chto)
    if not uslovie: provaly.append(chto)


def ton(s, y0=0, y1=1):
    """Средние R, G, B по полосе кадра (доли высоты)."""
    return s.evaluate(f"""() => {{ const y = Math.floor(holst.height * {y0}), h = Math.max(1, Math.floor(holst.height * ({y1} - {y0})));
      const d = ctx.getImageData(0, y, holst.width, h).data; let r = 0, g = 0, b = 0, n = 0;
      for (let i = 0; i < d.length; i += 16) {{ r += d[i]; g += d[i+1]; b += d[i+2]; n++; }} return [r / n, g / n, b / n]; }}""")


def pryzhok(s, vremya, pogoda='Кучевые'):
    s.goto(f'{adres}?vremya={vremya}'); s.wait_for_timeout(600)
    s.locator('#pogoda button', has_text=pogoda).first.click()
    s.click('#urovni button >> nth=0'); s.click('#b-start')
    s.wait_for_function("s && s.faza === 'samolet'", timeout=15000); s.wait_for_timeout(300)
    return s.evaluate("({...s.solnce, d:s.solnce.d.toISOString(), svet:s.svet})")


with sync_playwright() as p:
    b = p.chromium.launch()
    s = b.new_context(viewport={'width': 1440, 'height': 900}).new_page()
    s.on('pageerror', lambda e: oshibki.append(str(e)))
    s.on('console', lambda m: m.type == 'error' and oshibki.append(m.text))
    s.goto(adres); s.wait_for_timeout(800)

    # положение солнца: эталон — библиотека astral для 54,79° с. ш., 37,65° в. д. (без рефракции)
    for vremya, vys, az, chto in [('2026-06-21T12:15', 58.5, 173, 'летний полдень'),
                                  ('2026-12-21T12:15', 11.8, 177, 'зимний полдень'),
                                  ('2026-10-18T12:15', 25.6, 180, 'полдень сегодня'),
                                  ('2026-03-20T07:00', 3.4, 95, 'весеннее равноденствие, утро'),
                                  ('2026-09-23T18:15', 1.2, 268, 'осеннее равноденствие, закат')]:
        r = s.evaluate(f"polozhenieSolnca(new Date('{vremya}:00+03:00'))")
        proverit(abs(r['vys'] - vys) < 1 and abs(r['az'] - az) < 3,
                 f"{chto}: высота {r['vys']:.1f}° (≈{vys}), азимут {r['az']:.0f}° (≈{az})")

    proverit('солнце' in s.inner_text('#vremya-opis'), f"на старте — строка о солнце: «{s.inner_text('#vremya-opis')}»")

    # утро, день, вечер: время суток и сообщение — по прыжку; свет и тени — на одной и той же сцене
    rez = {}
    for vremya, chast in [('2026-10-18T09:00', 'утро'), ('2026-10-18T12:30', 'день'), ('2026-10-18T16:15', 'вечер')]:
        S = pryzhok(s, vremya)
        proverit(S['chast'] == chast, f"{vremya}: время суток «{S['chast']}», солнце {S['vys']:.0f}° на азимуте {S['az']:.0f}°")
        proverit(chast in s.evaluate("elSoob.textContent"), f'{chast}: время названо в начале прыжка')
    pryzhok(s, '2026-10-18T12:30')
    s.evaluate("pauza = true; s.tuchiSdvig = [0, 0]; skrytSoob()")
    for vremya, chast in [('2026-10-18T09:00', 'утро'), ('2026-10-18T12:30', 'день'), ('2026-10-18T16:15', 'вечер')]:
        s.evaluate(f"""() => {{ history.replaceState(null, '', '?vremya={vremya}');
          s.solnce = vremyaPryzhka(); s.svet = svet(s.solnce, s.sloi); risovat(); }}""")
        rez[chast] = {'ton': ton(s), 'ten': s.evaluate("sdvigTeni(s.solnce, 1000)")}
        s.screenshot(path=f'{kuda}/solnce-{chast}.png')
    teplo = {k: v['ton'][0] / max(1, v['ton'][2]) for k, v in rez.items()}
    yark = {k: sum(v['ton']) for k, v in rez.items()}
    proverit(teplo['утро'] > teplo['день'] * 1.04 and teplo['вечер'] > teplo['день'] * 1.08,
             f"утро и вечер теплее дня: R/B утро {teplo['утро']:.2f}, день {teplo['день']:.2f}, вечер {teplo['вечер']:.2f}")
    proverit(yark['вечер'] < yark['день'] * 0.95, f"вечер темнее дня: {yark['вечер']:.0f} против {yark['день']:.0f}")
    proverit(rez['утро']['ten'][0] < -300 and rez['вечер']['ten'][0] > 300,
             f"тени от солнца: утром на запад ({rez['утро']['ten'][0]:.0f} м), вечером на восток ({rez['вечер']['ten'][0]:.0f} м)")
    proverit(abs(rez['день']['ten'][0]) < abs(rez['утро']['ten'][0]) and rez['день']['ten'][1] < 0,
             f"днём тень к северу: {rez['день']['ten'][0]:.0f}, {rez['день']['ten'][1]:.0f} м")

    # ночь — на светлое время
    S = pryzhok(s, '2026-10-18T02:00', 'Ясно')
    proverit(S['vys'] >= 4 and S['perenos'] and S['chast'] == 'утро',
             f"в 02:00 прыжок перенесён на утро: {S['tekst']}, солнце {S['vys']:.1f}°")
    proverit('темно' in s.inner_text('#vremya-opis'), 'на старте сказано, что сейчас темно')

    # сплошная облачность: теней нет, тёплый тон слабее
    S = pryzhok(s, '2026-10-18T16:15', 'Два яруса')
    proverit(S['svet']['teni'] < 0.05, f"под сплошным слоем тени гаснут: сила {S['svet']['teni']:.2f}")

    # вид сбоку на закате: небо у горизонта тёплое
    nebo = {}
    for vremya in ['2026-10-18T12:30', '2026-10-18T16:15']:
        pryzhok(s, vremya, 'Ясно')
        s.evaluate("""() => { s.faza = 'kupol'; s.h = 30; s.x = 0; s.y = 0; s.kurs = s.solnce.azIgra + 90; s.bokT = 1; pauza = true; risovat(); }""")
        nebo[vremya] = ton(s, 0.4, 0.5)
        s.screenshot(path=f"{kuda}/solnce-bok-{vremya[-5:].replace(':', '')}.png")
    a, z = nebo['2026-10-18T12:30'], nebo['2026-10-18T16:15']
    proverit(z[0] / z[2] > a[0] / a[2] * 1.1, f'вид сбоку: у горизонта на закате теплее (R/B {z[0]/z[2]:.2f} против {a[0]/a[2]:.2f})')
    b.close()

print('ошибки страницы: ' + ('; '.join(oshibki) if oshibki else 'нет'))
if provaly or oshibki:
    print(f'ПРОВАЛОВ: {len(provaly)}'); sys.exit(1)
print('все проверки пройдены')
