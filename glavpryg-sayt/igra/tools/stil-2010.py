#!/usr/bin/env python3
"""Три стиля главного вида игры с отсылкой к 2010-м — по настоящему кадру.

    python stil-2010.py <кадр.png> <nadpisi.json> <каталог шрифтов> <каталог>

Кадр — холст игры без надписей (576×360), nadpisi.json — подписи игры (текст и точка).
В каталоге шрифтов: Oswald[wght].ttf, Nunito.ttf, RussoOne-Regular.ttf (Google Fonts, OFL).
Выход: stil-br.png («Королевская битва»), stil-geo.png (игра по карте с телефона),
stil-kazual.png (мобильная казуалка), 1280×800.
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
K = W / 576
IGROK, KRUG = (288, 360 * 0.58), (300, 65)


def shrift(imya, r, ves=None):
    f = ImageFont.truetype(f'{shrifty}/{imya}', r)
    if ves: f.set_variation_by_axes([ves])
    return f


def klassy(im):
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


def perekrasit(cveta):
    out = np.asarray(KADR).copy()
    for imya, hexc in cveta.items():
        out[KL == imya] = [int(hexc[i:i + 2], 16) for i in (0, 2, 4)]
    return Image.fromarray(out)


def nalozhit(im, cvet, maska, razmyt=0):
    """Цвет по маске (L) — смешивается с картинкой."""
    if razmyt: maska = maska.filter(ImageFilter.GaussianBlur(razmyt))
    return Image.composite(Image.new('RGB', im.size, cvet), im, maska)


def panel(d, box, r, cvet, verh=None, obvod=None, w=0):
    """Объёмная плашка: основной цвет, сверху светлее (как кнопки мобильных игр)."""
    d.rounded_rectangle(box, radius=r, fill=cvet, outline=obvod, width=w)
    if verh:
        x0, y0, x1, y1 = box
        d.rounded_rectangle((x0 + w + 2, y0 + w + 2, x1 - w - 2, y0 + (y1 - y0) * 0.5), radius=max(1, r - 3), fill=verh)


def zvezda(d, cx, cy, r, cvet, obvod=None, w=1):
    t = [(cx + r * math.cos(math.radians(-90 + j * 36)) * (1 if j % 2 == 0 else 0.48),
          cy + r * math.sin(math.radians(-90 + j * 36)) * (1 if j % 2 == 0 else 0.48)) for j in range(10)]
    d.polygon(t, fill=cvet, outline=obvod, width=w)


# ───────── 1. «Королевская битва»: зона, компас, мини-карта, шкала высоты ─────────
def br():
    im = perekrasit({'pole_t': '78bf45', 'pole_s': '8ccf55', 'trava': 'a8e067', 'les': '2d8a3c', 'svet': 'f4f1e8',
                     'voda': '38b0ff', 'zhyoltyy': 'ffe24a'})
    im = ImageEnhance.Contrast(im.resize((W, H), Image.Resampling.LANCZOS)).enhance(1.08)
    # зона: всё вне безопасного круга — в сиреневой «буре», по краю — яркое кольцо
    kx, ky, rz = KRUG[0] * K, KRUG[1] * K + 30, 420
    m = Image.new('L', (W, H), 150); ImageDraw.Draw(m).ellipse((kx - rz, ky - rz, kx + rz, ky + rz), fill=0)
    im = nalozhit(im, (130, 40, 230), m, 3)
    d = ImageDraw.Draw(im, 'RGBA')
    d.ellipse((kx - rz, ky - rz, kx + rz, ky + rz), outline=(255, 255, 255), width=5)
    d.ellipse((kx - 110, ky - 140, kx + 110, ky + 80), outline=(255, 255, 255, 200), width=3)   # следующая зона — круг
    for n in NADPISI:
        d.text((n['x'] * K, n['y'] * K - 6), n['t'], font=shrift('Oswald[wght].ttf', 28, 700), fill=(255, 255, 255),
               anchor='ms', stroke_width=2, stroke_fill=(30, 20, 60))
    f, fm = shrift('Oswald[wght].ttf', 24, 600), shrift('Oswald[wght].ttf', 18, 500)
    # компас — лента сверху по центру, курс 20°
    d.rectangle((390, 14, 890, 52), fill=(0, 0, 0, 90))
    for gr in range(-60, 61, 5):
        x = 640 + gr * 4; a = (20 + gr) % 360
        if a % 15 == 0:
            podp = {0: 'С', 45: 'СВ', 90: 'В', 135: 'ЮВ', 180: 'Ю', 225: 'ЮЗ', 270: 'З', 315: 'СЗ'}.get(a, str(a))
            d.text((x, 30), podp, font=fm if len(podp) > 2 else f, fill=(255, 255, 255) if a % 45 else (255, 220, 60), anchor='mm')
        else:
            d.line((x, 44, x, 50), fill=(255, 255, 255, 180), width=2)
    d.polygon([(640, 56), (632, 68), (648, 68)], fill=(255, 255, 255))
    d.text((640, 84), '20', font=fm, fill=(255, 255, 255), anchor='mm')
    # мини-карта справа сверху: зона, маршрут самолёта, игрок
    mm, mx, my = 230, W - 250, 20
    karta = im.resize((round(W * 0.3), round(H * 0.3)), Image.Resampling.LANCZOS)
    plit = Image.new('RGB', (mm, mm), (120, 180, 80))
    plit.paste(karta, (round(mm / 2 - IGROK[0] * K * 0.3), round(mm / 2 - IGROK[1] * K * 0.3)))
    im.paste(plit, (mx, my))
    d = ImageDraw.Draw(im, 'RGBA')
    d.rectangle((mx, my, mx + mm, my + mm), outline=(255, 255, 255, 220), width=3)
    for i in range(1, 4):
        d.line((mx + i * mm / 4, my, mx + i * mm / 4, my + mm), fill=(255, 255, 255, 60))
        d.line((mx, my + i * mm / 4, mx + mm, my + i * mm / 4), fill=(255, 255, 255, 60))
    d.line((mx + 10, my + mm - 30, mx + mm - 10, my + 20), fill=(255, 255, 255), width=3)          # маршрут самолёта
    d.polygon([(mx + mm - 10, my + 20), (mx + mm - 28, my + 24), (mx + mm - 18, my + 36)], fill=(255, 255, 255))
    pcx, pcy = mx + mm / 2, my + mm / 2
    d.polygon([(pcx, pcy - 10), (pcx - 8, pcy + 8), (pcx + 8, pcy + 8)], fill=(255, 210, 40), outline=(0, 0, 0))
    # слева сверху: сколько осталось, бура сжимается
    for i, (znak, tekst_) in enumerate((('👤', '1'), ('⏱', '0:42'))):
        x = 24 + i * 120
        d.rounded_rectangle((x, 20, x + 106, 58), radius=6, fill=(0, 0, 0, 120))
        if i == 0:
            d.ellipse((x + 12, 27, x + 26, 41), fill=(255, 255, 255)); d.pieslice((x + 8, 38, x + 30, 60), 180, 360, fill=(255, 255, 255))
        else:
            d.ellipse((x + 10, 27, x + 30, 47), outline=(190, 140, 255), width=3)
        d.text((x + 70, 39), tekst_, font=f, fill=(255, 255, 255), anchor='mm')
    d.text((24, 70), 'ЗОНА СУЖАЕТСЯ', font=fm, fill=(210, 180, 255), stroke_width=1, stroke_fill=(0, 0, 0, 160))
    # справа: шкала высоты, как при высадке
    sx, sy0, sy1 = W - 70, 300, 640
    d.rounded_rectangle((sx - 8, sy0, sx + 8, sy1), radius=8, fill=(0, 0, 0, 110))
    vy = sy1 - (sy1 - sy0) * 380 / 1000
    d.rounded_rectangle((sx - 6, vy, sx + 6, sy1 - 2), radius=6, fill=(255, 210, 40))
    d.polygon([(sx - 16, vy), (sx - 30, vy - 10), (sx - 30, vy + 10)], fill=(255, 255, 255))
    d.text((sx - 38, vy), '380', font=shrift('Oswald[wght].ttf', 34, 700), fill=(255, 255, 255), anchor='rm',
           stroke_width=2, stroke_fill=(0, 0, 0))
    d.text((sx, sy1 + 24), 'м', font=fm, fill=(255, 255, 255), anchor='mm')
    # снизу слева: щит и здоровье; по центру — клавиша действия
    for i, cv in enumerate(((60, 160, 255), (90, 220, 90))):          # щит и здоровье — полные
        y = 700 + i * 30
        d.rectangle((24, y, 384, y + 20), fill=(0, 0, 0, 120))
        d.rectangle((26, y + 2, 382, y + 18), fill=cv)
        d.text((394, y + 10), '100', font=fm, fill=(255, 255, 255), anchor='lm')
    d.rounded_rectangle((500, 720, 620, 756), radius=6, fill=(255, 255, 255), outline=(0, 0, 0), width=2)
    d.text((560, 738), 'ПРОБЕЛ', font=fm, fill=(0, 0, 0), anchor='mm')
    d.text((634, 738), 'ПОДУШКА', font=f, fill=(255, 255, 255), anchor='lm', stroke_width=2, stroke_fill=(0, 0, 0))
    im.save(f'{kuda}/stil-br.png')


# ───────── 2. Игра по карте с телефона: плоская карта в наклоне, маячок, круглая кнопка ─────────
def perspektiva_koef(ot, k):
    """Коэффициенты PERSPECTIVE для Image.transform: 4 точки результата → 4 точки исходника."""
    A, B = [], []
    for (x, y), (u, v) in zip(k, ot):
        A += [[x, y, 1, 0, 0, 0, -u * x, -u * y], [0, 0, 0, x, y, 1, -v * x, -v * y]]
        B += [u, v]
    return np.linalg.solve(np.array(A, float), np.array(B, float)).tolist()


def tochka(koef_obr, x, y):
    """Куда в наклонённой картинке попала точка исходника (обратное преобразование)."""
    a, b, c, d_, e, f, g, h = koef_obr
    z = g * x + h * y + 1
    return (a * x + b * y + c) / z, (d_ * x + e * y + f) / z


def geo():
    # плоская карта без «шума»: крупные пятна, мятная земля, яркие парки, белые дороги
    plosk = perekrasit({'pole_t': 'a9e3a0', 'pole_s': 'b5eaa9', 'trava': '7fd877', 'les': '5cc566', 'svet': 'ffffff',
                        'voda': '5cc8f5', 'goluboy': 'b5eaa9', 'zhyoltyy': 'b5eaa9', 'kupol': 'b5eaa9', 'chyornyy': 'b5eaa9'})
    plosk = plosk.resize((1152, 720), Image.Resampling.NEAREST).filter(ImageFilter.ModeFilter(9))
    plosk = plosk.filter(ImageFilter.SMOOTH_MORE)
    sw, sh = plosk.size
    # наклон: верх карты уходит вдаль
    rez = [(-520, 150), (W + 520, 150), (W + 120, H + 420), (-120, H + 420)]   # игрок — выше кнопки
    ish = [(0, 0), (sw, 0), (sw, sh), (0, sh)]
    koef = perspektiva_koef(ish, rez)
    obr = perspektiva_koef(rez, ish)
    im = plosk.transform((W, H), Image.Transform.PERSPECTIVE, koef, Image.Resampling.BICUBIC, fillcolor=(181, 234, 169))
    # небо и дымка у горизонта
    nebo = Image.linear_gradient('L').resize((W, 260))
    im = nalozhit(im, (255, 255, 255), Image.new('L', (W, H), 0).crop((0, 0, W, H)), 0)
    m = Image.new('L', (W, H), 0); m.paste(nebo.point(lambda v: 255 - v * 0.9), (0, 0))
    im = nalozhit(im, (190, 230, 255), m)
    m = Image.new('L', (W, H), 0); ImageDraw.Draw(m).rectangle((0, 0, W, 150), fill=255)
    im = nalozhit(im, (150, 205, 250), m, 30)
    s = sw / 576
    d = ImageDraw.Draw(im, 'RGBA')
    # маячок на круге: пятно на земле, столб, оранжевая «шляпка»
    kx, ky = tochka(obr, KRUG[0] * s, KRUG[1] * s)
    for r, a in ((70, 60), (48, 90)):
        d.ellipse((kx - r, ky - r * 0.4, kx + r, ky + r * 0.4), fill=(255, 140, 40, a))
    d.rectangle((kx - 5, ky - 110, kx + 5, ky), fill=(70, 90, 130))
    d.ellipse((kx - 30, ky - 140, kx + 30, ky - 100), fill=(255, 130, 30), outline=(255, 255, 255), width=4)
    d.rounded_rectangle((kx - 44, ky - 186, kx + 44, ky - 154), radius=16, fill=(255, 255, 255, 230))
    d.text((kx, ky - 170), 'Круг', font=shrift('Nunito.ttf', 20, 800), fill=(60, 80, 120), anchor='mm')
    # точки захода — голубые кубики-«остановки»
    for n in NADPISI:
        px, py = tochka(obr, n['x'] * s, (n['y'] + 14) * s)
        if not (0 < px < W and 150 < py < H): continue
        d.ellipse((px - 26, py - 8, px + 26, py + 8), fill=(40, 140, 220, 90))
        d.polygon([(px, py - 52), (px + 18, py - 42), (px, py - 32), (px - 18, py - 42)], fill=(140, 220, 255))
        d.polygon([(px - 18, py - 42), (px, py - 32), (px, py - 12), (px - 18, py - 22)], fill=(40, 150, 230))
        d.polygon([(px + 18, py - 42), (px, py - 32), (px, py - 12), (px + 18, py - 22)], fill=(20, 110, 200))
        d.text((px, py - 66), n['t'].split(' · ')[0], font=shrift('Nunito.ttf', 20, 900), fill=(255, 255, 255), anchor='mm',
               stroke_width=3, stroke_fill=(30, 90, 170))
    # игрок: кольца на земле, тень, купол над головой
    gx, gy = tochka(obr, IGROK[0] * s, IGROK[1] * s)
    for r, a in ((120, 40), (85, 70), (50, 110)):
        d.ellipse((gx - r, gy - r * 0.38, gx + r, gy + r * 0.38), outline=(80, 200, 255, a), width=4)
    d.ellipse((gx - 30, gy - 9, gx + 30, gy + 9), fill=(0, 60, 0, 70))
    cy = gy - 190
    d.chord((gx - 90, cy - 40, gx + 90, cy + 60), 180, 360, fill=(255, 128, 30), outline=(200, 80, 10), width=3)
    for i in range(1, 6):
        x = gx - 90 + i * 30
        d.line((x, cy + 10, x, cy - 30 + abs(i - 3) * 8), fill=(220, 95, 15), width=3)
    for x in (gx - 86, gx - 40, gx + 40, gx + 86):
        d.line((x, cy + 10, gx, cy + 120), fill=(255, 255, 255, 220), width=2)
    d.ellipse((gx - 12, cy + 108, gx + 12, cy + 132), fill=(255, 220, 190))
    d.rounded_rectangle((gx - 14, cy + 130, gx + 14, cy + 172), radius=10, fill=(40, 70, 160))
    # интерфейс: аватар с уровнем, круглая кнопка, компас и погода, «рядом»
    fb, fn = shrift('Nunito.ttf', 24, 800), shrift('Nunito.ttf', 18, 700)
    d.ellipse((24, H - 120, 120, H - 24), fill=(255, 255, 255), outline=(255, 160, 60), width=5)
    d.ellipse((56, H - 104, 88, H - 72), fill=(255, 210, 180)); d.pieslice((44, H - 72, 100, H - 30), 180, 360, fill=(40, 70, 160))
    d.ellipse((96, H - 54, 130, H - 20), fill=(255, 140, 40), outline=(255, 255, 255), width=3)
    d.text((113, H - 37), '1', font=fn, fill=(255, 255, 255), anchor='mm')
    d.text((140, H - 80), 'Новичок', font=fb, fill=(255, 255, 255), stroke_width=3, stroke_fill=(40, 90, 150))
    d.rounded_rectangle((140, H - 46, 300, H - 34), radius=6, fill=(255, 255, 255, 180))
    d.rounded_rectangle((140, H - 46, 210, H - 34), radius=6, fill=(255, 150, 40))
    bx, by = W // 2, H - 70
    # главная кнопка — оранжевая, с куполом (своя, не чужой «шарик»)
    d.ellipse((bx - 50, by - 50, bx + 50, by + 50), fill=(255, 130, 30), outline=(255, 255, 255), width=6)
    d.chord((bx - 30, by - 30, bx + 30, by + 14), 180, 360, fill=(255, 255, 255))
    for x in (bx - 28, bx, bx + 28):
        d.line((x, by - 8, bx, by + 22), fill=(255, 255, 255), width=3)
    d.ellipse((bx - 6, by + 18, bx + 6, by + 30), fill=(255, 255, 255))
    d.rounded_rectangle((W - 330, H - 100, W - 24, H - 32), radius=34, fill=(255, 255, 255, 235))
    d.text((W - 300, H - 66), 'Рядом:', font=fn, fill=(90, 100, 120), anchor='lm')
    for i, t in enumerate(('I', 'II', 'III')):
        x = W - 190 + i * 52
        d.ellipse((x - 20, H - 86, x + 20, H - 46), fill=(60, 160, 235))
        d.text((x, H - 66), t, font=fn, fill=(255, 255, 255), anchor='mm')
    for i, (x, znak) in enumerate(((W - 70, 'С'), (W - 70, '☀'))):
        y = 40 + i * 76
        d.ellipse((x - 30, y - 30 + 20, x + 30, y + 30 + 20), fill=(255, 255, 255, 235))
        if i == 0:
            d.polygon([(x, y - 2), (x - 10, y + 26), (x, y + 20), (x + 10, y + 26)], fill=(230, 60, 50))
            d.text((x, y + 38), 'С', font=shrift('Nunito.ttf', 14, 800), fill=(90, 100, 120), anchor='mm')
        else:
            d.ellipse((x - 12, y + 8, x + 12, y + 32), fill=(255, 190, 40))
            for j in range(8):
                a = math.radians(j * 45)
                d.line((x + math.cos(a) * 16, y + 20 + math.sin(a) * 16, x + math.cos(a) * 22, y + 20 + math.sin(a) * 22),
                       fill=(255, 190, 40), width=3)
    d.rounded_rectangle((24, 24, 250, 70), radius=23, fill=(255, 255, 255, 230))
    d.text((44, 47), '380 м · штиль', font=fb, fill=(60, 80, 120), anchor='lm')
    im.save(f'{kuda}/stil-geo.png')


# ───────── 3. Мобильная казуалка: мультяшный контур, монеты, кристаллы, три звезды ─────────
def kazual():
    w, h = 640, 400
    im = perekrasit({'pole_t': '7ccf3f', 'pole_s': '90dc4c', 'trava': 'b6ec5c', 'les': '2f9a3a', 'svet': 'fff3d6',
                     'voda': '3cc0ff', 'goluboy': '40d0ff', 'zhyoltyy': 'ffd84a'})
    im = im.resize((w, h), Image.Resampling.NEAREST).filter(ImageFilter.ModeFilter(5))
    # толстый тёмный контур по границам пятен
    kontur = im.convert('L').filter(ImageFilter.FIND_EDGES).point(lambda v: 255 if v > 18 else 0).filter(ImageFilter.MaxFilter(3))
    im.paste((40, 70, 30), (0, 0), kontur)
    im = im.resize((W, H), Image.Resampling.LANCZOS)
    # мягкий объём: светлее сверху, темнее по краям
    m = Image.linear_gradient('L').rotate(180).resize((W, H)).point(lambda v: v * 0.25)
    im = nalozhit(im, (255, 255, 230), m)
    d = ImageDraw.Draw(im, 'RGBA')
    R = 'RussoOne-Regular.ttf'
    # монета-бонус над кругом
    kx, ky = KRUG[0] * K, KRUG[1] * K + 40
    d.ellipse((kx - 40, ky - 40, kx + 40, ky + 40), fill=(255, 200, 30), outline=(170, 100, 0), width=6)
    d.ellipse((kx - 24, ky - 24, kx + 24, ky + 24), outline=(255, 235, 130), width=4)
    d.text((kx + 50, ky - 30), '+50', font=shrift(R, 40), fill=(255, 230, 60), stroke_width=4, stroke_fill=(120, 60, 0))
    for n in [n for n in NADPISI if not (n['x'] * K < 360 and n['y'] * K < 270)]:   # под табло не подписываем
        d.text((n['x'] * K, n['y'] * K - 6), n['t'], font=shrift(R, 26), fill=(255, 255, 255), anchor='ms',
               stroke_width=4, stroke_fill=(30, 60, 110))
    # верх: значок уровня с полоской опыта, монеты, кристаллы, пауза
    d.regular_polygon((70, 66, 46), 6, rotation=30, fill=(60, 120, 230), outline=(20, 40, 110), width=5)
    d.text((70, 66), '1', font=shrift(R, 40), fill=(255, 255, 255), anchor='mm', stroke_width=3, stroke_fill=(20, 40, 110))
    panel(d, (120, 44, 330, 88), 14, (20, 30, 60, 200), None, (255, 255, 255, 120), 2)
    d.rounded_rectangle((124, 70, 230, 84), radius=7, fill=(120, 230, 90))
    d.text((134, 56), 'Круг', font=shrift(R, 22), fill=(255, 255, 255), anchor='lm', stroke_width=2, stroke_fill=(0, 0, 0))
    for i, (cvet, chislo) in enumerate((((255, 200, 30), '1 250'), ((80, 230, 120), '45'))):
        x = 470 + i * 270
        panel(d, (x, 40, x + 220, 92), 16, (20, 30, 60, 200), None, (255, 255, 255, 120), 2)
        if i == 0:
            d.ellipse((x - 22, 34, x + 42, 98), fill=cvet, outline=(170, 100, 0), width=5)
        else:
            d.polygon([(x + 10, 34), (x + 42, 56), (x + 10, 98), (x - 22, 56)], fill=cvet, outline=(20, 110, 50), width=4)
        d.text((x + 120, 66), chislo, font=shrift(R, 30), fill=(255, 255, 255), anchor='mm', stroke_width=3, stroke_fill=(0, 0, 0))
        panel(d, (x + 180, 46, x + 214, 86), 10, (90, 200, 60), (160, 240, 120), (30, 90, 20), 3)
        d.text((x + 197, 66), '+', font=shrift(R, 30), fill=(255, 255, 255), anchor='mm', stroke_width=2, stroke_fill=(30, 90, 20))
    panel(d, (W - 92, 34, W - 28, 98), 18, (255, 170, 40), (255, 215, 120), (150, 80, 0), 4)
    d.rectangle((W - 70, 52, W - 63, 80), fill=(255, 255, 255)); d.rectangle((W - 57, 52, W - 50, 80), fill=(255, 255, 255))
    # цель уровня — три звезды
    panel(d, (24, 130, 210, 250), 18, (20, 30, 60, 190), None, (255, 255, 255, 110), 2)
    for i, (podp, n) in enumerate((('25', 1), ('50', 2), ('100', 3))):
        y = 152 + i * 34
        for j in range(n):
            zvezda(d, 46 + j * 26, y, 12, (255, 210, 40), (150, 90, 0), 2)
        d.text((190, y), podp, font=shrift(R, 22), fill=(255, 255, 255), anchor='rm')
    # низ: режимы купола и большая кнопка действия
    for i, (t, akt) in enumerate((('ПОЛНЫЙ', True), ('СРЕДНИЙ', False))):
        x = 40 + i * 200
        panel(d, (x, H - 96, x + 180, H - 36), 20, (255, 140, 30) if akt else (110, 120, 140),
              (255, 190, 100) if akt else (160, 170, 185), (120, 60, 0) if akt else (50, 55, 70), 4)
        d.text((x + 90, H - 66), t, font=shrift(R, 24), fill=(255, 255, 255), anchor='mm', stroke_width=2,
               stroke_fill=(90, 40, 0) if akt else (40, 45, 60))
    panel(d, (W - 330, H - 120, W - 40, H - 30), 28, (90, 200, 50), (160, 240, 110), (30, 90, 10), 5)
    d.text((W - 185, H - 75), 'ПОДУШКА!', font=shrift(R, 40), fill=(255, 255, 255), anchor='mm', stroke_width=4,
           stroke_fill=(30, 90, 10))
    im.save(f'{kuda}/stil-kazual.png')


br(); geo(); kazual()
print('готово:', kuda)
