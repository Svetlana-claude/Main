"""Подложки сертификата A5 из образцов заказчика: обрезка под пропорции A5,
увеличение вдвое (≈ 310 dpi), изменяемые надписи (имя, дата, программа, номер)
закрашиваются цветом фона — сайт впечатывает их сам.

    /usr/bin/python3 glavpryg-sayt/tools/sertifikat-podlozhki.py <образец-самостоятельный> <образец-тандем>
Пишет /var/www/glavpryg/resources/certificates/{self,tandem}.jpg
"""
import sys
from PIL import Image, ImageDraw

KUDA = "/var/www/glavpryg/resources/certificates"
# Прямоугольники надписей в координатах образца 950×1280
ZAKRASIT = {
    "self":   [(470, 955, 905, 997), (470, 1009, 915, 1038), (248, 1126, 850, 1162), (248, 1174, 445, 1212)],
    "tandem": [(350, 940, 705, 1003), (225, 1084, 765, 1224)],
}
for vid, put in zip(("self", "tandem"), sys.argv[1:3]):
    im = Image.open(put).convert("RGB")
    assert im.size == (950, 1280), im.size
    d = ImageDraw.Draw(im)
    px = im.load()
    for x0, y0, x1, y1 in ZAKRASIT[vid]:
        # Фон образца не чисто белый: заливаем медианой рамки вокруг надписи,
        # иначе края заплатки видны.
        kraj = [px[x, y] for x in range(x0 - 3, x1 + 4) for y in (y0 - 3, y1 + 3)] \
             + [px[x, y] for y in range(y0 - 3, y1 + 4) for x in (x0 - 3, x1 + 3)]
        cvet = tuple(sorted(k[i] for k in kraj)[len(kraj) // 2] for i in range(3))
        d.rectangle((x0, y0, x1, y1), fill=cvet)
    shir = round(1280 * 148 / 210)            # 902: пропорции A5
    sdvig = (950 - shir) // 2
    im = im.crop((sdvig, 0, sdvig + shir, 1280)).resize((shir * 2, 2560), Image.LANCZOS)
    im.save(f"{KUDA}/{vid}.jpg", quality=92)
    print(vid, im.size, "сдвиг", sdvig)
