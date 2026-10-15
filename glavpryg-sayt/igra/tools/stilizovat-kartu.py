#!/usr/bin/env python3
"""Карта в стиле игры: снимки учебника → «приставочная» палитра.

    python stilizovat-kartu.py <каталог сборки> <каталог assets>

Берёт из каталога сборки `far.png`, `near.png` (цвет ближнего подогнан под
дальний) и `mask.png` (0 поле, 1 лес, 2 вода) — их выдаёт sobrat-kartu.py.
Основа — сам снимок: поля, дороги, постройки остаются на своих местах и своих
цветов, но сглаживаются в плоские пятна и сводятся к общей палитре из 18 тонов
(палитра снята со снимка k-средними). Лес и вода рисуются поверх своими
узорами: кроны деревьев и рябь. Края леса обводятся тёмной линией.
"""
import sys, cv2, numpy as np
from PIL import Image

src, dst = sys.argv[1], sys.argv[2]
rng = np.random.default_rng(7)
far = cv2.imread(f'{src}/far.png'); near = cv2.imread(f'{src}/near.png')
mask_far = cv2.imread(f'{src}/mask.png', 0)

# палитра — со снимка: сглаживаем, берём k-средние в LAB, слегка добавляем сочности
def sgladit(img, sp, sr):
    return cv2.pyrMeanShiftFiltering(img, sp, sr)
obr = np.vstack([sgladit(far, 6, 22).reshape(-1, 3), sgladit(near, 8, 22).reshape(-1, 3)])
obr = obr[rng.choice(len(obr), 60000, replace=False)]
lab = cv2.cvtColor(obr.reshape(-1, 1, 3), cv2.COLOR_BGR2LAB).reshape(-1, 3).astype(np.float32)
_, _, centry = cv2.kmeans(lab, 18, None, (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 50, 0.5), 4, cv2.KMEANS_PP_CENTERS)
# приставочная сочность: в HSV поднимаем насыщенность и яркость, травяные тона
# сдвигаем к зелёному, сухие — к жёлтому; серые (дороги, крыши) не трогаем
bgr = cv2.cvtColor(centry.astype(np.uint8).reshape(-1, 1, 3), cv2.COLOR_LAB2BGR)
hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV).reshape(-1, 3).astype(float)
for c in hsv:
    if c[1] < 35: c[2] = min(255, c[2] * 1.12); continue
    if 18 <= c[0] <= 45: c[0] = 26 + (c[0] - 26) * 1.6 + (6 if c[2] < 150 else -2)
    c[1] = min(255, max(110, c[1] * 1.9)); c[2] = min(255, c[2] * 1.18 + 12)
hsv[:, 0] = np.clip(hsv[:, 0], 0, 179)
bgr = cv2.cvtColor(hsv.astype(np.uint8).reshape(-1, 1, 3), cv2.COLOR_HSV2BGR)
PAL = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB).reshape(-1, 3).astype(np.float32)

PAL_ISH = centry                                             # исходные центры — для выбора
def k_palitre(img):
    l = cv2.cvtColor(img, cv2.COLOR_BGR2LAB).reshape(-1, 3).astype(np.float32)
    d = ((l[:, None, :] - PAL_ISH[None, :, :]) ** 2).sum(2)
    out = PAL[d.argmin(1)].reshape(img.shape).astype(np.uint8)
    return cv2.cvtColor(out, cv2.COLOR_LAB2BGR)

LES = [tuple(reversed(c)) for c in [(24, 70, 30), (36, 104, 40), (70, 150, 60)]]   # RGB→BGR: тень, крона, блик
VODA = [(150, 90, 40), (190, 130, 60), (230, 200, 140)]      # BGR

def les_maska(img):
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV); h, v = hsv[..., 0].astype(int), hsv[..., 2].astype(int)
    m = (((h >= 42) & (v < 165)) | (v < 85)).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    return cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))

