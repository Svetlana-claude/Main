#!/usr/bin/env python3
"""Проверка игрового макета: загрузка без ошибок, прыжок автопилотом, снимки.

    python proverka-maketa.py <адрес index.html> <каталог снимков> [уровни: 0,5,7] [--bez-svodki]

По умолчанию погода — та, что выберет игра (на сервере — «Сегодня в Грызлово» по сводке дня);
`--bez-svodki` подменяет сводку пустой — погода и ветер по уровню.

Автопилот ведёт к цели в падении (поворот и движение вперёд), раскрывается на 1000 м и под куполом
держит курс на круг (ниже 45 м не крутит — иначе сваливание),
на 5,5 м жмёт подушку, в сильный ветер после касания гасит купол. Печатает итог прыжка.
"""
import sys, time
from playwright.sync_api import sync_playwright

adres, kuda = sys.argv[1], sys.argv[2]
argi = [a for a in sys.argv[3:] if not a.startswith('--')]
urovni = [int(u) for u in (argi[0] if argi else '0').split(',')]
bez_svodki = '--bez-svodki' in sys.argv
AVTOPILOT = """() => {
  // сильный ветер тянет купол после касания — гасим: одна клеванта до конца
  const P = s && s.posadka;
  if (P && P.tyanet && P.gasheno == null) { nazh.levo = true; nazh.pravo = nazh.podushka = false; return 'gasit'; }
  if (P) nazh.levo = nazh.pravo = nazh.podushka = false;
  if (!s || s.faza === 'itog' || s.faza === 'samolet') return s && s.faza;
  let kurs = Math.atan2(-s.x, s.y) * 180 / Math.PI;        // курс на центр: 0 — север
  // ветер сильнее купола — держаться против ветра, поправляясь вбок, и раскрываться низко
  if (s.W > 7) {
    const [wx, wy] = [Math.sin(s.veterKuda * Math.PI / 180), -Math.cos(s.veterKuda * Math.PI / 180)];
    const vbok = s.x * -wy + s.y * wx;                        // смещение поперёк ветра
    kurs = s.veterKuda + 180 + Math.max(-40, Math.min(40, vbok / 5));
  }
  // купол отвечает с запаздыванием — упреждаем по угловой скорости
  const d = ((kurs - s.kurs - (s.om || 0) * 0.9) % 360 + 540) % 360 - 180;
  const nizko = s.faza === 'kupol' && s.h < 45;
  nazh.levo = !nizko && d < -10; nazh.pravo = !nizko && d > 10; nazh.vniz = false;
  nazh.vverh = s.faza === 'padenie' && Math.abs(d) < 30;            // в падении — движение вперёд к цели
  if (s.faza === 'padenie' && s.h < (s.W > 7 ? 920 : 1000)) raskryt();
  nazh.podushka = s.faza === 'kupol' && s.h < (typeof razDva === 'function' ? (razDva(s.W)[0] + razDva(s.W)[1]) / 2 : 5.5);
  return s.faza + ' ' + Math.round(s.h) + ' ' + Math.round(Math.hypot(s.x, s.y));
}"""
oshibki = []
with sync_playwright() as p:
    b = p.chromium.launch()
    for imya, vp, mob, ur in [(f'{n}-u{u + 1}', v, m, u) for u in urovni
                              for n, v, m in (('telefon', (844, 390), True), ('kompyuter', (1440, 900), False))]:
        c = b.new_context(viewport=dict(width=vp[0], height=vp[1]), is_mobile=mob, has_touch=mob, device_scale_factor=2 if mob else 1)
        s = c.new_page()
        s.on('console', lambda m: m.type == 'error' and oshibki.append(m.text))
        s.on('pageerror', lambda e: oshibki.append(str(e)))
        s.on('response', lambda r: r.status >= 400 and oshibki.append(f'{r.status} {r.url}'))
        if bez_svodki: s.route('**/pogoda-dnya.json', lambda r: r.fulfill(status=200, content_type='application/json', body='null'))
        s.goto(adres); s.wait_for_timeout(800)
        if bez_svodki: s.evaluate("() => { vybranaPogoda = POGODA.findIndex(p => p.id === 'sluchaynaya'); spisokPogody(); }")
        s.screenshot(path=f'{kuda}/igra-{imya}-start.png')
        s.click(f'#urovni button >> nth={ur}'); s.click('#b-start'); s.wait_for_timeout(2000)
        s.screenshot(path=f'{kuda}/igra-{imya}-samolet.png')
        snyato = set(); t0 = time.time()
        while time.time() - t0 < 200:
            sost = s.evaluate(AVTOPILOT)
            if sost == 'itog': break
            f = (sost or '').split(' ')[0]
            if f in ('padenie', 'kupol') and f not in snyato and s.evaluate('s.h') < (2000 if f == 'padenie' else 250):
                snyato.add(f); s.screenshot(path=f'{kuda}/igra-{imya}-{f}.png')
            s.wait_for_timeout(50)
        s.wait_for_timeout(500); s.screenshot(path=f'{kuda}/igra-{imya}-posadka.png')   # посадка видом сбоку
        s.wait_for_selector('#e-itog.vidno', timeout=8000)
        s.screenshot(path=f'{kuda}/igra-{imya}-itog.png')
        print(imya, s.inner_text('#zag-itog'), '|', s.inner_text('#itog-ochki'), '|', s.inner_text('#itog-razbor').replace('\n', ' '))
        c.close()
    b.close()
print('ошибки:', oshibki or 'нет')
sys.exit(1 if oshibki else 0)
