#!/usr/bin/env python3
"""Проверка погоды дня, ветра по высотам, отделения и посадки в сильный ветер.

    python proverka-pogody.py <адрес index.html> <каталог снимков>

Сводка `pogoda-dnya.json` подменяется своей (снег, запрет, слой облаков) — игра выбирает «Сегодня в Грызлово»,
пишет запрет, берёт зимние карты и профиль ветра из сводки. Без сводки — «нет сводки», погода по уровню.
Ветер по высотам: между точками профиля — по составляющим; на 6-м уровне наверху дует иначе, чем у земли.
Отделение: вниз — с нуля и к 10–12 с почти 50 м/с, вперёд — 44 м/с и к 10–12 с почти ноль, вынос 200–350 м
(AFF, с. 21). Широкая маска: лес за краем снимка учебника. За лесом при ветре 8 м/с — турбулентность.
Посадка при ветре 8 м/с: без клеванты — протащило ×0,5, клавишей ← сразу после касания — погашен +5.
"""
import sys, json, datetime
from playwright.sync_api import sync_playwright

adres, kuda = sys.argv[1], sys.argv[2]
oshibki, provaly = [], []


def proverit(uslovie, chto):
    print(('ок    ' if uslovie else 'ПРОВАЛ') + ' — ' + chto)
    if not uslovie: provaly.append(chto)


def svodka():
    """Сводка на сегодня и завтра по Москве: снег, ветер 3 м/с у земли и 12 м/с на 1500 м против него, пелена 1200 м."""
    msk = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=3))).date()
    chasy = {}
    for d in (msk, msk + datetime.timedelta(days=1)):
        for h in range(8, 21):
            chasy[f'{d.isoformat()}T{h:02d}'] = {
                't': -6, 'veter': [[10, 3, 90], [180, 5, 100], [800, 8, 180], [1500, 12, 270], [3000, 14, 270]],
                'poryvy': 5, 'sloi': [{'tip': 'sc', 'niz': 1200, 'verh': 1800, 'pokr': 1}],
                'osadki': 0, 'sneg': 0, 'kod': 3, 'zapret': 'облачность 1200 м — проверка'}
    return {'mesto': 'Большое Грызлово', 'data': msk.isoformat(), 'sezon': 'zima', 'snegM': 0.2,
            'obnovleno': '', 'istochnik': 'проверка', 'chasy': chasy}


def bezopasno(s, kod, arg=None):
    """Вычисление в странице; на прежнем коде функций нет — это провал, а не падение проверки."""
    try:
        return s.evaluate(kod, arg) if arg is not None else s.evaluate(kod)
    except Exception as e:
        return {'oshibka': str(e).splitlines()[0]}


NACH = """([W, h]) => { pauza = true; noviyPryzhok(0); s.faza = 'kupol'; knopkaPodushka(true); kR.classList.add('vidno');
  s.W = W; s.profil = [[10, W, s.veterKuda]]; s.poryv = 0; s.kurs = s.veterKuda + 180; s.h = h; s.x = 0; s.y = 0;
  s.v = F.kupolGor; s.vzK = F.kupolVert; Object.assign(s.trevogaBylo, { k1:1, k2:1, k3:1 });
  document.getElementById('e-start').classList.remove('vidno'); document.getElementById('e-itog').classList.remove('vidno'); }"""

