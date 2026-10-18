#!/usr/bin/env python3
"""Три стилевые альтернативы главного вида игры — по настоящему кадру.

    python stil-varianty.py <кадр.png> <nadpisi.json> <шрифт PressStart2P.ttf> <каталог>

Кадр — холст игры без надписей (576×360), nadpisi.json — где игра пишет подписи
(текст и точка на холсте). Выход: stil-dendi.png, stil-sega.png, stil-geymboy.png, 1280×800.
"""
import json
import sys
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageEnhance

kadr_put, nadpisi_put, shrift_put, kuda = sys.argv[1:5]
KADR = Image.open(kadr_put).convert('RGB')
# проценты зон в круге на малом разрешении слипаются — оставляем подписи точек захода
NADPISI = [n for n in json.load(open(nadpisi_put)) if 0 <= n['x'] <= 576 and 0 <= n['y'] <= 360 and '%' not in n['t']]


def klassy(im):
    """Что на кадре: поле (тёмное и светлое), трава, лес, вода, светлое (дороги, дома, линии),
    купол (оранжевый), точки захода (голубые), жёлтая линия. Цвета приставки назначаются по классам."""
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
    """Кадр в цветах приставки: каждому классу — свой цвет."""
    out = np.zeros(KL.shape + (3,), dtype=np.uint8)
    for imya, hexc in cveta.items():
        out[KL == imya] = [int(hexc[i:i + 2], 16) for i in (0, 2, 4)]
    return Image.fromarray(out)
W, H = 1280, 800


def shrift(r=8):
    return ImageFont.truetype(shrift_put, r)


def palitra(hexy):
    return [tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) for h in hexy]


def k_palitre(im, cveta, dither=False):
    """Каждую точку — к ближайшему цвету набора (без смешения, как на приставке)."""
    p = Image.new('P', (1, 1))
    plosk = [c for rgb in cveta for c in rgb]
    p.putpalette(plosk + plosk[:3] * (256 - len(cveta)))
    return im.quantize(palette=p, dither=Image.Dither.FLOYDSTEINBERG if dither else Image.Dither.NONE).convert('RGB')


def tekst(d, xy, t, cvet, ten=None, f=None, anchor='la'):
    f = f or shrift()
    if ten:
        x, y = xy
        for dx, dy in ((1, 1), (1, 0), (0, 1), (-1, 0), (0, -1)):
            d.text((x + dx, y + dy), t, font=f, fill=ten, anchor=anchor)
    d.text(xy, t, font=f, fill=cvet, anchor=anchor)


def podpisi(im, masht, cvet, ten, f, verh=0):
    """Подписи карты — пиксельным шрифтом в разрешении приставки."""
    d = ImageDraw.Draw(im)
    for n in [n for n in NADPISI if n['y'] * masht > verh]:   # под табло не подписываем
        t = n['t'].replace(' · ', '·').upper()
        tekst(d, (round(n['x'] * masht), round(n['y'] * masht) - 2), t, cvet, ten, f, anchor='ms')


