#!/usr/bin/env python3
"""Проверка фигур свободного падения: клавиатура и сенсорные джойстики.

    python proverka-padeniya.py <адрес index.html> <каталог снимков>

Компьютер: ↑ — вперёд, ↓ — назад, ← — поворот, Shift+↑ — сальто вперёд,
Shift+→ — на спину, Shift — прогнуться (обратно на живот), ниже 2000 м фигур нет,
раскрытие на спине — «не лицом к земле», фигуры в разборе очков.
Телефон: одна кнопка вверх — вперёд, просто нажать правую — поворот вправо,
обе вверх (два пальца) — сальто вперёд, обе вниз — сальто назад.
"""
import sys
from playwright.sync_api import sync_playwright

adres, kuda = sys.argv[1], sys.argv[2]
oshibki, provaly = [], []


def proverit(uslovie, chto):
    print(('ок    ' if uslovie else 'ПРОВАЛ') + ' — ' + chto)
    if not uslovie: provaly.append(chto)


def v_padenie(s, h=3500):
    """Новый прыжок, свободное падение на высоте h."""
    s.click('#b-start') if s.is_visible('#b-start') else s.click('#b-eshe')
    s.wait_for_function("s && s.faza === 'padenie'", timeout=15000)
    s.evaluate(f"s.h = {h}; s.trevogaBylo.r1 = s.trevogaBylo.r2 = 1")


def zhdat(s, uslovie, ms=8000):
    try:
        s.wait_for_function(uslovie, timeout=ms); return True
    except Exception:
        return False


