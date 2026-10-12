#!/usr/bin/env python3
"""Ровное небо: заменяет фон плаката гладкой поверхностью, вмятины и складки бумаги уходят.

Запуск: python nebo.py вход.png выход.png [--maska maska.png]
Небо ищется по цвету кромки кадра; его цвет приближается многочленом 4-й степени
по x, y (так сохраняется естественный переход к горизонту и ореол солнца),
стропы и тонкие детали в маску не попадают.
"""
import sys, cv2, numpy as np

def mnogochlen(x, y, st=4):
    return np.stack([x**i*y**j for i in range(st+1) for j in range(st+1-i)], -1)

def Nebo(im):
    h, w = im.shape[:2]
    s = 320/max(h, w); hm, wm = round(h*s), round(w*s)
    mal = cv2.resize(im, (wm, hm), interpolation=cv2.INTER_AREA)
    lab = cv2.cvtColor(mal, cv2.COLOR_BGR2LAB).astype(np.float32)
    ves = np.float32([0.45, 1.6, 1.6])                 # яркость весит меньше: вмятины — это перепад яркости
    # затравка — самый частый цвет кромки кадра
    kr = np.concatenate([lab[:6].reshape(-1, 3), lab[-6:].reshape(-1, 3), lab[:, :6].reshape(-1, 3), lab[:, -6:].reshape(-1, 3)])
    d = np.linalg.norm((kr[:, None]-kr[None, ::7])*ves, axis=2)
    seme = kr[np.argmax((d < 12).sum(1))]
    m = np.linalg.norm((lab-seme)*ves, axis=2) < 30
    yy, xx = np.mgrid[0:hm, 0:wm].astype(np.float32)
    A = mnogochlen(xx/wm-0.5, yy/hm-0.5)
    for porog in (26, 20, 16, 16):
        k = [np.linalg.lstsq(A[m], lab[..., c][m], rcond=None)[0] for c in range(3)]
        fit = np.stack([A@kc for kc in k], -1)
        raz = np.linalg.norm((lab-fit)*ves, axis=2)
        m = raz < porog
    # связь с кромкой: островки «цвета неба» внутри купола не трогаем
    n, lb = cv2.connectedComponents(m.astype(np.uint8))
    kraj = set(np.unique(np.concatenate([lb[0], lb[-1], lb[:, 0], lb[:, -1]]))) - {0}
    m = np.isin(lb, list(kraj)).astype(np.uint8)
    # маска и гладкое небо в полный размер
    fitB = cv2.cvtColor(np.clip(fit, 0, 255).astype(np.uint8), cv2.COLOR_LAB2BGR)
    gl = cv2.resize(fitB, (w, h), interpolation=cv2.INTER_CUBIC).astype(np.float32)
    m = cv2.resize(m*255, (w, h), interpolation=cv2.INTER_LINEAR)
    # дырки в небе (пятна, вмятины, отличившиеся по цвету) заливаем, если они мелкие
    n, lb, st, _ = cv2.connectedComponentsWithStats((m < 128).astype(np.uint8))
    melkie = np.where(st[:, cv2.CC_STAT_AREA] < h*w*0.004)[0]
    m[np.isin(lb, melkie[melkie > 0])] = 255
    m = cv2.erode(m, np.ones((7, 7), np.uint8))
    # стропы и тонкие детали — из маски вон
    sery = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
    ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
    lin = np.maximum(cv2.morphologyEx(sery, cv2.MORPH_BLACKHAT, ker), cv2.morphologyEx(sery, cv2.MORPH_TOPHAT, ker))
    lin = cv2.dilate((lin > 14).astype(np.uint8)*255, np.ones((3, 3), np.uint8))
    # оставляем только протяжённые линии: точки фактуры бумаги стропами не считаются
    n, lb, st, _ = cv2.connectedComponentsWithStats(lin)
    dlin = np.maximum(st[:, cv2.CC_STAT_WIDTH], st[:, cv2.CC_STAT_HEIGHT])
    # и только те, что упираются в купол или человека: стропа всегда к чему-то пристёгнута
    predmet = cv2.dilate((m < 128).astype(np.uint8), np.ones((15, 15), np.uint8))
    kasanie = np.bincount(lb[predmet > 0].ravel(), minlength=n) > 0
    lin = (np.isin(lb, np.where((dlin >= 40) & kasanie & (np.arange(n) > 0))[0])*255).astype(np.uint8)
    m = cv2.min(m, 255-lin)
    a = cv2.GaussianBlur(m.astype(np.float32)/255, (0, 0), 2.5)[..., None]
    # на небо — гладкая поверхность плюс чуть мелкой фактуры, чтобы не выглядело нарисованным
    f = im.astype(np.float32)
    melk = f-cv2.GaussianBlur(f, (0, 0), 1.2)
    nebo = gl+melk*0.25
    out = f*(1-a)+nebo*a
    return np.clip(out, 0, 255).astype(np.uint8), (a[..., 0]*255).astype(np.uint8)

if __name__ == '__main__':
    im = cv2.imread(sys.argv[1]); out, m = Nebo(im)
    cv2.imwrite(sys.argv[2], out, [cv2.IMWRITE_JPEG_QUALITY, 95])
    if '--maska' in sys.argv: cv2.imwrite(sys.argv[sys.argv.index('--maska')+1], m)