# ───────── 1. «Денди»: 8 бит, палитра NES, телевизор с кинескопом ─────────
def dendi():
    NES = palitra(['000000', '7c7c7c', 'bcbcbc', 'fcfcfc', '0058f8', '3cbcfc', 'a4e4fc',
                   '00a800', '58d854', 'b8f818', '005800', '007800', 'ac7c00', 'f8b800',
                   'fca044', 'e45c10', 'f83800', '503000', '881400', 'f0d0b0', 'f8d878', 'd8f878'])
    w, h = 256, 160
    im = perekrasit({'pole_t': '00a800', 'pole_s': '58d854', 'trava': 'b8f818', 'les': '005800', 'svet': 'fcfcfc',
                     'voda': '0058f8', 'goluboy': '3cbcfc', 'zhyoltyy': 'f8b800', 'kupol': 'e45c10', 'chyornyy': '000000'})
    im = k_palitre(im.resize((w, h), Image.Resampling.BOX), NES)
    podpisi(im, w / 576, (252, 252, 252), (0, 0, 0), shrift(8))
    d = ImageDraw.Draw(im)
    # строка состояния как у «Марио»: чёрная плашка, белые буквы
    d.rectangle((0, 0, w, 21), fill=(0, 0, 0))
    tekst(d, (8, 3), 'ВЫСОТА', (252, 252, 252)); tekst(d, (8, 12), '  380М', (248, 184, 0))
    tekst(d, (96, 3), 'ОЧКИ', (252, 252, 252)); tekst(d, (96, 12), '000100', (252, 252, 252))
    tekst(d, (176, 3), 'МИР', (252, 252, 252)); tekst(d, (176, 12), ' 1-1', (252, 252, 252))
    # режим купола — стрелочкой, как выбор пункта в меню
    d.rectangle((0, h - 14, w, h), fill=(0, 0, 0))
    tekst(d, (8, h - 11), '▶ПОЛНЫЙ  СРЕДНИЙ  ПОДУШКА', (252, 252, 252))
    im = im.resize((w * 5, h * 5), Image.Resampling.NEAREST)
    # кинескоп: строки развёртки, лёгкое свечение, тёмные углы
    svet = im.filter(ImageFilter.GaussianBlur(3))
    im = Image.blend(im, svet, 0.18)
    stroki = Image.new('L', im.size, 255)
    ds = ImageDraw.Draw(stroki)
    for y in range(0, im.size[1], 5):
        ds.line((0, y + 4, im.size[0], y + 4), fill=150)
    im = Image.composite(im, Image.new('RGB', im.size, (0, 0, 0)), stroki)
    vin = Image.new('L', im.size, 0)
    ImageDraw.Draw(vin).rounded_rectangle((-60, -60, im.size[0] + 60, im.size[1] + 60), radius=260, fill=255)
    vin = vin.filter(ImageFilter.GaussianBlur(70))
    im = Image.composite(im, Image.new('RGB', im.size, (0, 0, 0)), vin)
    maska = Image.new('L', im.size, 0)
    ImageDraw.Draw(maska).rounded_rectangle((0, 0, *im.size), radius=48, fill=255)
    fon = Image.new('RGB', im.size, (18, 18, 20))
    fon.paste(im, (0, 0), maska)
    fon.save(f'{kuda}/stil-dendi.png')


# ───────── 2. «Сега»: 16 бит, сочные цвета, контур, табло как у «Соника» ─────────
def sega():
    w, h = 320, 200
    cv = {'pole_t': '24a03c', 'pole_s': '48c048', 'trava': '90d848', 'les': '186c24', 'svet': 'fcf0d8',
          'voda': '2448d8', 'goluboy': '48d8fc', 'zhyoltyy': 'fcd800', 'kupol': 'fc6c00', 'chyornyy': '181430'}
    im = perekrasit(cv).resize((w, h), Image.Resampling.BOX)
    im = k_palitre(im, palitra(list(cv.values()) + ['ffffff', '6c9030']))   # 9-битный цвет Mega Drive — набор из дюжины
    # тёмный контур по резким перепадам — так рисовали спрайты и края полей
    kontur = im.convert('L').filter(ImageFilter.FIND_EDGES).point(lambda v: 255 if v > 70 else 0)
    im.paste((24, 20, 48), (0, 0), kontur)
    podpisi(im, w / 576, (255, 255, 255), (24, 20, 48), shrift(8), verh=50)
    d = ImageDraw.Draw(im)
    zh, bel, ten = (255, 216, 0), (255, 255, 255), (24, 20, 48)
    for y, (podp, zn) in zip((8, 20, 32), (('ВЫСОТА', '380'), ('ВРЕМЯ', '0:42'), ('ОЧКИ', '100'))):
        tekst(d, (8, y), podp, zh, ten); tekst(d, (68, y), zn, bel, ten)
    # «жизни» внизу слева — запасной парашют
    d.rounded_rectangle((6, h - 22, 70, h - 6), radius=3, fill=(0, 40, 140), outline=ten)
    d.rectangle((10, h - 18, 22, h - 13), fill=(255, 120, 20), outline=ten)
    tekst(d, (26, h - 18), '×2', bel, ten)
    # режим — плашкой справа внизу
    d.rounded_rectangle((w - 92, h - 22, w - 6, h - 6), radius=3, fill=(220, 40, 30), outline=ten)
    tekst(d, (w - 49, h - 14), 'ПОЛНЫЙ', bel, ten, anchor='mm')
    im.resize((w * 4, h * 4), Image.Resampling.NEAREST).save(f'{kuda}/stil-sega.png')


