#!/usr/bin/env python3
"""Проверка скоростей купола и фитиля.

    python proverka-fitilya.py <адрес index.html> <каталог снимков>

0) Время настоящее: в свободном падении высота уходит ≈ 50 м за секунду, под куполом — 5 м.
1) Полный режим: купол разгоняется до 12 м/с вперёд и 5 м/с вниз.
2) За лесом при ветре 8 м/с турбулентность крутит купол, но снижение остаётся 5 м/с — ветер на него не влияет.
3) Фитиль (?fitil=1): купол начал наполняться — снижение падает, затем фитилит и снова разгоняется до 35 м/с,
   строка «ФИТИЛЬ!»; пробел — отцепка и запасной,
   в разборе «Фитиль — запасной».
4) Фитиль без отцепки: прибор раскрывает запасной на 350 м.
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
    proverit(4.5 < vch < 5.5, f'под куполом по часам: {vch:.1f} м/с вниз')
    proverit(abs(v - 12) < 0.3 and abs(vz - 5) < 0.1, f'полный режим: {v:.2f} м/с вперёд, {vz:.2f} вниз')

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
    b.close()
print('ошибки:', oshibki or 'нет')
sys.exit(1 if oshibki or provaly else 0)