with sync_playwright() as p:
    b = p.chromium.launch()
    # ── компьютер ──
    c = b.new_context(viewport={'width': 1440, 'height': 900})
    s = c.new_page()
    s.on('pageerror', lambda e: oshibki.append(str(e)))
    s.on('console', lambda m: m.type == 'error' and oshibki.append(m.text))
    s.goto(adres); s.wait_for_timeout(800)
    s.click('#b-upr')
    proverit(s.is_visible('#e-upr') and 'Сальто вперёд' in s.inner_text('#e-upr') and not s.is_visible('#e-upr th.tolko-sensor'),
             'экран «Управление» открывается, на компьютере — колонка клавиш')
    s.screenshot(path=f'{kuda}/upr-kompyuter.png')
    s.click('#b-upr-nazad')
    s.click('#urovni button >> nth=0')
    v_padenie(s)
    proverit('Shift' in s.inner_text('#klavishi'), 'подсказка клавиш в падении — с Shift')
    s.keyboard.down('ArrowUp'); s.wait_for_timeout(1500)
    vg = s.evaluate('s.vg'); poza = s.inner_text('#poza')
    s.screenshot(path=f'{kuda}/padenie-vpered.png')
    s.keyboard.up('ArrowUp')
    proverit(vg > 8 and 'ВПЕРЁД' in poza, f'↑ — движение вперёд ({vg:.1f} м/с, «{poza}»)')
    proverit(s.evaluate("s.faza") == 'padenie', '↑ в падении не раскрывает парашют')
    s.keyboard.down('ArrowDown'); s.wait_for_timeout(1500)
    vg = s.evaluate('s.vg'); s.keyboard.up('ArrowDown')
    proverit(vg < -3, f'↓ — движение назад ({vg:.1f} м/с)')
    s.keyboard.down('ArrowLeft'); s.wait_for_timeout(700)
    om = s.evaluate('s.om'); s.keyboard.up('ArrowLeft')
    proverit(om < -20, f'← — поворот влево ({om:.0f}°/с)')
    s.wait_for_timeout(400)
    s.evaluate("s.h = 3500")
    s.keyboard.down('Shift'); s.keyboard.down('ArrowUp'); s.wait_for_timeout(200)
    tip = s.evaluate("s.fig && s.fig.tip")
    s.wait_for_timeout(450); s.screenshot(path=f'{kuda}/padenie-salto.png')
    s.keyboard.up('ArrowUp'); s.keyboard.up('Shift')
    proverit(tip == 'saltoV', f'Shift+↑ — сальто вперёд ({tip})')
    proverit(zhdat(s, "!s.fig && s.figury.includes('saltoV')"), 'сальто закончилось, засчитано')
    s.evaluate("s.h = 3500")
    s.keyboard.down('Shift'); s.keyboard.down('ArrowRight'); s.wait_for_timeout(100)
    s.keyboard.up('ArrowRight'); s.keyboard.up('Shift')
    proverit(zhdat(s, "s.poza === 'spina' && !s.fig"), 'Shift+→ — переворот на спину')
    s.screenshot(path=f'{kuda}/padenie-spina.png')
    proverit('СПИНЕ' in s.inner_text('#poza'), f'на приборе — «{s.inner_text("#poza")}»')
    s.keyboard.down('Shift'); s.wait_for_timeout(200); s.keyboard.up('Shift')
    proverit(zhdat(s, "s.poza === 'zhivot' && !s.fig && s.figury.includes('bochka')"), 'Shift — прогнулся, снова на животе')
    s.evaluate("s.h = 1900")
    s.keyboard.down('Shift'); s.keyboard.down('ArrowDown'); s.wait_for_timeout(200)
    fig = s.evaluate("s.fig"); soob = s.inner_text('#soobshenie')
    s.keyboard.up('ArrowDown'); s.keyboard.up('Shift')
    proverit(fig is None and 'Ниже 2000' in soob, f'ниже 2000 м сальто нет — «{soob}»')
    # на спину и раскрытие на спине
    s.evaluate("s.h = 3000")
    s.keyboard.down('Shift'); s.keyboard.down('ArrowLeft'); s.wait_for_timeout(100)
    s.keyboard.up('ArrowLeft'); s.keyboard.up('Shift')
    zhdat(s, "s.poza === 'spina' && !s.fig")
    s.evaluate("s.h = 1000"); s.keyboard.press('Space')
    proverit(s.evaluate("s.nestab") is True and 'лицом' in s.inner_text('#soobshenie'), 'раскрытие на спине — предупреждение')
    s.wait_for_function("s.faza === 'kupol'", timeout=15000)
    s.evaluate("s.h = 25; s.x = 0; s.y = 0")
    s.wait_for_selector('#e-itog.vidno', timeout=60000)
    razbor = s.inner_text('#itog-razbor').replace('\n', ' ')
    proverit('не лицом к земле' in razbor and 'Сальто вперёд' in razbor and 'Переворот на спину' in razbor,
             f'в разборе — ×0,5 за раскрытие и фигуры: {razbor[:200]}')
    c.close()

    # ── телефон: джойстики ──
    c = b.new_context(viewport={'width': 844, 'height': 390}, is_mobile=True, has_touch=True, device_scale_factor=2)
    s = c.new_page()
    s.on('pageerror', lambda e: oshibki.append(str(e)))
    s.on('console', lambda m: m.type == 'error' and oshibki.append(m.text))
    cdp = c.new_cdp_session(s)
    s.goto(adres); s.wait_for_timeout(800)
    s.click('#urovni button >> nth=0')
    v_padenie(s)
    L = s.locator('#k-levo').bounding_box(); P = s.locator('#k-pravo').bounding_box()
    lx, ly = L['x'] + L['width'] / 2, L['y'] + L['height'] / 2
    px, py = P['x'] + P['width'] / 2, P['y'] + P['height'] / 2
    sdvig = L['width'] * 0.45

    def kasanie(tip, tochki):
        cdp.send('Input.dispatchTouchEvent', {'type': tip, 'touchPoints': [{'x': x, 'y': y, 'id': i} for i, (x, y) in tochki]})

    # одна кнопка вверх — вперёд
    kasanie('touchStart', [(0, (lx, ly))])
    for k in range(1, 6): kasanie('touchMove', [(0, (lx, ly - sdvig * k / 5))]); s.wait_for_timeout(30)
    s.wait_for_timeout(1500)
    vg = s.evaluate('s.vg'); tr = s.evaluate("document.querySelector('#k-levo .ruchka').style.transform")
    s.screenshot(path=f'{kuda}/telefon-vpered.png')
    kasanie('touchEnd', [])
    proverit(vg > 6 and 'translate' in tr, f'левая кнопка вверх — вперёд ({vg:.1f} м/с), ручка сдвинулась')
    # правая — просто нажать: поворот вправо
    kasanie('touchStart', [(1, (px, py))]); s.wait_for_timeout(800)
    om = s.evaluate('s.om'); kasanie('touchEnd', [])
    proverit(om > 15, f'нажать правую — поворот вправо ({om:.0f}°/с)')
    s.wait_for_timeout(400)
    # обе вверх — сальто вперёд
    s.evaluate("s.h = 3500")
    kasanie('touchStart', [(0, (lx, ly)), (1, (px, py))])
    for k in range(1, 6):
        kasanie('touchMove', [(0, (lx, ly - sdvig * k / 5)), (1, (px, py - sdvig * k / 5))]); s.wait_for_timeout(30)
    s.wait_for_timeout(100)
    tip = s.evaluate("s.fig && s.fig.tip")
    kasanie('touchEnd', [])
    proverit(tip == 'saltoV', f'обе кнопки вверх — сальто вперёд ({tip})')
    zhdat(s, "!s.fig")
    s.evaluate("s.h = 3500")
    kasanie('touchStart', [(0, (lx, ly)), (1, (px, py))])
    for k in range(1, 6):
        kasanie('touchMove', [(0, (lx, ly + sdvig * k / 5)), (1, (px, py + sdvig * k / 5))]); s.wait_for_timeout(30)
    s.wait_for_timeout(100)
    tip = s.evaluate("s.fig && s.fig.tip")
    kasanie('touchEnd', [])
    proverit(tip == 'saltoN', f'обе кнопки вниз — сальто назад ({tip})')
    proverit(s.locator('.knopka:visible').count() == 3, 'на экране те же кнопки: две боковые и «Раскрыть»')
    c.close()
    b.close()
print('ошибки:', oshibki or 'нет')
sys.exit(1 if oshibki or provaly else 0)
