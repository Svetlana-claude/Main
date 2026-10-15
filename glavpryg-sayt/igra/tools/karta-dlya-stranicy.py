"""Картинка карты для страницы /igra: стилизованная карта игры с градусами, как в учебнике.

Собирается из тех же слоёв, что грузит игра (maket/assets), поэтому на странице
показывается ровно та карта, над которой прыгают. Поверх — круг и зоны, метки
запасного поля и роза с градусами через 30°.

    <venv>/bin/python tools/karta-dlya-stranicy.py <выход.webp>
"""
import json
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ASSETS = Path(__file__).resolve().parent.parent / 'maket' / 'assets'
SHRIFT = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'

# Окно карты в метрах (x — восток, y — юг) и масштаб, пикселей на метр
X0, Y0, X1, Y1, K = -800, -1000, 800, 1100, 1.0
# Метки запасного поля — те же, что METKI в игре
METKI = [(-560, 40), (-420, 300), (-330, 80)]


def sloy(imya, zapis):
    """Слой карты, приведённый к окну и масштабу картинки."""
    x0, y0, x1, y1, k = zapis
    img = Image.open(ASSETS / imya).convert('RGBA')
    w, h = round((x1 - x0) * K), round((y1 - y0) * K)
    img = img.resize((w, h), Image.NEAREST)
    return img, (round((x0 - X0) * K), round((y0 - Y0) * K))


def px(x, y):
    return ((x - X0) * K, (y - Y0) * K)


def main(vyhod):
    mir = json.loads((ASSETS / 'world.json').read_text())
    W, H = round((X1 - X0) * K), round((Y1 - Y0) * K)
    holst = Image.new('RGBA', (W, H), (40, 60, 40, 255))
    for imya, klyuch in (('karta-dal.webp', 'far'), ('karta-blizh.webp', 'near')):
        img, mesto = sloy(imya, mir[klyuch])
        holst.paste(img, mesto, img)
    d = ImageDraw.Draw(holst)
    f = ImageFont.truetype(SHRIFT, 30)
    fm = ImageFont.truetype(SHRIFT, 22)

    # Круг и зоны
    cx, cy = px(0, 0)
    for r, cvet in ((150, (255, 255, 255, 150)), (100, (255, 255, 255, 190)), (50, (255, 120, 40, 255))):
        rr = r * K
        d.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), outline=cvet, width=4)
    d.ellipse((cx - 8, cy - 8, cx + 8, cy + 8), fill=(255, 120, 40, 255))

    # Метки запасного поля — белые кресты в тёмной обводке, как в игре
    for mx, my in METKI:
        x, y = px(mx, my)
        for dx, dy in ((22, 6), (6, 22)):
            d.rectangle((x - dx - 3, y - dy - 3, x + dx + 3, y + dy + 3), fill=(20, 30, 40, 255))
        for dx, dy in ((22, 6), (6, 22)):
            d.rectangle((x - dx, y - dy, x + dx, y + dy), fill=(245, 245, 245, 255))
    x, y = px(-440, 400)
    d.text((x, y), 'запасное поле', font=fm, fill='white', stroke_width=3, stroke_fill=(20, 30, 40), anchor='mm')

    # Роза с градусами в правом верхнем углу
    rx, ry, R = W - 220, 220, 175
    d.ellipse((rx - R, ry - R, rx + R, ry + R), fill=(16, 28, 48, 170), outline='white', width=4)
    for g in range(0, 360, 30):
        a = math.radians(g)
        s, c = math.sin(a), -math.cos(a)
        dl = 22 if g % 90 == 0 else 12
        d.line((rx + s * (R - dl), ry + c * (R - dl), rx + s * R, ry + c * R), fill='white', width=4)
        if g % 90:
            d.text((rx + s * (R - 42), ry + c * (R - 42)), str(g), font=ImageFont.truetype(SHRIFT, 22),
                   fill=(220, 230, 240), anchor='mm')
    for g, bukva in ((0, 'С 0°'), (90, 'В 90°'), (180, 'Ю 180°'), (270, 'З 270°')):
        a = math.radians(g)
        d.text((rx + math.sin(a) * (R - 82), ry - math.cos(a) * (R - 52)), bukva, font=ImageFont.truetype(SHRIFT, 28),
               fill=(255, 140, 60) if g == 0 else 'white', anchor='mm')
    d.polygon([(rx, ry - R + 85), (rx - 11, ry), (rx + 11, ry)], fill=(255, 120, 40))
    d.polygon([(rx, ry + R - 85), (rx - 11, ry), (rx + 11, ry)], fill='white')

    # Масштабная линейка 500 м
    lx, ly = 40, H - 50
    d.rectangle((lx - 6, ly - 34, lx + 500 * K + 6, ly + 14), fill=(16, 28, 48, 170))
    d.line((lx, ly, lx + 500 * K, ly), fill='white', width=6)
    d.text((lx + 250 * K, ly - 18), '500 м', font=f, fill='white', anchor='mm')

    holst = holst.convert('RGB').resize((990, round(H * 990 / W)), Image.LANCZOS)
    holst.save(vyhod, 'WEBP', quality=82, method=6)
    print(vyhod, holst.size, Path(vyhod).stat().st_size)


if __name__ == '__main__':
    main(sys.argv[1])
