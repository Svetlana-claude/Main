#!/usr/bin/env python3
"""Проверка скоростей купола и фитиля.

    python proverka-fitilya.py <адрес index.html> <каталог снимков>

0) Свободное падение — в настоящем времени, ≈ 50 м за секунду по часам; спуск под куполом выше 300 м —
   с перемоткой ×6 (30 м за секунду по часам), на экране «⏩ ×6».
1) Полный режим в штиль: 10 м/с вперёд и 5 м/с вниз; полный круг на одной клеванте — 8 с игрового времени
   от её затягивания, и с перемоткой ×6, и без неё.
2) За лесом при ветре 8 м/с турбулентность крутит купол, но снижение остаётся 5 м/с — ветер на него не влияет.
3) Фитиль (?fitil=1): купол начал наполняться — снижение падает, затем фитилит и снова разгоняется до 35 м/с,
   строка «ФИТИЛЬ!»; пробел — отцепка и запасной,
   в разборе «Фитиль — запасной».
2а) Скорость игры (?skorost=): нормальная — без перемотки, ×1 — 6 / 2,5 / 1, ×2 — 12 / 5 / 1.
4) Фитиль без отцепки: прибор раскрывает запасной на 350 м — два купола: строка «ДВА КУПОЛА!»,
   ≈ 6,5 м/с вперёд и 6,5 вниз, на экране два купола (сверху и сбоку), в разборе «два купола».
   По AFF, с. 58: клеванты не ниже плеч (ход до 0,5), подушка не делается, посадка — «Перекат» без штрафа.
"""
import sys
from playwright.sync_api import sync_playwright

adres, kuda = sys.argv[1], sys.argv[2]
oshibki, provaly = [], []


def proverit(uslovie, chto):
    print(('ок    ' if uslovie else 'ПРОВАЛ') + ' — ' + chto)
    if not uslovie: provaly.append(chto)


def stranica(b, param):
    s = b.new_context(viewport={'width': 1440, 'height': 900}).new_page()
    s.on('pageerror', lambda e: oshibki.append(str(e)))
    s.on('console', lambda m: m.type == 'error' and oshibki.append(m.text))
    s.goto(adres + param + '&vremya=12:00'); s.wait_for_selector('#b-start')
    return s


def v_padenie(s, h):
    s.click('#b-start')
    s.wait_for_function("s && s.faza === 'padenie'", timeout=15000)
    s.evaluate(f"s.h = {h}; s.trevogaBylo.r1 = s.trevogaBylo.r2 = 1")


