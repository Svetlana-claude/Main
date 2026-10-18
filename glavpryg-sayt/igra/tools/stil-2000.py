#!/usr/bin/env python3
"""Три стиля главного вида игры с отсылкой к 2000-м — по настоящему кадру.

    python stil-2000.py <кадр.png> <nadpisi.json> <каталог шрифтов> <каталог>

Кадр — холст игры без надписей (576×360), nadpisi.json — подписи игры (текст и точка).
В каталоге шрифтов: Oswald[wght].ttf, PixelifySans.ttf (Google Fonts, OFL).
Выход: stil-sa.png («Сан-Андреас»), stil-xp.png («Икс-Пи и глянец»), stil-java.png
(Java-игра на телефоне), 1280×800.
"""
import json
import math
import sys
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageEnhance

kadr_put, nadpisi_put, shrifty, kuda = sys.argv[1:5]
KADR = Image.open(kadr_put).convert('RGB')
NADPISI = [n for n in json.load(open(nadpisi_put)) if 0 <= n['x'] <= 576 and 0 <= n['y'] <= 360 and '%' not in n['t']]
W, H = 1280, 800
K = W / 576                                   # кадр игры → 1280×800
IGROK, KRUG = (288, 360 * 0.58), (300, 65)    # где на кадре парашютист и центр круга
DEJAVU = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
SERIF = '/usr/share/fonts/truetype/dejavu/DejaVuSerif-BoldItalic.ttf'
LIBER = '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf'


def oswald(r):
    f = ImageFont.truetype(f'{shrifty}/Oswald[wght].ttf', r)
    f.set_variation_by_axes([700])
    return f


def F(put, r):
    return ImageFont.truetype(put, r)


def klassy(im):
    """Что на кадре: поле, трава, лес, вода, светлое (дороги, дома, линии), купол, точки захода."""
    a = np.asarray(im).astype(int); R, G, B = a[..., 0], a[..., 1], a[..., 2]
    L = (R * 3 + G * 6 + B) / 10
    k = np.full(R.shape, 'pole_t', dtype=object)
    k[L > np.median(L)] = 'pole_s'
    k[(G >= R - 8) & (G > B + 40)] = 'trava'
    k[(L < 110) & (G > R)] = 'les'
    k[(L > 195) & (np.abs(R - B) < 90)] = 'svet'
    k[(B > R + 40) & (B > G - 10)] = 'voda'
    k[(B > 200) & (G > 170) & (R < 140)] = 'goluboy'
    k[(R > 220) & (G > 190) & (B < 90)] = 'zhyoltyy'
    k[(R > 225) & (G < 160) & (B < 90)] = 'kupol'
    k[L < 45] = 'chyornyy'
    return k


KL = klassy(KADR)


def perekrasit(cveta, osnova=None):
    """Кадр в новых цветах по классам; классы без цвета берутся из исходного кадра."""
    out = np.asarray(osnova or KADR).copy()
    for imya, hexc in cveta.items():
        out[KL == imya] = [int(hexc[i:i + 2], 16) for i in (0, 2, 4)]
    return Image.fromarray(out)


def gradient(razmer, verh, niz):
    w, h = razmer
    g = Image.new('RGBA', (1, h))
    for y in range(h):
        t = y / max(1, h - 1)
        g.putpixel((0, y), tuple(round(verh[i] + (niz[i] - verh[i]) * t) for i in range(len(verh))))
    return g.resize((w, h))


def vinetka(im, sila=0.55, r=0.75):
    m = Image.new('L', im.size, 0)
    w, h = im.size
    ImageDraw.Draw(m).ellipse((w * (0.5 - r), h * (0.5 - r), w * (0.5 + r), h * (0.5 + r)), fill=255)
    m = m.filter(ImageFilter.GaussianBlur(min(w, h) * 0.18))
    temn = Image.new('RGB', im.size, (0, 0, 0))
    return Image.composite(im, Image.blend(im, temn, sila), m)


