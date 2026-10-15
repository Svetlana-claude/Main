"""Подложки сертификата по программе: шаблон «крыло» с другой строкой шапки.

Строка «НА САМОСТОЯТЕЛЬНЫЙ ПРЫЖОК» затирается (фон плашки тянется сверху вниз
по каждому столбцу — полосы купола вертикальные, шов не виден), на её место
ставится своя строка тем же шрифтом AGRESSIVE, той же высоты и цвета.

    /usr/bin/python3 glavpryg-sayt/tools/sertifikat-shapka.py <вариант> <имя>="<СТРОКА>" ...
Пишет /var/www/glavpryg/resources/certificates/<вариант>/<имя>.jpg.
"""
import sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont

SAYT = "/var/www/glavpryg/resources"
ISHODNIK = f"{SAYT}/certificates/krylo-2026-10/self.jpg"
SHRIFT = f"{SAYT}/fonts/Agressive-Bold.otf"
# Строка шапки на подложке 1804×2560: полоса затирки, центр, верх и высота заглавных
POLOSA = (436, 278, 1406, 331)
CENTR, VERH, CAP = 921, 293, 26.7
CVET = (72, 100, 160)

im = np.asarray(Image.open(ISHODNIK).convert("RGB")).astype(float)
x0, y0, x1, y1 = POLOSA
verh, niz = im[y0 - 8:y0 - 2].mean(0), im[y1 + 2:y1 + 8].mean(0)
shum = np.random.default_rng(1)
for y in range(y0, y1):
    t = (y - y0) / (y1 - y0)
    im[y, x0:x1] = ((1 - t) * verh + t * niz)[x0:x1] + shum.normal(0, 1.5, (x1 - x0, 3))
fon = Image.fromarray(np.clip(im, 0, 255).astype("uint8"))

# Кегль — по высоте заглавной «Н», как у надписей, которые впечатывает сайт
probnyy = ImageFont.truetype(SHRIFT, 100)
h = probnyy.getbbox("Н")
shrift = ImageFont.truetype(SHRIFT, round(100 * CAP / (h[3] - h[1])))

for para in sys.argv[2:]:
    imya, stroka = para.split("=", 1)
    kartinka = fon.copy()
    d = ImageDraw.Draw(kartinka)
    shir = d.textlength(stroka, font=shrift)
    d.text((CENTR - shir / 2, VERH - shrift.getbbox("Н")[1]), stroka, font=shrift, fill=CVET)
    kartinka.save(f"{SAYT}/certificates/{sys.argv[1]}/{imya}.jpg", quality=92)
    print(imya, round(shir), "px")