with sync_playwright() as p:
    b = p.chromium.launch()

    # ── 0–2. скорости в полном режиме ──
    s = stranica(b, '?fitil=0')
    v_padenie(s, 3900)
    s.wait_for_function("s.vz > 49", timeout=30000)                 # разгон после отделения закончился
    sek = "() => new Promise(ok => { const h0 = s.h, t0 = performance.now(); setTimeout(() => ok((h0 - s.h) / (performance.now() - t0) * 1000), 2000); })"
    v = s.evaluate(sek)
    proverit(45 < v < 55, f'свободное падение по часам: {v:.1f} м/с')
    s.evaluate("s.h = 2000")
    s.evaluate("raskryt()")
    s.wait_for_function("s.faza === 'kupol'", timeout=15000)
    s.evaluate("s.h = 1000; s.v = 4; s.vzK = 3; s.trevogaBylo.k1 = 1")
    s.wait_for_timeout(7000)
    v, vz = s.evaluate("[s.v, s.vzTek]")
    vch = s.evaluate(sek)
    per = s.evaluate("document.getElementById('peremotka')?.innerText ?? ''")
    proverit(27 < vch < 33 and per == '⏩ ×6', f'под куполом выше 300 м по часам: {vch:.1f} м/с вниз, на экране «{per}»')
    proverit(abs(v - 10) < 0.3 and abs(vz - 5) < 0.1, f'полный режим: {v:.2f} м/с вперёд, {vz:.2f} вниз')

    # полный круг: штиль, правая клеванта до упора; время — игровое (s.t), курс — накопленный
    krug = """h => new Promise(ok => { s.profil = [[10, 0, 0]]; s.poryv = 0; s.h = h; s.om = 0; s.omT = 0; s.dL = s.dP = 0;
      s.v = F.kupolGor; s.vzK = F.kupolVert;
      let k0 = s.kurs, ug = 0, t0 = s.t, pred = s.kurs; nazh.pravo = true;
      const id = setInterval(() => { s.h = h; ug += s.kurs - pred; pred = s.kurs;
        if (Math.abs(ug) >= 360) { clearInterval(id); nazh.pravo = false; ok([s.t - t0, s.usk]); } }, 5); })"""
    for h in (1000, 45):
        t, usk = s.evaluate(krug, h)
        proverit(abs(t - 8) < 0.25, f'полный круг с {h} м (перемотка ×{usk:g}): {t:.2f} с')
        s.evaluate("s.om = 0; s.dL = s.dP = 0; s.h = 1000"); s.wait_for_timeout(1500)

    r = s.evaluate("""() => { pauza = true;
      for (let y = -2000; y < 2500; y += 40) for (let x = -1900; x < 1900; x += 40) for (const k of [0, 90, 180, 270]) {
        const [wx, wy] = vec(k); if (grunt(x, y) !== 0 || grunt(x - wx * 60, y - wy * 60) !== 1) continue;
        s.profil = [[10, 8, k]]; s.poryv = 0; s.x = x; s.y = y; s.h = 40;
        if (turbulentnost() > 0.3) return true; }
      return false; }""")
    proverit(r, 'нашлось место за лесом с турбулентностью')
    s.evaluate("s.kurs = 0; s.om = 0; s.h = 60; s.trevogaBylo.k3 = s.trevogaBylo.sv = 1; pauza = false")
    zamery = s.evaluate("""() => new Promise(ok => { const z = []; const id = setInterval(() => {
      if (s.faza === 'kupol' && s.h > 20) z.push([s.turb, s.vzTek]); if (z.length >= 25 || s.h <= 20) { clearInterval(id); ok(z); } }, 40); })""")
    turb = [t for t, _ in zamery if t > 0]
    vzs = [round(v, 2) for _, v in zamery]
    proverit(turb and all(abs(v - 5) < 0.1 for v in vzs),
             f'турбулентность {max(turb) if turb else 0:.2f}, снижение {min(vzs)}…{max(vzs)} м/с')
    s.context.close()

    # ── 2а. скорость игры: перемотка под куполом выше 300 м, 300–50 м и ниже 50 м ──
    for sk, zhdu in (('norma', [1, 1, 1]), ('x1', [6, 2.5, 1]), ('x2', [12, 5, 1])):
        s = stranica(b, f'?fitil=0&skorost={sk}')
        v_padenie(s, 1500)
        s.evaluate("raskryt()"); s.wait_for_function("s.faza === 'kupol'", timeout=15000)
        est = []
        for h in (1000, 200, 40):
            s.evaluate(f"s.h = {h}; Object.assign(s.trevogaBylo, {{ k1:1, k2:1, k3:1, k4:1 }})"); s.wait_for_timeout(300)
            est.append(s.evaluate("s.usk"))
        proverit(est == zhdu, f'скорость игры {sk}: перемотка {est}')
        s.context.close()

    # ── 3. фитиль и отцепка ──
    s = stranica(b, '?fitil=1')
    v_padenie(s, 3900)
    s.wait_for_function("s.vz > 45", timeout=30000)
    s.evaluate("s.h = 1500; raskryt()")
    # скорость по ходу раскрытия: сперва гаснет, с началом фитиля растёт
    hod = s.evaluate("""() => new Promise(ok => { const z = []; const id = setInterval(() => {
      z.push([s.t, s.vz]); if (s.t > 5) { clearInterval(id); ok(z); } }, 50); })""")
    vmin = min(v for _, v in hod); tmin = next(t for t, v in hod if v == vmin)
    proverit(vmin < 32 and tmin < 2 and hod[-1][1] > vmin + 5,
             f'фитиль: при раскрытии до {vmin:.0f} м/с, потом разгон до {hod[-1][1]:.0f} м/с')
    s.wait_for_timeout(3000)
    faza, fitil, vz, tekst = s.evaluate("[s.faza, s.fitil, s.vz, document.getElementById('soobshenie').innerText]")
    s.screenshot(path=f'{kuda}/fitil.png')
    proverit(faza == 'raskrytie' and fitil and abs(vz - 35) < 1.5, f'фитиль: снижение {vz:.1f} м/с ({faza})')
    proverit('ФИТИЛЬ' in tekst, f'строка — «{tekst}»')
    s.keyboard.press('Space')
    s.wait_for_function("s.faza === 'kupol'", timeout=10000)
    zap, vys = s.evaluate("[s.zapasnoy, s.raskrytVys]")
    proverit(zap and vys > 900, f'пробел — отцепка, запасной на {vys} м')
    s.evaluate("s.h = 30; s.x = 0; s.y = 0; s.trevogaBylo.k3 = s.trevogaBylo.k4 = 1")
    s.wait_for_selector('#e-itog.vidno', timeout=30000)
    razbor = s.inner_text('#itog-razbor').replace('\n', ' ')
    proverit('Фитиль — запасной' in razbor, f'разбор: {razbor[:90]}')
    s.context.close()

    # ── 4. фитиль без отцепки — прибор ──
    s = stranica(b, '?fitil=1')
    v_padenie(s, 700)
    s.evaluate("raskryt()")
    s.wait_for_function("s.zapasnoy", timeout=20000, polling=10)
    vys = s.evaluate("s.raskrytVys")
    proverit(340 <= vys <= 350, f'без отцепки — прибор на {vys} м')
    s.wait_for_function("s.faza === 'kupol'", timeout=10000)
    dva, tekst = s.evaluate("[s.dvaKupola, document.getElementById('soobshenie').innerText]")
    proverit(dva is True and 'ДВА КУПОЛА' in tekst, f'два купола: «{tekst[:60]}»')
    s.evaluate("s.h = 250; s.x = 0; s.y = 0; s.trevogaBylo.k1 = s.trevogaBylo.k2 = 1")
    s.wait_for_timeout(2500)
    v, vz = s.evaluate("[s.v, s.vzTek]")
    s.screenshot(path=f'{kuda}/dva-kupola.png')
    proverit(abs(v - 6.5) < 0.3 and abs(vz - 6.5) < 0.2, f'на двух куполах: {v:.1f} м/с вперёд, {vz:.1f} вниз')
    s.evaluate("s.h = 35; s.x = 0; s.y = 0; s.trevogaBylo.k3 = s.trevogaBylo.k4 = 1")   # садимся в круг — в разборе будет посадка
    s.wait_for_function("bokVid()", timeout=10000); s.wait_for_timeout(500)
    s.screenshot(path=f'{kuda}/dva-kupola-sboku.png')
    # по AFF, с. 58: клеванты не ниже плеч, подушку не делать
    s.keyboard.down('ArrowRight'); s.wait_for_timeout(700)
    dP = s.evaluate("s.dP"); s.keyboard.up('ArrowRight')
    proverit(dP <= 0.51, f'на двух куполах клеванта не ниже плеч: ход {dP:.2f}')
    s.keyboard.down('ArrowUp'); s.wait_for_timeout(700)
    dL, dP, tekst = s.evaluate("[s.dL, s.dP, document.getElementById('soobshenie').innerText]")
    proverit(dL < 0.05 and dP < 0.05 and 'подушку не делаем' in tekst, f'подушка на двух куполах не делается: ход {dL:.2f}/{dP:.2f}, «{tekst[:45]}»')
    s.keyboard.up('ArrowUp')
    s.wait_for_selector('#e-itog.vidno', timeout=30000)
    razbor = s.inner_text('#itog-razbor').replace('\n', ' ')
    proverit('два купола' in razbor and 'Перекат — два купола' in razbor and 'большая скорость' not in razbor, f'разбор: {razbor[:200]}')
    b.close()
print('ошибки:', oshibki or 'нет')
sys.exit(1 if oshibki or provaly else 0)