# ───────── 1. «Сан-Андреас»: PS2, радар, часы и деньги, название района ─────────
def sa():
    im = KADR.resize((W, H), Image.Resampling.LANCZOS)
    im = ImageEnhance.Color(im).enhance(0.85).filter(ImageFilter.GaussianBlur(0.8))   # мыльная PS2-картинка
    im = Image.blend(im, Image.new('RGB', im.size, (255, 196, 120)), 0.13)              # оранжевая дымка
    yark = im.convert('L').point(lambda v: 255 if v > 200 else 0).filter(ImageFilter.GaussianBlur(14))
    im = Image.composite(Image.blend(im, Image.new('RGB', im.size, (255, 250, 235)), 0.35), im, yark)   # свечение
    im = vinetka(im, 0.4)
    d = ImageDraw.Draw(im, 'RGBA')
    # контрольная точка миссии — красный светящийся цилиндр на круге
    kx, ky = KRUG[0] * K, KRUG[1] * K
    for r, a in ((120, 40), (100, 70), (86, 110)):
        d.ellipse((kx - r, ky - r * 0.9, kx + r, ky + r * 0.9), outline=(230, 30, 30, a), width=10)
    for n in [n for n in NADPISI if not (n['x'] * K < 600 and n['y'] * K < 180)]:   # под плашкой подсказки — нет
        d.text((n['x'] * K, n['y'] * K - 4), n['t'], font=oswald(30), fill=(255, 255, 255), anchor='ms',
               stroke_width=3, stroke_fill=(0, 0, 0))
    # подсказка — чёрная плашка слева сверху, как в игре
    d.rounded_rectangle((28, 28, 560, 150), radius=8, fill=(0, 0, 0, 170))
    d.multiline_text((48, 44), 'Над точкой III разворачивайся\nпротив ветра. Тяни обе клеванты\nна 5 м — ~ПОДУШКА~.'.replace('~', ''),
                     font=F(LIBER, 25), fill=(235, 235, 235), spacing=8)
    # справа сверху: значок «оружия» — парашют, часы, полоска, «деньги», звёзды розыска = уровень
    ix, iy = 920, 40
    d.ellipse((ix, iy, ix + 110, iy + 110), fill=(20, 20, 20, 200), outline=(0, 0, 0), width=4)
    d.pieslice((ix + 18, iy + 22, ix + 92, iy + 96), 180, 360, fill=(255, 122, 26), outline=(0, 0, 0), width=3)
    for x in (ix + 22, ix + 55, ix + 88):
        d.line((x, iy + 59, ix + 55, iy + 92), fill=(230, 230, 230), width=2)
    d.ellipse((ix + 48, iy + 86, ix + 62, iy + 100), fill=(40, 60, 140))
    d.text((1250, 38), '13:00', font=oswald(56), fill=(225, 225, 225), anchor='ra', stroke_width=4, stroke_fill=(0, 0, 0))
    d.rectangle((1052, 112, 1250, 132), fill=(0, 0, 0)); d.rectangle((1056, 116, 1210, 128), fill=(180, 25, 30))
    d.text((1250, 140), '000100', font=oswald(50), fill=(54, 104, 44), anchor='ra', stroke_width=4, stroke_fill=(0, 0, 0))
    for i in range(6):
        cx, cy, r = 1236 - i * 40, 230, 16
        tochki = [(cx + r * math.cos(math.radians(-90 + j * 36)) * (1 if j % 2 == 0 else 0.45),
                   cy + r * math.sin(math.radians(-90 + j * 36)) * (1 if j % 2 == 0 else 0.45)) for j in range(10)]
        d.polygon(tochki, fill=(200, 160, 40) if i == 0 else (40, 40, 40), outline=(0, 0, 0))
    # радар слева снизу
    rx, ry, rr, rk = 150, 640, 112, 0.42
    karta = perekrasit({'pole_t': '5d6b4c', 'pole_s': '6b7856', 'trava': '74845a', 'les': '3d4f35', 'svet': 'd8d8d8',
                        'voda': '3b5f8f', 'goluboy': '6b7856', 'zhyoltyy': '6b7856', 'kupol': '6b7856', 'chyornyy': '2a2a2a'})
    karta = karta.resize((round(576 * rk), round(360 * rk)), Image.Resampling.LANCZOS)   # радар — мельче, обзор шире
    m = karta.size[0] / 576
    sloy = Image.new('RGB', (rr * 2, rr * 2), (100, 113, 81))   # за краем кадра — тот же цвет поля
    sloy.paste(karta, (round(rr - IGROK[0] * m), round(rr - IGROK[1] * m)))
    maska = Image.new('L', sloy.size, 0); ImageDraw.Draw(maska).ellipse((0, 0, rr * 2, rr * 2), fill=255)
    d.ellipse((rx - rr - 8, ry - rr - 8, rx + rr + 8, ry + rr + 8), fill=(0, 0, 0))
    im.paste(sloy, (rx - rr, ry - rr), maska)
    d = ImageDraw.Draw(im, 'RGBA')
    bx, by = rx + (KRUG[0] - IGROK[0]) * m, ry + (KRUG[1] - IGROK[1]) * m
    d.rectangle((bx - 8, by - 8, bx + 8, by + 8), fill=(230, 40, 40), outline=(0, 0, 0), width=2)
    d.polygon([(rx, ry - 14), (rx - 10, ry + 10), (rx, ry + 4), (rx + 10, ry + 10)], fill=(255, 255, 255), outline=(0, 0, 0))
    d.ellipse((rx - 15, ry - rr - 24, rx + 15, ry - rr + 6), fill=(0, 0, 0))
    d.text((rx, ry - rr - 9), 'С', font=F(LIBER, 22), fill=(255, 255, 255), anchor='mm')
    # название района справа снизу
    d.text((1240, 720), 'Большое Грызлово', font=F(SERIF, 54), fill=(150, 190, 225), anchor='rs',
           stroke_width=4, stroke_fill=(0, 0, 0))
    im.save(f'{kuda}/stil-sa.png')


