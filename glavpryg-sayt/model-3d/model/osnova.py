#!/usr/bin/env python3
"""Основа процедурных 3D-моделей парашютных систем: геометрия, манекен, запись GLB.

Модели строятся числами, без редактора, поэтому правятся текстом и пересобираются
за секунду. Каждая система — свой скрипт рядом (`sportivnaya-sistema.py`,
`lesnik-3.py`): он описывает детали и зовёт `vypustit()`. Детали — узлы glTF с
именами-ключами (`podushka`, `kolco_zps` …): по ним просмотрщик подсвечивает деталь.

Оси: y вверх, парашютист смотрит в +z, его правая рука — в −x. Единица — метр.
Сжатие и квантование — следующим шагом, `gltfpack` (см. `../prosmotr/sobrat.sh`).
"""
import json
import math
import struct
from pathlib import Path

import numpy as np

ZDES = Path(__file__).resolve().parent

# Материалы: цвет (sRGB), металличность, шероховатость
MATERIALY = {
    "manekan": ("#c4c8cf", 0.0, 0.8),
    "ranec": ("#31384d", 0.0, 0.75),
    "ranec_zap": ("#3b4560", 0.0, 0.75),
    "akcent": ("#f26a1b", 0.0, 0.6),
    "lenta": ("#1d2029", 0.0, 0.8),
    "metall": ("#c9ced6", 0.9, 0.3),
    "krasnyy": ("#e8452c", 0.0, 0.55),
    "zheltyy": ("#ffd400", 0.0, 0.6),
    "pribor": ("#111318", 0.2, 0.4),
    "ekran": ("#8fd3a8", 0.0, 0.3),
    # спортивная система — по фотографиям заказчика (Aerodyne Icon)
    "chernyy": ("#1e2025", 0.0, 0.85),
    "bezh": ("#b9b29f", 0.0, 0.9),
    "kant": ("#43474f", 0.0, 0.7),
    "siniy": ("#1f55c8", 0.0, 0.6),
    "belyy": ("#e9e9e4", 0.0, 0.7),
    # «Лесник-3» — по фотографиям заказчика
    "siniy_les": ("#3a52a8", 0.0, 0.85),
    "seryy": ("#a3a49e", 0.0, 0.9),
    "olivka": ("#5f6b3c", 0.0, 0.8),
    "olivka_t": ("#4b5530", 0.0, 0.8),
    "lenta_ol": ("#33381f", 0.0, 0.85),
    "shlang": ("#23262b", 0.1, 0.5),
}


