#!/usr/bin/env python3
"""Карты игры по временам года: осень, голый лес, зима, весна.

    python sezony.py <каталог assets>

Берёт летние `karta-dal.webp`, `karta-blizh.webp`, `karta-shir.webp` и
перекрашивает их в `assets/sezon/<сезон>/` с теми же именами. Карты сведены к
палитре (stilizovat-kartu.py, osm-karta.py), поэтому всё делится по цвету:
лес — три цвета узора крон и обводка, вода — три цвета ряби, дороги и крыши —
светлые малонасыщенные, остальное — поля и луга. Каждому классу — свой цвет
сезона; у леса цвет кроны выбирается по клетке 10×10 точек, так что осенний лес
пёстрый, а зимний — в снегу пятнами. Альфа (растушёвка краёв) сохраняется.
"""
import sys, os, numpy as np, cv2
from PIL import Image

dst = sys.argv[1]
LES = {(24, 70, 30): 0, (36, 104, 40): 1, (70, 150, 60): 2, (20, 45, 18): 3}   # тень, крона, блик, край
VODA = {(40, 90, 150): 0, (60, 130, 190): 1, (140, 200, 230): 2, (230, 200, 140): 2}

def klass(rgb, sovp):
    k = np.full(rgb.shape[:2], -1, np.int8)
    for c, i in sovp.items(): k[(rgb == c).all(2)] = i
    return k

def kletka(h, w, n=10):
    """Случайное число 0…1 на клетку n×n — одно и то же при каждой сборке."""
    r = np.random.default_rng(11).random((h // n + 1, w // n + 1))
    return np.kron(r, np.ones((n, n)))[:h, :w]

def smeshat(a, b, k):
    return (a * (1 - k[..., None]) + np.array(b) * k[..., None]).astype(np.uint8)

def perekrasit(rgb, sezon):
    h, w = rgb.shape[:2]
    les, voda = klass(rgb, LES), klass(rgb, VODA)
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV).astype(np.float32)
    H, Sat, V = hsv[..., 0] * 2, hsv[..., 1] / 255, hsv[..., 2] / 255
    svetloe = (Sat < 0.6) & (V > 0.88) & (les < 0) & (voda < 0)        # дороги, крыши, полосы
    pole = (les < 0) & (voda < 0) & ~svetloe
    zelen = pole & (H > 62)                                             # луга
    zhelt = pole & (H <= 62)                                            # пашня, жнивьё
    out = rgb.copy(); r = kletka(h, w)
    def krona(nabor):
        """Кроны по клеткам: nabor — [(доля, тень, крона, блик)]."""
        gran = np.cumsum([n[0] for n in nabor])
        for i, (_, ten, kr, blik) in enumerate(nabor):
            m = (r < gran[i]) & (r >= (gran[i - 1] if i else 0))
            out[m & (les == 0)] = ten; out[m & (les == 1)] = kr; out[m & (les == 2)] = blik
    if sezon == 'osen':
        krona([(0.35, (22, 64, 30), (36, 100, 42), (66, 140, 58)),             # хвоя
               (0.30, (92, 74, 18), (200, 160, 32), (240, 206, 80)),           # берёза
               (0.22, (96, 46, 16), (208, 110, 34), (240, 160, 70)),           # клён, осина
               (0.13, (70, 30, 18), (150, 58, 30), (196, 96, 52))])            # дуб
        out[les == 3] = (40, 34, 16)
        g = out[zelen].astype(np.float32); out[zelen] = smeshat(g, (176, 166, 92), np.full(len(g), 0.55))
        g = out[zhelt].astype(np.float32); out[zhelt] = smeshat(g, (150, 112, 64), np.full(len(g), 0.45))
    elif sezon == 'golaya':                                                    # ноябрь, бесснежье
        krona([(0.35, (26, 52, 34), (40, 80, 50), (64, 104, 66)),
               (0.65, (78, 66, 54), (122, 104, 86), (150, 132, 112))])
        out[les == 3] = (40, 36, 30)
        g = out[pole].astype(np.float32); out[pole] = smeshat(g, (138, 128, 92), np.full(len(g), 0.65))
        out[voda == 0] = (60, 84, 110); out[voda == 1] = (80, 104, 128)
    elif sezon == 'zima':
        krona([(0.5, (26, 46, 40), (40, 70, 56), (226, 234, 242)),             # ель в снегу
               (0.5, (110, 112, 116), (176, 180, 188), (236, 240, 246))])      # голые ветви и снег
        out[les == 3] = (52, 60, 64)
        snezh = (236 + (V[pole] - 0.7) * 28).clip(222, 250)
        out[pole] = np.stack([snezh, snezh + 2, snezh + 8], 1).clip(0, 255).astype(np.uint8)
        doroga = svetloe & (Sat < 0.2); out[doroga] = (196, 192, 184); out[svetloe & ~doroga] = (206, 196, 176)
        out[voda == 0] = (196, 212, 226); out[voda == 1] = (222, 232, 242); out[voda == 2] = (240, 246, 250)
    elif sezon == 'vesna':
        krona([(0.35, (24, 70, 32), (40, 108, 44), (72, 150, 62)),
               (0.65, (52, 104, 34), (98, 170, 60), (150, 206, 96))])          # свежая листва
        g = out[zelen].astype(np.float32); out[zelen] = smeshat(g, (120, 186, 72), np.full(len(g), 0.4))
        g = out[zhelt].astype(np.float32); out[zhelt] = smeshat(g, (128, 96, 62), np.full(len(g), 0.55))  # пахота
    return out

for sezon in ('osen', 'golaya', 'zima', 'vesna'):
    os.makedirs(f'{dst}/sezon/{sezon}', exist_ok=True)
    for imya in ('karta-dal', 'karta-blizh', 'karta-shir'):
        im = Image.open(f'{dst}/{imya}.webp')
        rgb = np.array(im.convert('RGB'))
        out = perekrasit(rgb, sezon)
        if im.mode == 'RGBA': out = np.dstack([out, np.array(im)[..., 3]])
        Image.fromarray(out).save(f'{dst}/sezon/{sezon}/{imya}.webp', lossless=True, quality=100, method=6)
    print(sezon, 'готово')