# ───────── 3. «Гейм бой»: четыре оттенка зелёного, карманная приставка ─────────
def geymboy():
    GB = palitra(['0f380f', '306230', '8bac0f', '9bbc0f'])
    w, h = 160, 100
    # поле светлое, лес и купол тёмные — на четырёх оттенках главное должно читаться
    im = perekrasit({'pole_t': '8bac0f', 'pole_s': '8bac0f', 'trava': '9bbc0f', 'les': '0f380f', 'svet': '306230',
                     'voda': '306230', 'goluboy': '0f380f', 'zhyoltyy': '306230', 'kupol': '0f380f', 'chyornyy': '0f380f'})
    # приближение в 1,3 раза вокруг парашютиста, круг остаётся в кадре: на карманной приставке спрайты крупные
    im = im.crop((64, 40, 512, 320))
    im = k_palitre(im.resize((w, h), Image.Resampling.BOX), GB)
    d = ImageDraw.Draw(im)
    d.rectangle((0, h - 11, w, h), fill=GB[0])
    tekst(d, (3, h - 9), '380М', GB[3]); tekst(d, (w - 3, h - 9), '♥♥', GB[2], anchor='ra')
    tekst(d, (44, h - 9), 'ПОЛНЫЙ', GB[2])
    k = 5
    ekran = im.resize((w * k, h * k), Image.Resampling.NEAREST)
    # сетка жидкокристаллического экрана и лёгкий «шлейф» точек
    setka = Image.new('L', ekran.size, 255)
    ds = ImageDraw.Draw(setka)
    for i in range(0, ekran.size[0], k): ds.line((i, 0, i, ekran.size[1]), fill=215)
    for i in range(0, ekran.size[1], k): ds.line((0, i, ekran.size[0], i), fill=215)
    ekran = Image.composite(ekran, Image.new('RGB', ekran.size, (155, 188, 15)), setka)
    shleyf = ekran.copy().filter(ImageFilter.GaussianBlur(1.2))
    ekran = Image.blend(ekran, shleyf, 0.25)
    # корпус: светло-серый, тёмная рамка экрана, крестовина и кнопки A и B
    korp = Image.new('RGB', (W, H), (40, 40, 44))
    d = ImageDraw.Draw(korp)
    d.rounded_rectangle((20, 40, W - 20, H - 40), radius=90, fill=(198, 196, 190), outline=(150, 148, 142), width=4)
    ex, ey = (W - ekran.size[0]) // 2, 110
    d.rounded_rectangle((ex - 50, ey - 46, ex + ekran.size[0] + 50, ey + ekran.size[1] + 40), radius=26, fill=(84, 84, 96))
    d.ellipse((ex - 34, ey + 150, ex - 22, ey + 162), fill=(220, 30, 40))
    f = ImageFont.truetype(shrift_put, 12)
    d.text((ex - 28, ey + 172), 'ВКЛ', font=f, fill=(190, 190, 200), anchor='ma')
    d.text((ex, ey - 30), 'ТОЧЕЧНАЯ МАТРИЦА · ГЛАВПРЫГ', font=f, fill=(190, 190, 200))
    korp.paste(ekran, (ex, ey))
    # крестовина слева, кнопки справа
    cx, cy = 125, ey + ekran.size[1] // 2
    d.rounded_rectangle((cx - 52, cy - 16, cx + 52, cy + 16), radius=5, fill=(30, 30, 34))
    d.rounded_rectangle((cx - 16, cy - 52, cx + 16, cy + 52), radius=5, fill=(30, 30, 34))
    bx, by = W - 125, cy
    for dx, dy, bukva in ((22, -22, 'A'), (-22, 22, 'B')):
        d.ellipse((bx + dx - 26, by + dy - 26, bx + dx + 26, by + dy + 26), fill=(150, 20, 70))
        d.text((bx + dx, by + dy + 40), bukva, font=f, fill=(60, 50, 120), anchor='ma')
    tsentr = ImageFont.truetype(shrift_put, 16)
    d.text((W // 2, H - 92), 'ТОЧНО В КРУГ', font=tsentr, fill=(60, 50, 120), anchor='ma')
    for i, t in enumerate(('ВЫБОР', 'СТАРТ')):
        x = W // 2 - 70 + i * 140
        d.rounded_rectangle((x - 30, H - 132, x + 30, H - 120), radius=6, fill=(110, 110, 116))
        d.text((x, H - 112), t, font=f, fill=(60, 50, 120), anchor='ma')
    korp.save(f'{kuda}/stil-geymboy.png')


dendi(); sega(); geymboy()
print('готово:', kuda)