def cvet(hex_):
    """sRGB → линейный, как требует glTF."""
    c = [int(hex_[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    return [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c]


def norm(v):
    v = np.asarray(v, float)
    d = np.linalg.norm(v, axis=-1, keepdims=True)
    return v / np.where(d == 0, 1, d)


# ---------- Сетка: позиции, нормали, индексы ----------

class Setka:
    def __init__(self, p=None, n=None, i=None):
        self.p = np.zeros((0, 3)) if p is None else np.asarray(p, float)
        self.n = np.zeros((0, 3)) if n is None else np.asarray(n, float)
        self.i = np.zeros((0,), np.int64) if i is None else np.asarray(i, np.int64)

    def __add__(self, o):
        return Setka(np.vstack([self.p, o.p]), np.vstack([self.n, o.n]),
                     np.concatenate([self.i, o.i + len(self.p)]))

    def preobr(self, m):
        """Матрица 4×4: точки — целиком, нормали — поворотной частью."""
        r = m[:3, :3]
        p = self.p @ r.T + m[:3, 3]
        n = norm(self.n @ np.linalg.inv(r))
        return Setka(p, n, self.i)


def setka_iz_reshetki(P, N, zamk_u=False):
    """Решётка точек (u × v) → треугольники. zamk_u — замкнуть по первой оси."""
    nu, nv = P.shape[:2]
    idx = np.arange(nu * nv).reshape(nu, nv)
    tri = []
    ur = nu if zamk_u else nu - 1
    for a in range(ur):
        b = (a + 1) % nu
        for c in range(nv - 1):
            q = [idx[a, c], idx[b, c], idx[b, c + 1], idx[a, c + 1]]
            tri += [q[0], q[1], q[2], q[0], q[2], q[3]]
    return Setka(P.reshape(-1, 3), N.reshape(-1, 3), np.array(tri))


def okrugl_korobka(razmer, r, seg=4):
    """Коробка со скруглёнными рёбрами: грани куба, «надутые» к радиусу r."""
    h = np.array(razmer, float) / 2
    vnutr = np.maximum(h - r, 0)
    itog = Setka()
    n = 2 * seg + 2
    t = np.linspace(-1, 1, n)
    for os_ in range(3):
        for zn in (-1, 1):
            u, v = np.meshgrid(t, t, indexing="ij")
            q = np.zeros((n, n, 3))
            a, b = [k for k in range(3) if k != os_]
            q[..., os_] = zn
            q[..., a], q[..., b] = (u, v) if zn > 0 else (v, u)
            if os_ == 1:
                q[..., a], q[..., b] = q[..., b].copy(), q[..., a].copy()
            p = q * h
            c = np.clip(p, -vnutr, vnutr)
            d = norm(p - c)
            p = c + d * r
            itog = itog + setka_iz_reshetki(p, d)
    return itog


def tor(R, r, nu=40, nv=10, dolya=1.0):
    """Тор в плоскости xy, ось — z. dolya < 1 — дуга."""
    u = np.linspace(0, 2 * math.pi * dolya, nu + (0 if dolya == 1 else 1), endpoint=dolya != 1)
    v = np.linspace(0, 2 * math.pi, nv + 1)
    U, V = np.meshgrid(u, v, indexing="ij")
    c = np.stack([np.cos(U), np.sin(U), np.zeros_like(U)], -1)
    n = c * np.cos(V)[..., None] + np.array([0, 0, 1]) * np.sin(V)[..., None]
    p = c * R + n * r
    return setka_iz_reshetki(p, n, zamk_u=dolya == 1)


def cilindr(r, dl, n=20, kryshki=True):
    """Цилиндр вдоль y, центр в нуле."""
    a = np.linspace(0, 2 * math.pi, n, endpoint=False)
    kr = np.stack([np.cos(a), np.zeros(n), np.sin(a)], -1)
    P = np.stack([kr * r - [0, dl / 2, 0], kr * r + [0, dl / 2, 0]], 1)
    N = np.stack([kr, kr], 1)
    s = setka_iz_reshetki(P, N, zamk_u=True)
    if kryshki:
        for zn in (-1, 1):
            p = np.vstack([[0, zn * dl / 2, 0], kr * r + [0, zn * dl / 2, 0]])
            nn = np.tile([0, zn, 0], (n + 1, 1))
            tri = []
            for k in range(n):
                a_, b_ = 1 + k, 1 + (k + 1) % n
                tri += [0, b_, a_] if zn > 0 else [0, a_, b_]
            s = s + Setka(p, nn, tri)
    return s


def sfera(r, nu=24, nv=14):
    u = np.linspace(0, 2 * math.pi, nu, endpoint=False)
    v = np.linspace(-math.pi / 2, math.pi / 2, nv)
    U, V = np.meshgrid(u, v, indexing="ij")
    n = np.stack([np.cos(V) * np.sin(U), np.sin(V), np.cos(V) * np.cos(U)], -1)
    return setka_iz_reshetki(n * r, n, zamk_u=True)


def lenta(tochki, naruzhu, shir, tol, zamk=False):
    """Лента прямоугольного сечения по ломаной. naruzhu — нормаль к телу в каждой точке."""
    P = np.asarray(tochki, float)
    No = norm(naruzhu)
    if zamk:
        T = norm(np.roll(P, -1, 0) - np.roll(P, 1, 0))
    else:
        T = norm(np.gradient(P, axis=0))
    S = norm(np.cross(T, No))
    No = norm(np.cross(S, T))
    w, t = shir / 2, tol / 2
    itog = Setka()
    # четыре грани, у каждой свои вершины — рёбра остаются резкими
    for (a, b, nn) in [((w, t), (-w, t), No), ((-w, t), (-w, -t), -S),
                       ((-w, -t), (w, -t), -No), ((w, -t), (w, t), S)]:
        pa = P + S * a[0] + No * a[1]
        pb = P + S * b[0] + No * b[1]
        Q = np.stack([pa, pb], 1)
        NN = np.stack([nn, nn], 1)
        itog = itog + setka_iz_reshetki(Q, NN, zamk_u=zamk)
    if not zamk:
        for k, zn in ((0, -1), (-1, 1)):
            c = P[k]
            ug = [c + S[k] * x + No[k] * y for x, y in ((w, t), (-w, t), (-w, -t), (w, -t))]
            tri = [0, 1, 2, 0, 2, 3] if zn > 0 else [0, 2, 1, 0, 3, 2]
            itog = itog + Setka(ug, np.tile(T[k] * zn, (4, 1)), tri)
    return itog


def gladko(tochki, n=60, zamk=False):
    """Сплайн Катмулла — Рома через опорные точки."""
    P = np.asarray(tochki, float)
    if zamk:
        P = np.vstack([P[-1], P, P[0], P[1]])
    else:
        P = np.vstack([2 * P[0] - P[1], P, 2 * P[-1] - P[-2]])
    seg = len(P) - 3
    vyh = []
    for k in range(n):
        s = k / (n if zamk else n - 1) * seg
        i = min(int(s), seg - 1)
        t = s - i
        p0, p1, p2, p3 = P[i:i + 4]
        vyh.append(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t
                          + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3))
    return np.array(vyh)


def matr(sdvig=(0, 0, 0), povorot=None, masshtab=1.0):
    m = np.eye(4)
    if povorot is not None:
        m[:3, :3] = povorot
    m[:3, :3] *= masshtab
    m[:3, 3] = sdvig
    return m


def bazis(os_z, verh=(0, 1, 0)):
    """Поворот, при котором локальная z смотрит по os_z, а y — по возможности вверх."""
    z = norm(os_z)
    x = norm(np.cross(verh, z))
    y = np.cross(z, x)
    return np.stack([x, y, z], 1)


def rot_y(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


# ---------- Строительное тело: торс как суперэллипс по высоте ----------
# Системы строятся на этом гладком теле, а при выпуске натягиваются на манекен
# заказчика (см. «Манекен заказчика» ниже) — так их описания не зависят от фигуры.

# высота → (полуширина по x, полуглубина по z); ниже 0,80 торс сходится между бёдер
PROFIL = [(0.725, 0.020, 0.020), (0.745, 0.060, 0.060), (0.775, 0.090, 0.090),
          (0.80, 0.115, 0.104), (0.84, 0.150, 0.108), (0.90, 0.168, 0.110), (1.05, 0.148, 0.098),
          (1.25, 0.168, 0.108), (1.42, 0.182, 0.105), (1.52, 0.175, 0.095),
          (1.58, 0.140, 0.080), (1.62, 0.085, 0.068), (1.66, 0.064, 0.058)]
STEPEN = 2.6


def profil(y):
    ys = [p[0] for p in PROFIL]
    return np.interp(y, ys, [p[1] for p in PROFIL]), np.interp(y, ys, [p[2] for p in PROFIL])


def poverh(y, ugol_gr, otstup=0.0):
    """Точка на строительном торсе: ugol 0° — грудь (+z), +90° — левый бок (+x)."""
    a, b = profil(y)
    t = math.radians(ugol_gr)
    s, c = math.sin(t), math.cos(t)
    # суперэллипс: |x/a|^p + |z/b|^p = 1
    k = (abs(s / a) ** STEPEN + abs(c / b) ** STEPEN) ** (-1 / STEPEN)
    p = np.array([s * k, y, c * k])
    # нормаль суперэллипса
    nx = np.sign(s) * abs(p[0] / a) ** (STEPEN - 1) / a
    nz = np.sign(c) * abs(p[2] / b) ** (STEPEN - 1) / b
    n = norm([nx, 0, nz])
    return p + n * otstup, n


def put_po_torsu(opory, otstup, n=50):
    """Опоры (высота, угол) → гладкий путь по поверхности торса и нормали."""
    o = gladko(np.array(opory, float), n)
    pt, nr = zip(*[poverh(y, u, otstup) for y, u in o])
    return np.array(pt), np.array(nr)


# строительное бедро: ось от таза вниз, радиусы вверху и внизу (для левого, zn = +1)
BEDRO = ((0.077, 0.84, -0.004), (0.094, 0.585, 0.02), 0.108, 0.078)
BEDRO_OKRUG = 0.25
# ножной обхват: середина петли на бедре ниже паха, подъём спереди-снаружи;
# кольцо на бедре, куда сходятся лямка, обхват и боковая лента, — у паховой складки
OBHVAT_Y = 0.70
OBHVAT_NAKLON = 0.045
KOLCO_Y = 0.885


def bedro(zn, y):
    """Центр и радиус строительного бедра на высоте y — по ним строятся ножные обхваты."""
    (x1, y1, z1), (x2, y2, z2), r1, r2 = BEDRO
    t = (y1 - y) / (y1 - y2)
    r = r1 + (r2 - r1) * t
    if t < 0.35:  # бедро сужается к тазу
        r *= 1 - BEDRO_OKRUG * (1 - t / 0.35) ** 2
    return np.array([zn * (x1 + (x2 - x1) * t), y, z1 + (z2 - z1) * t]), r


def konechnost(verh, niz, r1, r2, n=24, srez=False):
    """Усечённый конус от точки verh (радиус r1) до niz (r2); srez — плоский торец внизу."""
    verh, niz = np.asarray(verh, float), np.asarray(niz, float)
    dl = float(np.linalg.norm(verh - niz))
    m = matr((verh + niz) / 2, bazis([0, 0, 1], verh=verh - niz))
    s = konus(r1, r2, dl, n).preobr(m)
    if srez:
        s = s + cilindr(r2, 0.002, n, True).preobr(m @ matr((0, -dl / 2, 0)))
    return s


def konus(r1, r2, dl, n=20):
    """Усечённый конус вдоль y: r1 вверху, r2 внизу."""
    a = np.linspace(0, 2 * math.pi, n, endpoint=False)
    kr = np.stack([np.cos(a), np.zeros(n), np.sin(a)], -1)
    P = np.stack([kr * r2 - [0, dl / 2, 0], kr * r1 + [0, dl / 2, 0]], 1)
    nk = norm(kr + [0, (r2 - r1) / dl, 0])
    return setka_iz_reshetki(P, np.stack([nk, nk], 1), zamk_u=True)


def trubka(tochki, r, n=10):
    """Трубка круглого сечения по ломаной — шланги и тросы."""
    P = np.asarray(tochki, float)
    T = norm(np.gradient(P, axis=0))
    opora = np.where(np.abs(T[:, 1:2]) < 0.9, [[0, 1, 0]], [[1, 0, 0]])
    A = norm(np.cross(T, opora))
    B = np.cross(T, A)
    u = np.linspace(0, 2 * math.pi, n, endpoint=False)
    N = A[:, None, :] * np.cos(u)[None, :, None] + B[:, None, :] * np.sin(u)[None, :, None]
    return setka_iz_reshetki(np.transpose(P[:, None, :] + N * r, (1, 0, 2)),
                             np.transpose(N, (1, 0, 2)), zamk_u=True)


def ramka(shir, vys, r_ugla, tol):
    """Плоская металлическая рамка со скруглёнными углами в плоскости xy."""
    pts = []
    hx, hy = shir / 2 - r_ugla, vys / 2 - r_ugla
    for cx, cy, a0 in ((hx, hy, 0), (-hx, hy, 90), (-hx, -hy, 180), (hx, -hy, 270)):
        for k in range(7):
            a = math.radians(a0 + k * 15)
            pts.append([cx + r_ugla * math.cos(a), cy + r_ugla * math.sin(a), 0])
    pts = np.array(pts)
    return lenta(pts, np.tile([0, 0, 1], (len(pts), 1)), tol, tol, zamk=True)


def obhvat_bedra(zn, pb, nb, shir=0.04, tol=0.007):
    """Ножной обхват: петля вокруг бедра и ход к кольцу на бедре pb.
    Возвращает сетку и точку с нормалью для пряжки."""
    f0 = math.atan2(0.9, zn * 0.45)
    pts, nrs = [], []
    for k in range(64):
        f = 2 * math.pi * k / 64
        d = np.array([math.cos(f), 0, math.sin(f)])
        cb, rb = bedro(zn, OBHVAT_Y + OBHVAT_NAKLON * math.cos(f - f0))
        pts.append(cb + d * (rb + tol / 2 + 0.003))
        nrs.append(d)
    s = lenta(np.array(pts), np.array(nrs), shir, tol, zamk=True)
    k0 = int(round((f0 % (2 * math.pi)) / (2 * math.pi) * 64)) % 64
    vhod = gladko([pb, (pb + pts[k0]) / 2 + nb * 0.01, pts[k0]], 14)
    s = s + lenta(vhod, np.tile(nb, (len(vhod), 1)), shir, tol)
    k1 = (k0 + zn * 6) % 64
    return s, np.array(pts[k1]), np.array(nrs[k1])


# ---------- Манекен заказчика и натяжка систем на него ----------
# Манекен — STL заказчика (`maneken-opty.stl`: торс с шеей, руками выше локтя и бёдрами до
# середины, высоты — метры от пола), прорежен Blender'ом (`maneken/iz-stl.py`) и не меняется.
# Системы строятся на строительном теле выше, а при выпуске каждая их точка
# переносится на манекен: высота — по ориентирам фигуры (пах, талия, грудь, плечи,
# шея), угол вокруг оси торса сохраняется, отступ от поверхности — тоже. Поверхность
# манекена берётся выпуклой оболочкой сечения: ленты и ранец перекрывают ложбины
# (позвоночник, межгрудную), как на живом человеке.

MANEKEN_GLB = ZDES / "maneken" / "maneken.glb"
# высота на строительном теле → высота на манекене: пах, талия, грудные, плечи, основание и верх шеи
OPORY_STAR = [0.585, 0.785, 1.05, 1.40, 1.56, 1.62, 1.70]
OPORY_NOV = [0.575, 0.775, 1.03, 1.26, 1.41, 1.445, 1.475]
PAH = 0.775        # высота паха манекена: ниже — два бедра
SHAG_Y = 0.004     # шаг таблицы сечений
UGLY = 360         # лучей на сечение
SHIR_TORSA = 0.175  # полуширина торса без рук, м


def chitat_glb(put):
    """Позиции, нормали и индексы всех примитивов GLB без сжатия."""
    d = Path(put).read_bytes()
    dl = struct.unpack("<I", d[12:16])[0]
    js = json.loads(d[20:20 + dl])
    buf = d[20 + dl + 8:]

    def acc(i):
        a = js["accessors"][i]
        bv = js["bufferViews"][a["bufferView"]]
        tip = {5126: np.float32, 5125: np.uint32, 5123: np.uint16}[a["componentType"]]
        k = {"VEC3": 3, "SCALAR": 1}[a["type"]]
        x = np.frombuffer(buf, tip, a["count"] * k, bv.get("byteOffset", 0) + a.get("byteOffset", 0))
        return x.reshape(-1, 3) if k == 3 else x

    P, N, I = [], [], []
    for m in js["meshes"]:
        for pr in m["primitives"]:
            sm = sum(len(x) for x in P)
            P.append(acc(pr["attributes"]["POSITION"]).astype(float))
            N.append(acc(pr["attributes"]["NORMAL"]).astype(float))
            I.append(acc(pr["indices"]).astype(np.int64) + sm)
    return np.vstack(P), np.vstack(N), np.concatenate(I)


def _srez(T, y):
    """Сечение треугольников T (k, 3, 3) плоскостью y → отрезки (m, 2, 2) в (x, z)."""
    d = T[:, :, 1] - y
    vyshe = (d > 0).sum(1)
    m = (vyshe == 1) | (vyshe == 2)
    T, d = T[m], d[m]
    konci = []
    for a, b in ((0, 1), (1, 2), (2, 0)):
        ok = (d[:, a] > 0) != (d[:, b] > 0)
        t = np.where(ok, d[:, a] / np.where(ok, d[:, a] - d[:, b], 1), 0)
        konci.append((ok, (T[:, a] + (T[:, b] - T[:, a]) * t[:, None])[:, [0, 2]]))
    ok = np.stack([k[0] for k in konci], 1)
    pts = np.stack([k[1] for k in konci], 1)
    dva = ok.sum(1) == 2
    ok, pts = ok[dva], pts[dva]
    pervyy = np.argmax(ok, 1)
    vtoroy = 2 - np.argmax(ok[:, ::-1], 1)
    r = np.arange(len(pts))
    return np.stack([pts[r, pervyy], pts[r, vtoroy]], 1)


def _luchi(seg, c, ugly):
    """Первое пересечение лучей из c (угол 0 — +z, 90° — +x) с отрезками → расстояния."""
    dv = np.stack([np.sin(ugly), np.cos(ugly)], 1)[:, None, :]
    a = seg[None, :, 0] - c
    e = seg[None, :, 1] - seg[None, :, 0]
    den = dv[..., 0] * e[..., 1] - dv[..., 1] * e[..., 0]
    with np.errstate(divide="ignore", invalid="ignore"):
        t = (a[..., 0] * e[..., 1] - a[..., 1] * e[..., 0]) / den
        s = (a[..., 0] * dv[..., 1] - a[..., 1] * dv[..., 0]) / den
    t = np.where((t > 1e-6) & (s >= 0) & (s <= 1), t, np.inf)
    return t.min(1)


def _obolochka(pts):
    """Выпуклая оболочка точек на плоскости (монотонная цепь)."""
    pts = sorted(set(map(tuple, np.round(pts, 5))))
    if len(pts) < 3:
        return np.array(pts)

    def povorot(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    niz, verh = [], []
    for p in pts:
        while len(niz) >= 2 and povorot(niz[-2], niz[-1], p) <= 0:
            niz.pop()
        niz.append(p)
    for p in reversed(pts):
        while len(verh) >= 2 and povorot(verh[-2], verh[-1], p) <= 0:
            verh.pop()
        verh.append(p)
    return np.array(niz[:-1] + verh[:-1])


def _radiusy_obolochki(pts, c, ugly):
    ob = _obolochka(pts)
    seg = np.stack([ob, np.roll(ob, -1, 0)], 1)
    return _luchi(seg, c, ugly)


class Maneken:
    """Манекен заказчика: сетка для показа и таблицы сечений для натяжки систем."""

    def __init__(self, put=MANEKEN_GLB):
        self.P, self.N, self.I = chitat_glb(put)
        T = self.P[self.I.reshape(-1, 3)]
        self.ugly = np.linspace(-math.pi, math.pi, UGLY, endpoint=False)
        # торс: от паха до верха шеи
        self.ys = np.arange(PAH + 0.002, OPORY_NOV[-1] + 1e-9, SHAG_Y)
        zc, R = [], []
        for y in self.ys:
            seg = _srez(T, y)
            u = np.abs(seg.mean(1)[:, 0]) < 0.03
            zc.append((seg[u, :, 1].min() + seg[u, :, 1].max()) / 2)
        # центр сглажен по высоте — лучи не дёргаются от сечения к сечению
        zc = np.convolve(np.pad(zc, 4, mode="edge"), np.ones(9) / 9, mode="valid")
        for y, z in zip(self.ys, zc):
            seg = _srez(T, y)
            c = np.array([0.0, z])
            r = _luchi(seg, c, self.ugly)  # первое попадание — торс, руки отдельно
            ok = np.isfinite(r)
            pts = c + r[ok, None] * np.stack([np.sin(self.ugly[ok]), np.cos(self.ugly[ok])], 1)
            # выше подмышек сечение сливается с плечом: руку в торс не берём,
            # иначе углы ранца ложатся на плечевые обрубки
            pts = pts[np.abs(pts[:, 0]) <= SHIR_TORSA]
            R.append(_radiusy_obolochki(pts, c, self.ugly))
        self.zc, self.R = np.array(zc), np.array(R)
        # бёдра: ниже паха, левое (zn = +1) и правое
        self.ys_b = np.arange(self.P[:, 1].min() + 0.008, PAH - 0.01, SHAG_Y)
        self.bedra = {}
        for zn in (-1, 1):
            cs, Rs = [], []
            for y in self.ys_b:
                seg = _srez(T, y)
                m = seg.mean(1)
                # бёдра у паха почти смыкаются (зазор 1–1,5 см): делим по середине с малым
                # запасом — с широким оболочка срезала внутренний край ноги, и петля обхвата
                # уходила внутрь бедра
                vnutr = 0.004
                tochki = seg[(m[:, 0] * zn > vnutr) & (np.abs(m[:, 0]) < 0.3)].reshape(-1, 2)
                c = tochki.mean(0)
                cs.append(c)
                Rs.append(_radiusy_obolochki(tochki, c, self.ugly))
            self.bedra[zn] = (np.array(cs), np.array(Rs))

    @staticmethod
    def _tabl(ys, R, y, u):
        """Билинейно из таблицы R[высота, угол]."""
        fy = np.clip((y - ys[0]) / (ys[1] - ys[0]), 0, len(ys) - 1.001)
        iy = fy.astype(int)
        ty = fy - iy
        fu = (u + math.pi) / (2 * math.pi) * UGLY
        iu = np.floor(fu).astype(int) % UGLY
        tu = fu - np.floor(fu)
        iu2 = (iu + 1) % UGLY
        r0 = R[iy, iu] * (1 - tu) + R[iy, iu2] * tu
        r1 = R[iy + 1, iu] * (1 - tu) + R[iy + 1, iu2] * tu
        return r0 * (1 - ty) + r1 * ty

    def setka(self):
        return Setka(self.P, self.N, self.I)

    # --- натяжка ---

    def _tors(self, p, yn):
        """Перенос точек по торсу: угол и отступ от строительной поверхности сохраняются."""
        u = np.arctan2(p[:, 0], p[:, 2])
        r = np.hypot(p[:, 0], p[:, 2])
        a, b = profil(p[:, 1])
        s, c = np.sin(u), np.cos(u)
        r_star = (np.abs(s / a) ** STEPEN + np.abs(c / b) ** STEPEN) ** (-1 / STEPEN)
        r_nov = self._tabl(self.ys, self.R, yn, u) + (r - r_star)
        zc = np.interp(yn, self.ys, self.zc)
        return np.stack([s * r_nov, yn, zc + c * r_nov], 1)

    def _bedro(self, p, yn, storona):
        """Перенос точек по бедру — для ножных обхватов; storona — нога каждой точки (±1)."""
        out = np.zeros_like(p)
        yb = np.minimum(yn, self.ys_b[-1])
        for zn in (-1, 1):
            m = storona == zn
            if not m.any():
                continue
            q = p[m]
            ystar = np.array([bedro(zn, y) for y in q[:, 1]], dtype=object)
            c_st = np.stack([x[0] for x in ystar])
            r_st = np.array([x[1] for x in ystar])
            d = q - c_st
            u = np.arctan2(d[:, 0], d[:, 2])
            cs, Rs = self.bedra[zn]
            c_nov = np.stack([np.interp(yb[m], self.ys_b, cs[:, k]) for k in (0, 1)], 1)
            r_nov = self._tabl(self.ys_b, Rs, yb[m], u) + (np.hypot(d[:, 0], d[:, 2]) - r_st)
            out[m] = np.stack([c_nov[:, 0] + np.sin(u) * r_nov, yn[m], c_nov[:, 1] + np.cos(u) * r_nov], 1)
        return out

    def natyanut(self, p, po_bedru=False, storona=None):
        """Точки систем со строительного тела → на манекен."""
        p = np.asarray(p, float)
        yn = np.interp(p[:, 1], OPORY_STAR, OPORY_NOV)
        pt = self._tors(p, np.maximum(yn, self.ys[0]))
        pt[:, 1] = yn
        if not po_bedru:
            return pt
        # обхват: ниже паха — по бедру, выше (ход к кольцу на бедре) — плавно к торсу
        pb = self._bedro(p, yn, np.where(p[:, 0] >= 0, 1, -1) if storona is None else storona)
        w = np.clip((p[:, 1] - 0.78) / 0.08, 0, 1)[:, None]
        w = w * w * (3 - 2 * w)
        return pb * (1 - w) + pt * w

    def natyanut_setku(self, s, po_bedru=False):
        e = 0.002
        # нога — по связной части сетки: петля обхвата заходит за середину,
        # и по знаку x её внутренний край ушёл бы на чужое бедро
        storona = _storony(s) if po_bedru else None
        p = self.natyanut(s.p, po_bedru, storona)
        n = norm(self.natyanut(s.p + s.n * e, po_bedru, storona) - p)
        return Setka(p, n, s.i)


def _storony(s):
    """Для каждой вершины — знак x середины её связной части сетки."""
    rod = np.arange(len(s.p))

    def koren(a):
        while rod[a] != a:
            rod[a] = rod[rod[a]]
            a = rod[a]
        return a

    for a, b in s.i.reshape(-1, 3)[:, :2].tolist() + s.i.reshape(-1, 3)[:, 1:].tolist():
        ra, rb = koren(a), koren(b)
        if ra != rb:
            rod[ra] = rb
    k = np.array([koren(a) for a in range(len(s.p))])
    sx = np.bincount(k, s.p[:, 0], len(s.p)) / np.maximum(np.bincount(k, None, len(s.p)), 1)
    return np.where(sx[k] >= 0, 1, -1)


# ---------- Запись GLB ----------

class Rakovina:
    """Обтекаемый ранец: контур со спины — «щит», толщина спадает к краю по суперэллипсу,
    так что борта скруглены. Плоская сторона прилегает к спине торса."""
    def __init__(self, kontur, centr, tolsh, q=3.0, prileganie=0.8):
        """kontur — правая половина контура со спины (x ≥ 0) снизу вверх; tolsh — (высоты, толщины);
        q — скругление борта; prileganie — до какой доли ширины торса плоская сторона следует спине."""
        self.C, self.Q, self.tolsh, self.pril = np.array(centr, float), q, tolsh, prileganie
        pol = list(kontur) + [(-x, y) for x, y in reversed(kontur[1:])]
        self.kont = gladko(np.array([[x, y, 0] for x, y in pol]), 240, zamk=True)[:, :2]
        d = self.kont - self.C
        self.ug = np.arctan2(d[:, 1], d[:, 0])
        por = np.argsort(self.ug)
        self.ug, self.rad = self.ug[por], np.linalg.norm(d, axis=1)[por]

    def R(self, t):
        return np.interp(t, self.ug, self.rad, period=2 * math.pi)

    def tolshchina(self, y):
        return float(np.interp(y, *self.tolsh))

    def spina(self, x, y):
        a, b = profil(y)
        xx = min(abs(x), self.pril * a) / a
        return -b * (1 - xx ** STEPEN) ** (1 / STEPEN) - 0.004

    def kontur(self, n):
        t = np.linspace(-math.pi, math.pi, n, endpoint=False)
        return [self.C + self.R(u) * np.array([math.cos(u), math.sin(u)]) for u in t]

    def _p(self, x, y, s_):
        return np.array([x, y, self.spina(x, y) - self.tolshchina(y) * max(0.0, 1 - s_ ** self.Q) ** (1 / self.Q)])

    def tochka(self, x, y, otstup=0.0, s_=None):
        """Точка внешней поверхности над (x, y) со спины и её нормаль (наружу)."""
        d = np.array([x, y]) - self.C
        t = math.atan2(d[1], d[0])
        if s_ is None:
            s_ = min(0.999, np.linalg.norm(d) / self.R(t))
        else:
            x, y = self.C + s_ * self.R(t) * np.array([math.cos(t), math.sin(t)])

        def f(xx, yy):
            dd = np.array([xx, yy]) - self.C
            tt = math.atan2(dd[1], dd[0])
            return self._p(xx, yy, min(0.9995, np.linalg.norm(dd) / self.R(tt)))
        e = 1e-4
        p = f(x, y)
        n = norm(np.cross(f(x, y + e) - f(x, y - e), f(x + e, y) - f(x - e, y)))
        if n[2] > 0:
            n = -n
        return p + n * otstup, n

    def setka(self, nt=96, ns=20):
        """Внешний купол (s = cos^(2/Q) φ — борт скруглён) и плоская сторона к спине."""
        t = np.linspace(-math.pi, math.pi, nt, endpoint=False)
        P = np.zeros((nt, 2 * ns, 3))
        for i, u in enumerate(t):
            r = self.R(u)
            e = np.array([math.cos(u), math.sin(u)])
            for j in range(ns):  # от центра купола к краю
                f = (math.pi / 2) * (1 - j / (ns - 1))
                s_ = max(0.0, math.cos(f)) ** (2 / self.Q)
                x, y = self.C + s_ * r * e
                t_ = self.tolshchina(y) * max(0.0, math.sin(f)) ** (2 / self.Q)
                P[i, j] = (x, y, self.spina(x, y) - t_)
            for j in range(ns):  # от края по спине к центру
                s_ = 1 - j / (ns - 1)
                x, y = self.C + s_ * r * e
                P[i, ns + j] = (x, y, self.spina(x, y))
        # нормали — по соседям решётки
        dU = np.roll(P, -1, 0) - np.roll(P, 1, 0)
        dV = np.gradient(P, axis=1)
        N = norm(np.cross(dV, dU))
        return setka_iz_reshetki(P, N, zamk_u=True)

    @staticmethod
    def razrezat(st, y0):
        """Делит сетку по высоте центров треугольников: выше y0 и ниже."""
        tri = st.i.reshape(-1, 3)
        cy = st.p[tri][:, :, 1].mean(axis=1)
        verh = Setka(st.p, st.n, tri[cy >= y0].reshape(-1))
        niz = Setka(st.p, st.n, tri[cy < y0].reshape(-1))
        return verh, niz

    def naklejka(self, forma, otstup, na=8, nv=16):
        """Накладка по поверхности: forma(a, v) → (x, y), a ∈ [−1, 1] поперёк, v ∈ [0, 1] вдоль."""
        P = np.zeros((na, nv, 3))
        N = np.zeros((na, nv, 3))
        for i, a in enumerate(np.linspace(-1, 1, na)):
            for j, v in enumerate(np.linspace(0, 1, nv)):
                P[i, j], N[i, j] = self.tochka(*forma(a, v), otstup=otstup)
        return setka_iz_reshetki(P, N)

    def po_poverhnosti(self, opory, otstup, n=30):
        pts = gladko(np.array([[x, y, 0] for x, y in opory]), n)
        tn = [self.tochka(x, y, otstup=otstup) for x, y, _ in pts]
        return np.array([a for a, _ in tn]), np.array([b for _, b in tn])


def zapisat_glb(detali, put):
    buf = bytearray()
    views, accessors, meshes, nodes = [], [], [], []
    mat_klyuchi = list(MATERIALY)

    def vid(dannye, cel):
        while len(buf) % 4:
            buf.append(0)
        views.append({"buffer": 0, "byteOffset": len(buf), "byteLength": len(dannye), "target": cel})
        buf.extend(dannye)
        return len(views) - 1

    for kl, po_mat in detali.items():
        prims = []
        for mat, s in po_mat.items():
            p = s.p.astype(np.float32)
            n = norm(s.n).astype(np.float32)
            # обход треугольников — по нормалям вершин, чтобы лицевая сторона смотрела наружу
            t = s.i.reshape(-1, 3).copy()
            gn = np.cross(p[t[:, 1]] - p[t[:, 0]], p[t[:, 2]] - p[t[:, 0]])
            naoborot = (gn * (n[t[:, 0]] + n[t[:, 1]] + n[t[:, 2]])).sum(1) < 0
            t[naoborot] = t[naoborot][:, ::-1]
            idx = t.reshape(-1).astype(np.uint32 if len(p) > 65535 else np.uint16)
            vp = vid(p.tobytes(), 34962)
            accessors.append({"bufferView": vp, "componentType": 5126, "count": len(p), "type": "VEC3",
                              "min": p.min(0).tolist(), "max": p.max(0).tolist()})
            ap = len(accessors) - 1
            accessors.append({"bufferView": vid(n.tobytes(), 34962), "componentType": 5126,
                              "count": len(n), "type": "VEC3"})
            an = len(accessors) - 1
            accessors.append({"bufferView": vid(idx.tobytes(), 34963),
                              "componentType": 5125 if idx.dtype == np.uint32 else 5123,
                              "count": len(idx), "type": "SCALAR"})
            prims.append({"attributes": {"POSITION": ap, "NORMAL": an}, "indices": len(accessors) - 1,
                          "material": mat_klyuchi.index(mat)})
        meshes.append({"name": kl, "primitives": prims})
        nodes.append({"name": kl, "mesh": len(meshes) - 1})

    gltf = {
        "asset": {"version": "2.0", "generator": "glavpryg postroit-model.py"},
        "scene": 0,
        "scenes": [{"nodes": list(range(len(nodes)))}],
        "nodes": nodes, "meshes": meshes, "accessors": accessors, "bufferViews": views,
        "buffers": [{"byteLength": len(buf)}],
        "materials": [{"name": k, "pbrMetallicRoughness": {
            "baseColorFactor": cvet(c) + [1.0], "metallicFactor": m, "roughnessFactor": r}}
            for k, (c, m, r) in MATERIALY.items()],
    }
    js = json.dumps(gltf, ensure_ascii=False, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    while len(buf) % 4:
        buf.append(0)
    dlina = 12 + 8 + len(js) + 8 + len(buf)
    with open(put, "wb") as f:
        f.write(struct.pack("<III", 0x46546C67, 2, dlina))
        f.write(struct.pack("<II", len(js), 0x4E4F534A) + js)
        f.write(struct.pack("<II", len(buf), 0x004E4942) + bytes(buf))


class Sborka:
    """Детали системы по материалам и метки с номерами — на строительном теле."""

    # детали, которые натягиваются по бедру, а не по торсу
    PO_BEDRU = {"obhvaty"}

    def __init__(self):
        self.detali = {}  # ключ → {материал: Setka}
        self.metki = []

    def dobavit(self, kl, mat, s):
        self.detali.setdefault(kl, {})
        self.detali[kl][mat] = self.detali[kl].get(mat, Setka()) + s

    def metka(self, kl, nomer, p, n):
        self.metki.append({"kl": kl, "n": nomer, "p": np.asarray(p, float), "nr": norm(n)})


def vypustit(sborka, imya):
    """Натягивает систему на манекен заказчика и пишет `<imya>.glb` (несжатый)
    и `<imya>.metki.json` рядом со скриптами."""
    man = Maneken()
    detali = {"manekan": {"manekan": man.setka()}}
    for kl, po_mat in sborka.detali.items():
        detali[kl] = {mat: man.natyanut_setku(s, kl in Sborka.PO_BEDRU) for mat, s in po_mat.items()}
    metki = []
    for m in sorted(sborka.metki, key=lambda m: m["n"]):
        s = man.natyanut_setku(Setka(m["p"][None], m["nr"][None], []), m["kl"] in Sborka.PO_BEDRU)
        metki.append({"kl": m["kl"], "n": m["n"], "p": [round(float(x), 4) for x in s.p[0]],
                      "nr": [round(float(x), 3) for x in s.n[0]]})
    glb = ZDES / f"{imya}.glb"
    zapisat_glb(detali, glb)
    (ZDES / f"{imya}.metki.json").write_text(json.dumps(metki, ensure_ascii=False), encoding="utf-8")
    tri = sum(len(s.i) // 3 for d in detali.values() for s in d.values())
    print(f"{glb.name}: {glb.stat().st_size // 1024} КБ, {tri} треугольников, "
          f"{len(detali)} деталей, {len(metki)} меток")