with sync_playwright() as p:
    b = p.chromium.launch()

    # ── со сводкой ──
    s = b.new_context(viewport={'width': 1440, 'height': 900}).new_page()
    s.on('pageerror', lambda e: oshibki.append(str(e)))
    s.on('console', lambda m: m.type == 'error' and oshibki.append(m.text))
    s.route('**/pogoda-dnya.json', lambda r: r.fulfill(status=200, content_type='application/json',
                                                       body=json.dumps(svodka(), ensure_ascii=False)))
    s.goto(adres); s.wait_for_timeout(1500)
    vybrana = s.inner_text('#pogoda button[aria-pressed=true]') if s.query_selector('#pogoda button[aria-pressed=true]') else ''
    opis = s.inner_text('#pogoda-opis')
    proverit('Сегодня в Грызлово' in vybrana, f'по умолчанию — «Сегодня в Грызлово» ({vybrana.strip()[:40]!r})')
    proverit('Прыжков нет' in opis and 'проверка' in opis, 'запрет из сводки — на стартовом экране')
    s.screenshot(path=f'{kuda}/pogoda-start.png')
    z = bezopasno(s, "() => ({ sezon: SEZON, karta: imgDal && imgDal.src })")
    proverit(isinstance(z, dict) and z.get('sezon') == 'zima' and 'sezon/zima/karta-dal' in (z.get('karta') or ''),
             f'время года из сводки — зимние карты ({z})')
    r = bezopasno(s, """() => { pauza = true; noviyPryzhok(0); return { W: s.W, kuda: s.veterKuda, sloi: s.sloi.map(L => L.niz),
      v800: veterProfil(s.profil, 800).map(c => +c.toFixed(2)), v1150: Math.hypot(...veterProfil(s.profil, 1150)) } }""")
    ok = isinstance(r, dict) and r.get('W') == 3 and r.get('kuda') == 90 and 1200 in r.get('sloi', [])
    proverit(ok, f'прыжок «сегодня» — ветер у земли и облака из сводки ({r})')
    # 800 м: 8 м/с «куда» 180 — на юг, x ≈ 0, y ≈ +8; 1150 м — середина 8 и 12 по составляющим, меньше 10
    ok = isinstance(r, dict) and 'v800' in r and abs(r['v800'][0]) < 0.01 and abs(r['v800'][1] - 8) < 0.01 and 6 < r['v1150'] < 9
    proverit(ok, f'профиль ветра — по составляющим между точками ({r.get("v800") if isinstance(r, dict) else r})')
    # ветер на высоте сносит точку выброски: та же сводка с ветром 3 м/с на всех высотах — точка ближе к кругу
    r = bezopasno(s, """() => { POGODA[0].sloi = []; const d = []; for (let i = 0; i < 20; i++) { noviyPryzhok(0); d.push(s.x); }
      DEN = { ...DEN, veter: [[10, 3, 90], [3000, 3, 90]] };
      const t = []; for (let i = 0; i < 20; i++) { noviyPryzhok(0); t.push(s.x); }
      const sr = a => a.reduce((x, y) => x + y) / a.length; return [Math.round(sr(d)), Math.round(sr(t))]; }""")
    proverit(isinstance(r, list) and r[0] > r[1] + 300, f'ветер по высотам сдвигает точку выброски на восток, против ветра наверху (x с профилем и без: {r} м)')
    b2 = s.context

    # ── без сводки ──
    s2 = b.new_context(viewport={'width': 1440, 'height': 900}).new_page()
    s2.on('pageerror', lambda e: oshibki.append(str(e)))
    s2.on('console', lambda m: m.type == 'error' and 'pogoda-dnya' not in m.text and '404' not in m.text and oshibki.append(m.text))
    s2.route('**/pogoda-dnya.json', lambda r: r.fulfill(status=404, body=''))
    s2.goto(adres); s2.wait_for_timeout(1500)
    vybrana = s2.inner_text('#pogoda button[aria-pressed=true]') if s2.query_selector('#pogoda button[aria-pressed=true]') else ''
    r = bezopasno(s2, "() => { pauza = true; vybranaPogoda = 0; noviyPryzhok(3); return { sloi: POGODA[0].sloi, prof: s.profil.length } }")
    proverit('нет сводки' in vybrana and isinstance(r, dict) and r.get('sloi') is None and r.get('prof', 0) > 3,
             f'нет сводки — «нет сводки», погода и профиль по уровню ({r})')
    # 6-й уровень: наверху дует иначе, чем у земли («колено», AFF с. 36)
    r = bezopasno(s2, """() => { let n = 0; for (let i = 0; i < 20; i++) { const p = profilVetra(6, 0, 6);
      const d = ((p[p.length - 1][2] - p[0][2]) + 540) % 360 - 180; if (Math.abs(d - 35) >= 59 && p[p.length - 1][1] > 9) n++; } return n; }""")
    proverit(r == 20, f'6-й уровень — наверху ветер сильнее, а «колено» поворачивает его на 60–120° сверх обычных 35° ({r} из 20)')
    r = bezopasno(s2, "() => { const p = profilVetra(4, 30, 1); return p.every(q => q[2] === 30); }")
    proverit(r is True, '1-й уровень — ветер на всех высотах одного направления (ПМУ)')

    # отделение: вниз с нуля, вперёд — скорость самолёта
    r = bezopasno(s2, """() => { pauza = true; vybranaPogoda = 1; noviyPryzhok(0); s.profil = [[10, 0, 0]]; s.poryv = 0;
      s.h = 4000; s.samoletT = 4.59; shag(1/60); const x0 = s.x, y0 = s.y, o = {};
      while (s.tFF < 1) shag(1/60); o.vz1 = s.vz; o.vg1 = Math.hypot(...s.brosok);
      while (s.tFF < 11) shag(1/60); o.vz11 = s.vz; o.vg11 = Math.hypot(...s.brosok); o.snos = Math.hypot(s.x - x0, s.y - y0);
      for (const k in o) o[k] = +o[k].toFixed(1); return o; }""")
    ok = isinstance(r, dict) and r.get('vz1', 99) < 15 and r.get('vg1', 0) > 30 and r.get('vz11', 0) > 40 and r.get('vg11', 99) < 10 \
        and 200 <= r.get('snos', 0) <= 350
    proverit(ok, f'отделение: через 1 с ↓{r.get("vz1") if isinstance(r, dict) else r} вперёд {r.get("vg1") if isinstance(r, dict) else ""}, '
                 f'через 11 с ↓{r.get("vz11") if isinstance(r, dict) else ""} вперёд {r.get("vg11") if isinstance(r, dict) else ""}, вынос {r.get("snos") if isinstance(r, dict) else ""} м')

    # широкая маска: за краем снимка учебника — лес из OSM
    r = bezopasno(s2, "() => [grunt(6590, -3330), grunt(0, 0), MIR.dal[2] < 6590]")
    proverit(r == [1, 0, True], f'широкая маска: лес за краем учебника, круг — поле ({r})')
    # турбулентность: ветер 8 м/с дует из леса — в 100 м за опушкой на 40 м трясёт, с наветренной стороны — нет
    r = bezopasno(s2, """() => { pauza = true; noviyPryzhok(0); s.faza = 'kupol'; s.h = 40;
      const kuda = [0, 90, 180, 270]; let est = null;
      for (let y = -2000; y < 2500 && !est; y += 40) for (let x = -1900; x < 1900 && !est; x += 40) for (const k of kuda) {
        const [wx, wy] = vec(k); if (grunt(x, y) !== 0 || grunt(x - wx * 60, y - wy * 60) !== 1) continue;
        s.profil = [[10, 8, k]]; s.x = x; s.y = y; const za = turbulentnost();
        s.profil = [[10, 8, (k + 180) % 360]]; s.x = x + wx * 300; s.y = y + wy * 300;
        if (grunt(s.x, s.y) !== 0) continue; const pered = turbulentnost(); est = [+za.toFixed(2), +pered.toFixed(2)]; break; }
      return est; }""")
    proverit(isinstance(r, list) and r[0] > 0.3, f'турбулентность за лесом при 8 м/с: за опушкой {r[0] if isinstance(r, list) else r}')

    # посадка в ветер 8 м/с — без клеванты протащило
    s2.evaluate("document.getElementById('e-start').classList.remove('vidno')")
    bezopasno(s2, NACH, [8, 6]); s2.evaluate("pauza = false")
    try:
        s2.wait_for_function("s.posadka && s.posadka.t > 0.2", polling=10, timeout=20000)
        s2.screenshot(path=f'{kuda}/tyanet.png')
        s2.wait_for_selector('#e-itog.vidno', timeout=8000)
        razbor = s2.inner_text('#itog-razbor').replace('\n', ' ')
    except Exception as e:
        razbor = 'нет итога: ' + str(e).splitlines()[0]
    proverit('Протащило' in razbor and '×0,5' in razbor, f'ветер 8 м/с, клеванту не тянул: {razbor[:160]}')

    # то же, но сразу после касания — ← (одна клеванта до конца)
    bezopasno(s2, NACH, [8, 6]); s2.evaluate("pauza = false")
    try:
        s2.wait_for_function("s.posadka", polling=10, timeout=20000)
        s2.keyboard.down('ArrowLeft'); s2.wait_for_timeout(500)
        s2.screenshot(path=f'{kuda}/pogashen.png')
        s2.keyboard.up('ArrowLeft')
        s2.wait_for_selector('#e-itog.vidno', timeout=8000)
        razbor = s2.inner_text('#itog-razbor').replace('\n', ' ')
    except Exception as e:
        razbor = 'нет итога: ' + str(e).splitlines()[0]
    proverit('погашен' in razbor and '+5' in razbor and 'Протащило' not in razbor, f'ветер 8 м/с, ← после касания: {razbor[:160]}')
    b.close()
print('ошибки:', oshibki or 'нет')
sys.exit(1 if oshibki or provaly else 0)