# ───────── 2. «Икс-Пи и глянец»: окно Windows XP, гелевые кнопки, пузыри, блик ─────────
def gel(d, box, cvet, tekst_, f, aktiv=True):
    """Гелевая кнопка-«пилюля»: цвет, сверху белый блик."""
    x0, y0, x1, y1 = box
    r = (y1 - y0) // 2
    d.rounded_rectangle(box, radius=r, fill=cvet if aktiv else (190, 205, 220, 230), outline=(255, 255, 255, 200), width=2)
    d.rounded_rectangle((x0 + 6, y0 + 3, x1 - 6, y0 + (y1 - y0) * 0.48), radius=r - 3, fill=(255, 255, 255, 110))
    d.text(((x0 + x1) / 2, (y0 + y1) / 2 + 1), tekst_, font=f, fill=(255, 255, 255) if aktiv else (70, 90, 120),
           anchor='mm', stroke_width=1 if aktiv else 0, stroke_fill=(0, 0, 0, 90))


def xp():
    zag, niz = 34, 44                                         # заголовок окна и панель задач
    vys = H - zag - niz
    igra = perekrasit({'pole_t': '4f9e2d', 'pole_s': '62b23a', 'trava': '8fd04e', 'les': '2c7428', 'svet': 'f4f8ff',
                       'voda': '1e9be0', 'zhyoltyy': 'ffe14a'})
    # кадр на всю ширину окна, лишняя высота срезается поровну
    kk = W / 576; oy = (360 * kk - vys) / 2
    igra = igra.resize((W, round(360 * kk)), Image.Resampling.LANCZOS).crop((0, round(oy), W, round(oy) + vys))
    igra = ImageEnhance.Color(igra).enhance(1.15)
    dx = 0

    def svet_(maska, cvet, razmyt=0):
        """Наложить цвет по маске (L): блики и пузыри смешиваются с картинкой, а не замещают её."""
        nonlocal igra
        if razmyt: maska = maska.filter(ImageFilter.GaussianBlur(razmyt))
        igra = Image.composite(Image.new('RGB', igra.size, cvet), igra, maska)

    # глянец: светлое «небо» сверху, блик-«линза» с отражениями, пузыри
    gl = Image.new('L', (W, vys), 0)
    gl.paste(Image.linear_gradient('L').rotate(180).resize((W, vys // 3)).point(lambda v: v * 0.5), (0, 0))
    svet_(gl, (255, 255, 255))
    # мягкие облачка — «аэро»-небо поверх карты
    m = Image.new('L', (W, vys), 0); dm = ImageDraw.Draw(m)
    for cx, cy in ((260, 560), (980, 180)):
        for ox, oy, r in ((0, 0, 60), (55, -20, 70), (115, 5, 55), (60, 25, 60)):
            dm.ellipse((cx + ox - r, cy + oy - r, cx + ox + r, cy + oy + r), fill=150)
    svet_(m, (255, 255, 255), 14)
    m = Image.new('L', (W, vys), 0); dm = ImageDraw.Draw(m)
    for r, a in ((260, 40), (150, 70), (60, 160)):
        dm.ellipse((1150 - r, 40 - r, 1150 + r, 40 + r), fill=a)
    svet_(m, (255, 255, 235), 8)
    m = Image.new('L', (W, vys), 0); dm = ImageDraw.Draw(m)
    bliki = Image.new('L', (W, vys), 0); dbl = ImageDraw.Draw(bliki)
    for x, y, r in ((70, 520, 34), (130, 600, 18), (40, 640, 12), (1210, 300, 28), (1160, 360, 14)):
        dm.ellipse((x - r, y - r, x + r, y + r), fill=50, outline=200, width=2)
        dbl.ellipse((x - r * 0.55, y - r * 0.7, x - r * 0.05, y - r * 0.3), fill=220)
    svet_(m, (225, 248, 255), 0.6); svet_(bliki, (255, 255, 255), 0.8)
    d = ImageDraw.Draw(igra, 'RGBA')
    for n in NADPISI:
        x, y = n['x'] * kk - dx, n['y'] * kk
        d.text((x + 2, y - 2), n['t'], font=F(DEJAVU, 22), fill=(0, 40, 90, 120), anchor='ms')
        d.text((x, y - 4), n['t'], font=F(DEJAVU, 22), fill=(255, 255, 255), anchor='ms')
    # высотомер — круглый «гаджет боковой панели»: хром, стекло, стрелка
    gx, gy, gr = 110, 120, 84
    d.ellipse((gx - gr - 6, gy - gr - 6, gx + gr + 6, gy + gr + 6), fill=(150, 170, 190, 230), outline=(255, 255, 255), width=3)
    d.ellipse((gx - gr, gy - gr, gx + gr, gy + gr), fill=(20, 40, 70, 235))
    for i in range(4):
        a = math.radians(-90 + i * 90)
        d.text((gx + math.cos(a) * 62, gy + math.sin(a) * 62), str(i), font=F(DEJAVU, 20), fill=(220, 235, 255), anchor='mm')
    d.arc((gx - 74, gy - 74, gx + 74, gy + 74), -90, 0, fill=(230, 60, 40), width=8)
    a = math.radians(-90 + 0.38 * 90)
    d.line((gx, gy, gx + math.cos(a) * 66, gy + math.sin(a) * 66), fill=(255, 255, 255), width=4)
    d.text((gx, gy + 28), '380 м', font=F(DEJAVU, 20), fill=(140, 220, 255), anchor='mm')
    d.chord((gx - gr + 8, gy - gr + 8, gx + gr - 8, gy + gr - 8), 195, 345, fill=(255, 255, 255, 45))   # стекло
    # режимы купола — гелевые кнопки внизу
    f = F(DEJAVU, 22)
    for i, (t, akt) in enumerate((('Полный', True), ('Средний', False), ('Подушка', False))):
        gel(d, (250 + i * 180, vys - 70, 410 + i * 180, vys - 24), (255, 130, 30, 235), t, f, akt)
    # всплывающее сообщение «аськи» над треем
    bx0, by0 = 880, vys - 150
    d.rounded_rectangle((bx0, by0, 1260, vys - 20), radius=10, fill=(255, 255, 225, 245), outline=(110, 110, 110), width=1)
    d.polygon([(1180, vys - 20), (1205, vys - 20), (1215, vys)], fill=(255, 255, 225))
    lep = (bx0 + 32, by0 + 36)
    for i in range(5):                                     # цветок о пяти лепестках
        a = math.radians(i * 72 - 90)
        x, y = lep[0] + math.cos(a) * 12, lep[1] + math.sin(a) * 12
        d.ellipse((x - 9, y - 9, x + 9, y + 9), fill=(80, 190, 60))
    d.ellipse((lep[0] - 7, lep[1] - 7, lep[0] + 7, lep[1] + 7), fill=(230, 50, 40))
    d.text((bx0 + 60, by0 + 22), 'Инструктор', font=F(DEJAVU, 18), fill=(0, 0, 0))
    d.text((bx0 + 60, by0 + 52), 'Ветер у земли — штиль.\nЗаходи на точку I, 300 м :)', font=F('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 17),
           fill=(20, 20, 20), spacing=6)
    # окно: синий заголовок «Луны», кнопки, панель задач с «Пуском»
    im = Image.new('RGBA', (W, H), (0, 0, 0, 255))
    im.alpha_composite(gradient((W, zag), (0, 88, 238, 255), (0, 64, 200, 255)))
    im.alpha_composite(gradient((W, zag // 2), (60, 140, 255, 255), (20, 100, 245, 255)), (0, 0))
    d = ImageDraw.Draw(im, 'RGBA')
    d.rounded_rectangle((10, 7, 30, 27), radius=4, fill=(255, 130, 30))
    d.text((40, zag // 2), 'Точно в круг — Главпрыг', font=F(DEJAVU, 18), fill=(255, 255, 255), anchor='lm',
           stroke_width=1, stroke_fill=(0, 30, 100))
    for i, (znak, cv) in enumerate((('_', (40, 110, 240)), ('□', (40, 110, 240)), ('×', (225, 70, 40)))):
        x = W - 100 + i * 32
        d.rounded_rectangle((x, 5, x + 26, 29), radius=4, fill=cv, outline=(255, 255, 255), width=1)
        d.text((x + 13, 16), znak, font=F(DEJAVU, 18), fill=(255, 255, 255), anchor='mm')
    im.paste(igra, (0, zag))
    im.alpha_composite(gradient((W, niz), (40, 110, 230, 255), (20, 80, 200, 255)), (0, H - niz))
    im = im.convert('RGB')
    d = ImageDraw.Draw(im, 'RGBA')
    d.rounded_rectangle((-20, H - niz, 140, H), radius=18, fill=(60, 160, 60))
    d.rounded_rectangle((4, H - niz + 3, 130, H - niz + 16), radius=7, fill=(255, 255, 255, 50))
    d.text((66, H - niz // 2), 'прыжок', font=ImageFont.truetype(SERIF, 20), fill=(255, 255, 255), anchor='mm',
           stroke_width=1, stroke_fill=(0, 60, 0))
    d.rectangle((W - 150, H - niz, W, H), fill=(15, 140, 230))
    d.text((W - 24, H - niz // 2), '13:00', font=F(DEJAVU, 17), fill=(255, 255, 255), anchor='rm')
    d.rounded_rectangle((150, H - niz + 6, 420, H - 6), radius=4, fill=(30, 70, 190), outline=(90, 150, 255))
    d.text((170, H - niz // 2), 'Точно в круг', font=F(DEJAVU, 17), fill=(255, 255, 255), anchor='lm')
    im.save(f'{kuda}/stil-xp.png')


# ───────── 3. Java-игра на телефоне: экран 176×208, софт-клавиши, джойстик ─────────
def java():
    w, h = 176, 208
    kadr = KADR.crop((138, 0, 438, 355))
    ekr = perekrasit({'pole_t': '5aa02c', 'pole_s': '70b83c', 'trava': 'a0d84c', 'les': '2a6420', 'svet': 'f0f0e0',
                      'voda': '2878e0'}).crop((138, 0, 438, 355))
    ekr = ekr.resize((w, h), Image.Resampling.BOX).quantize(colors=48, dither=Image.Dither.NONE).convert('RGB')
    d = ImageDraw.Draw(ekr)
    pix = F(f'{shrifty}/PressStart2P.ttf', 8)      # пиксельный шрифт с кириллицей, как в телефонных играх
    # верхняя строка телефона: связь, время, батарея
    d.rectangle((0, 0, w, 13), fill=(10, 10, 30))
    for i in range(4):
        d.rectangle((3 + i * 4, 10 - i * 2, 5 + i * 4, 11), fill=(255, 255, 255))
    d.text((w // 2, 8), '13:00', font=pix, fill=(255, 255, 255), anchor='mm')
    d.rectangle((w - 22, 3, w - 5, 10), outline=(255, 255, 255)); d.rectangle((w - 20, 5, w - 9, 8), fill=(120, 230, 90))
    # табло игры: металлическая плашка с высотой и очками
    d.rectangle((0, 14, w, 30), fill=(40, 60, 110)); d.line((0, 14, w, 14), fill=(140, 170, 230))
    d.text((4, 22), 'ВЫС 380', font=pix, fill=(255, 220, 60), anchor='lm')
    d.text((w - 4, 22), '100', font=pix, fill=(255, 255, 255), anchor='rm')
    cx, cy = w - 36, 22
    d.polygon([(cx + 5 * math.cos(math.radians(-90 + j * 36)) * (1 if j % 2 == 0 else 0.45),
                cy + 5 * math.sin(math.radians(-90 + j * 36)) * (1 if j % 2 == 0 else 0.45)) for j in range(10)], fill=(255, 210, 40))
    # шкала высоты справа
    d.rectangle((w - 9, 40, w - 3, 160), fill=(20, 20, 40), outline=(255, 255, 255))
    d.rectangle((w - 8, 160 - round(120 * 380 / 1000), w - 4, 159), fill=(255, 140, 30))
    # софт-клавиши
    d.rectangle((0, h - 16, w, h), fill=(10, 10, 30))
    d.text((3, h - 8), 'МЕНЮ', font=pix, fill=(255, 255, 255), anchor='lm')
    d.text((w // 2, h - 8), 'ПОЛНЫЙ', font=pix, fill=(255, 150, 40), anchor='mm')
    d.text((w - 3, h - 8), 'ПАУЗА', font=pix, fill=(255, 255, 255), anchor='rm')
    k = 2
    ekr = ekr.resize((w * k, h * k), Image.Resampling.NEAREST)
    # стол и телефон-«слайдер»: тёмно-серебристый корпус, экран, джойстик, клавиши
    im = gradient((W, H), (36, 40, 52, 255), (14, 16, 22, 255)).convert('RGB')
    d = ImageDraw.Draw(im, 'RGBA')
    tx0, tw = W // 2 - 230, 460
    d.rounded_rectangle((tx0 + 10, 40 + 14, tx0 + tw + 10, H + 80 + 14), radius=70, fill=(0, 0, 0, 120))
    d.rounded_rectangle((tx0, 40, tx0 + tw, H + 80), radius=70, fill=(70, 74, 82), outline=(160, 165, 175), width=4)
    d.rounded_rectangle((tx0 + 24, 70, tx0 + tw - 24, H + 80), radius=50, fill=(28, 30, 36))
    d.rounded_rectangle((W // 2 - 40, 88, W // 2 + 40, 96), radius=4, fill=(60, 62, 70))         # динамик
    d.text((W // 2, 118), 'ГЛАВПРЫГ', font=F(DEJAVU, 16), fill=(170, 175, 185), anchor='mm')
    ex, ey = W // 2 - ekr.size[0] // 2, 140
    d.rectangle((ex - 6, ey - 6, ex + ekr.size[0] + 6, ey + ekr.size[1] + 6), fill=(8, 8, 10))
    im.paste(ekr, (ex, ey))
    # стекло: косой блик
    blik = Image.new('RGBA', ekr.size, (0, 0, 0, 0))
    ImageDraw.Draw(blik).polygon([(0, 0), (ekr.size[0] * 0.55, 0), (0, ekr.size[1] * 0.5)], fill=(255, 255, 255, 14))
    im.paste(Image.alpha_composite(im.crop((ex, ey, ex + ekr.size[0], ey + ekr.size[1])).convert('RGBA'), blik), (ex, ey))
    d = ImageDraw.Draw(im, 'RGBA')
    jy = ey + ekr.size[1] + 70
    d.rounded_rectangle((W // 2 - 190, jy - 30, W // 2 - 90, jy + 10), radius=14, fill=(90, 94, 104))
    d.rounded_rectangle((W // 2 + 90, jy - 30, W // 2 + 190, jy + 10), radius=14, fill=(90, 94, 104))
    d.ellipse((W // 2 - 44, jy - 44, W // 2 + 44, jy + 44), fill=(120, 126, 138), outline=(190, 195, 205), width=3)
    d.ellipse((W // 2 - 18, jy - 18, W // 2 + 18, jy + 18), fill=(70, 74, 82))
    # подпись сбоку — как на коробке игры
    d.text((90, 330), 'Точно\nв круг', font=oswald(64), fill=(255, 140, 40), spacing=-14, stroke_width=3, stroke_fill=(0, 0, 0))
    d.text((92, 500), 'Java-игра\nдля телефона\n176×208', font=F(DEJAVU, 20), fill=(170, 175, 190), spacing=8)
    im.save(f'{kuda}/stil-java.png')


sa(); xp(); java()
print('готово:', kuda)