def plitka_lesa(shag):
    """Плитка крон: повторяющийся рисунок — по-приставочному и хорошо сжимается."""
    n = shag * 2
    t = np.zeros((n, n, 3), np.uint8); t[:] = LES[0]
    for cx, cy in ((shag // 2, shag // 2), (shag + shag // 2, shag + shag // 2)):
        r = max(1, shag // 2 + (shag > 3))
        for dx, dy in ((0, 0), (n, 0), (0, n), (n, n), (-n, 0), (0, -n)):
            cv2.circle(t, (cx + dx, cy + dy), r, LES[1], -1)
            cv2.circle(t, (cx + dx - max(1, r // 3), cy + dy - max(1, r // 3)), max(1, r // 2), LES[2], -1)
    return t

def zalit_dyry(m, plosh):
    """Просветы внутри леса меньше plosh точек — заливаем, крапинки леса меньше plosh/4 — убираем."""
    m = m.astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(1 - m, connectivity=4)
    for i in range(1, n):
        if st[i, cv2.CC_STAT_AREA] < plosh: m[lab == i] = 1
    n, lab, st, _ = cv2.connectedComponentsWithStats(m, connectivity=4)
    for i in range(1, n):
        if st[i, cv2.CC_STAT_AREA] < plosh // 4: m[lab == i] = 0
    return m

def risovat_les(out, m, shag):
    t = plitka_lesa(shag); n = t.shape[0]
    h, w = m.shape
    uzor = np.tile(t, (h // n + 1, w // n + 1, 1))[:h, :w]
    out[m == 1] = uzor[m == 1]
    # обводка края леса
    kray = cv2.morphologyEx(m, cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8))
    out[(kray == 1) & (m == 0)] = (18, 45, 20)

def risovat_vodu(out, m):
    out[m == 1] = VODA[0]
    ys, xs = np.nonzero(m)
    for x, y in zip(xs, ys):
        if (x + 2 * y) % 9 == 0 and y % 3 == 0:
            cv2.line(out, (int(x), int(y)), (int(x + 3), int(y)), VODA[1], 1)
    kray = cv2.morphologyEx(m, cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8))
    out[(kray == 1) & (m == 0)] = VODA[2]

def stilizovat(img, sp, mask_les, mask_voda, shag):
    out = k_palitre(sgladit(img, sp, 30))
    out = cv2.medianBlur(out, 3)
    risovat_les(out, mask_les, shag)
    if mask_voda is not None: risovat_vodu(out, mask_voda)
    return out

import json
mir = json.load(open(f'{src}/world.json'))
X0, Y0, X1, Y1, FAR = mir['far']; NX0, NY0, NX1, NY1, NEAR = mir['near']
mfar = cv2.resize(mask_far, (far.shape[1], far.shape[0]), interpolation=cv2.INTER_NEAREST)
voda = cv2.GaussianBlur((mfar == 2).astype(np.float32), (0, 0), 3) > 0.5          # скруглить пруды
les_far = (zalit_dyry((mfar == 1) | (les_maska(far) == 1), 40) == 1) & ~voda
les_near = zalit_dyry(les_maska(near), 120)
# игровая маска (5 м/клетка) — ровно то, что нарисовано: лес дальнего слоя,
# а в пределах ближнего — лес ближнего слоя
les_mir = les_far.astype(np.uint8).copy()
fx0, fy0 = int((NX0 - X0) * FAR), int((NY0 - Y0) * FAR)
fx1, fy1 = int((NX1 - X0) * FAR), int((NY1 - Y0) * FAR)
les_mir[fy0:fy1, fx0:fx1] = cv2.resize(les_near, (fx1 - fx0, fy1 - fy0), interpolation=cv2.INTER_AREA) > 0
MS = mir['mask'][2]
mw, mh = mask_far.shape[1], mask_far.shape[0]
igr = np.zeros((mh, mw), np.uint8)
igr[cv2.resize(les_mir.astype(np.float32), (mw, mh), interpolation=cv2.INTER_AREA) > 0.5] = 100
igr[cv2.resize(voda.astype(np.float32), (mw, mh), interpolation=cv2.INTER_AREA) > 0.5] = 200
cv2.imwrite(f'{dst}/maska.png', igr)
sfar = stilizovat(far, 6, les_far.astype(np.uint8), voda.astype(np.uint8), 3)
snear = stilizovat(near, 8, les_near, None, 5)
cv2.imwrite(f'{src}/far-stil.png', sfar); cv2.imwrite(f'{src}/near-stil.png', snear)

# без потерь: плоские цвета и повторяющиеся узоры так сжимаются лучше, чем с потерями
Image.fromarray(cv2.cvtColor(sfar, cv2.COLOR_BGR2RGB)).save(f'{dst}/karta-dal.webp', lossless=True, quality=100, method=6)
h, w = snear.shape[:2]; F = 60
y = np.minimum(np.arange(h), np.arange(h)[::-1]); x = np.minimum(np.arange(w), np.arange(w)[::-1])
a = np.clip(np.minimum.outer(y, x) / F, 0, 1); a = (a * a * (3 - 2 * a) * 255).astype(np.uint8)
Image.fromarray(np.dstack([cv2.cvtColor(snear, cv2.COLOR_BGR2RGB), a])).save(f'{dst}/karta-blizh.webp', lossless=True, quality=100, method=6)
print('готово:', sfar.shape, snear.shape)
