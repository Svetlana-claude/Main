#!/usr/bin/env python3
"""Строит 3D-модель спортивной парашютной системы на манекене — `ranec-syroy.glb`.

Модель процедурная: вся геометрия описана здесь числами, без редактора, поэтому
правится текстом и пересобирается за секунду. Детали — отдельные узлы glTF с
именами-ключами (`podushka`, `kolco_pz` …): по ним просмотрщик подсвечивает деталь.
Рядом пишется `../prosmotr/src/metki.js` — точки меток с номерами и нормалями.

Оси: y вверх, парашютист смотрит в +z, его правая рука — в −x. Единица — метр.
Сжатие и квантование — следующим шагом, `gltfpack` (см. `../prosmotr/sobrat.sh`).

    /usr/bin/python3 postroit-model.py
"""
import json
import math
import struct
from pathlib import Path

import numpy as np

ZDES = Path(__file__).resolve().parent
VYHOD = ZDES / "ranec-syroy.glb"
METKI = ZDES.parent / "prosmotr" / "src" / "metki.js"

# Материалы: цвет (sRGB), металличность, шероховатость
MATERIALY = {
    "manekan": ("#b9bfcb", 0.0, 0.9),
    "ranec": ("#31384d", 0.0, 0.75),
    "ranec_zap": ("#3b4560", 0.0, 0.75),
    "akcent": ("#f26a1b", 0.0, 0.6),
    "lenta": ("#1d2029", 0.0, 0.8),
    "metall": ("#c9ced6", 0.9, 0.3),
    "krasnyy": ("#e8452c", 0.0, 0.55),
    "zheltyy": ("#ffd400", 0.0, 0.6),
    "pribor": ("#111318", 0.2, 0.4),
    "ekran": ("#8fd3a8", 0.0, 0.3),
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


# ---------- Манекен: торс как суперэллипс по высоте ----------

# высота → (полуширина по x, полуглубина по z)
PROFIL = [(0.80, 0.150, 0.105), (0.90, 0.165, 0.110), (1.05, 0.148, 0.098),
          (1.25, 0.168, 0.108), (1.42, 0.182, 0.105), (1.52, 0.175, 0.095),
          (1.58, 0.140, 0.080), (1.62, 0.075, 0.060), (1.66, 0.050, 0.050)]
STEPEN = 2.6


def profil(y):
    ys = [p[0] for p in PROFIL]
    return np.interp(y, ys, [p[1] for p in PROFIL]), np.interp(y, ys, [p[2] for p in PROFIL])


def poverh(y, ugol_gr, otstup=0.0):
    """Точка на торсе: ugol 0° — грудь (+z), +90° — левый бок парашютиста (+x)."""
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


def manekan():
    ys = np.linspace(0.78, 1.66, 34)
    ug = np.linspace(-180, 180, 48, endpoint=False)
    P = np.zeros((len(ug), len(ys), 3))
    N = np.zeros_like(P)
    for i, u in enumerate(ug):
        for j, y in enumerate(ys):
            P[i, j], N[i, j] = poverh(y, u)
    s = setka_iz_reshetki(P, N, zamk_u=True)
    # низ и шея — шары-заглушки, бёдра и голова
    s = s + sfera(0.05, 16, 10).preobr(matr((0, 1.66, 0)))
    # шея-подставка вместо головы, как у портновского манекена
    s = s + cilindr(0.035, 0.08, 18, True).preobr(matr((0, 1.70, 0)))
    for zn in (-1, 1):
        bedro = konus(0.088, 0.062, 0.48, 24).preobr(
            matr((zn * 0.088, 0.58, 0.015), bazis([0, 0.05, 1], verh=[zn * -0.06, 1, 0])))
        s = s + bedro + sfera(0.088, 20, 12).preobr(matr((zn * 0.088, 0.82, 0.015)))
        s = s + sfera(0.062, 16, 10).preobr(matr((zn * 0.088, 0.34, 0.03)))
    return s


def konus(r1, r2, dl, n=20):
    """Усечённый конус вдоль y: r1 вверху, r2 внизу."""
    a = np.linspace(0, 2 * math.pi, n, endpoint=False)
    kr = np.stack([np.cos(a), np.zeros(n), np.sin(a)], -1)
    P = np.stack([kr * r2 - [0, dl / 2, 0], kr * r1 + [0, dl / 2, 0]], 1)
    nk = norm(kr + [0, (r2 - r1) / dl, 0])
    return setka_iz_reshetki(P, np.stack([nk, nk], 1), zamk_u=True)


# ---------- Детали системы ----------

def postroit():
    detali = {}  # ключ → {материал: Setka}
    metki = []

    def dobavit(kl, mat, s):
        detali.setdefault(kl, {})
        detali[kl][mat] = detali[kl].get(mat, Setka()) + s

    def metka(kl, nomer, p, n):
        metki.append({"kl": kl, "n": nomer, "p": [round(float(x), 4) for x in p],
                      "nr": [round(float(x), 3) for x in norm(n)]})

    dobavit("manekan", "manekan", manekan())

    # Ранец: нижний отсек — основной, верхний — запасной. Спина торса — z ≈ −0.10.
    zs = -0.10
    osn_c = np.array([0, 1.09, zs - 0.095])
    dobavit("osn_otsek", "ranec", okrugl_korobka((0.35, 0.40, 0.19), 0.045).preobr(matr(osn_c)))
    # спинка-подложка за обоими отсеками
    dobavit("osn_otsek", "ranec", okrugl_korobka((0.37, 0.66, 0.03), 0.014).preobr(matr((0, 1.20, zs - 0.005))))
    zap_c = np.array([0, 1.395, zs - 0.08])
    dobavit("zap_otsek", "ranec_zap", okrugl_korobka((0.34, 0.20, 0.16), 0.045).preobr(matr(zap_c)))
    # 2. Клапан основного с чекой — на задней стенке основного отсека
    zad_osn = osn_c[2] - 0.095
    dobavit("klapan_osn", "ranec", okrugl_korobka((0.20, 0.13, 0.012), 0.006).preobr(
        matr((0, 1.07, zad_osn - 0.004))))
    dobavit("klapan_osn", "akcent", okrugl_korobka((0.05, 0.03, 0.01), 0.004).preobr(
        matr((0, 1.115, zad_osn - 0.012))))
    metka("klapan_osn", 2, (0, 1.07, zad_osn - 0.012), (0, 0, -1))
    metka("osn_otsek", 1, (0.13, 0.98, zad_osn + 0.01), (0.5, 0, -1))

    # 3. Бобышка медузы: карман внизу справа, бобышка торчит вбок
    dobavit("bobyshka", "ranec", okrugl_korobka((0.12, 0.012, 0.09), 0.005).preobr(
        matr((-0.10, 0.884, osn_c[2]))))
    bob_p = np.array([-0.175, 0.905, osn_c[2] - 0.03])
    dobavit("bobyshka", "zheltyy", cilindr(0.016, 0.055, 20).preobr(
        matr(bob_p, bazis([0, 0, 1], verh=[1, 0, 0]) @ np.eye(3))))
    usd = gladko([[-0.14, 0.89, osn_c[2] - 0.02], [-0.16, 0.90, osn_c[2] - 0.03], bob_p + [0.0, 0, 0]], 12)
    dobavit("bobyshka", "lenta", lenta(usd, np.tile([0, 1, 0], (len(usd), 1)), 0.012, 0.004))
    metka("bobyshka", 3, bob_p + [-0.02, 0, 0], (-1, -0.3, -0.4))

    # 4–6. Запасной: клапан сверху, на нём блок страхующего прибора
    zad_zap = zap_c[2] - 0.08
    metka("zap_otsek", 4, (0.14, 1.40, zad_zap + 0.012), (0.6, 0.2, -1))
    klap = okrugl_korobka((0.30, 0.012, 0.15), 0.006)
    dobavit("klapan_zap", "ranec_zap", klap.preobr(matr((0, 1.497, zap_c[2] - 0.005))))
    yazyk = okrugl_korobka((0.24, 0.10, 0.012), 0.006)
    dobavit("klapan_zap", "ranec_zap", yazyk.preobr(matr((0, 1.445, zad_zap - 0.004))))
    dobavit("klapan_zap", "akcent", okrugl_korobka((0.25, 0.012, 0.014), 0.005).preobr(
        matr((0, 1.395, zad_zap - 0.005))))
    metka("klapan_zap", 5, (-0.08, 1.505, zap_c[2] - 0.02), (0, 1, -0.3))
    dobavit("pribor", "pribor", okrugl_korobka((0.065, 0.04, 0.014), 0.006).preobr(
        matr((0.05, 1.45, zad_zap - 0.014))))
    dobavit("pribor", "ekran", okrugl_korobka((0.034, 0.016, 0.004), 0.002).preobr(
        matr((0.05, 1.452, zad_zap - 0.022))))
    metka("pribor", 6, (0.05, 1.45, zad_zap - 0.024), (0, 0, -1))

    # Главные лямки: от замков КЗУ на ключицах вниз к бёдрам
    otst = 0.008
    for zn, storona in ((-1, "prav"), (1, "lev")):
        put, nr = put_po_torsu([(1.47, zn * 34), (1.36, zn * 37), (1.22, zn * 42),
                                (1.08, zn * 52), (0.96, zn * 62)], otst)
        dobavit("lyamki", "lenta", lenta(put, nr, 0.046, 0.007))
        # подложка под лямкой — двойная лента, как на настоящих системах
        if zn < 0:
            metka("lyamki", 12, *poverh(1.19, zn * 44, otst + 0.006))

        # замки КЗУ: три кольца, большое внизу
        p0, n0 = poverh(1.47, zn * 34, otst + 0.008)
        vverh = norm(np.array([0, 1, 0]) - n0 * n0[1])
        for k, (R, r) in enumerate(((0.021, 0.0042), (0.014, 0.0035), (0.009, 0.003))):
            c = p0 + vverh * (0.0 + k * 0.022) + n0 * (0.004 * k)
            dobavit("kzu", "metall", tor(R, r, 32, 8).preobr(matr(c, bazis(n0))))
        if zn > 0:
            metka("kzu", 8, p0 + vverh * 0.02 + n0 * 0.01, n0)

        # свободные концы: от колец через плечо назад к ранцу, под клапанами
        konc = gladko([p0 + vverh * 0.05 + n0 * 0.006, [zn * 0.125, 1.585, 0.045],
                       [zn * 0.125, 1.615, -0.03], [zn * 0.12, 1.575, -0.12],
                       [zn * 0.115, 1.50, -0.165]], 40)
        nk = norm(np.vstack([n0, [0, 1, 0.4], [0, 1, 0], [0, 1, -0.6], [0, 0.3, -1]]))
        nk = norm(gladko(nk, 40))
        dobavit("konci", "lenta", lenta(konc, nk, 0.044, 0.012))
        # клапан свободных концов: шире и толще, на верхней части плеча
        kl_put = konc[14:]
        dobavit("konci", "ranec", lenta(kl_put + nk[14:] * 0.012, nk[14:], 0.07, 0.016))
        dobavit("konci", "akcent", lenta(kl_put[:3] + nk[14:17] * 0.012, nk[14:17], 0.072, 0.017))
        if zn > 0:
            metka("konci", 7, kl_put[6] + nk[20] * 0.03, nk[20])

        # транзит — на правом свободном конце, тянется к клапану запасного
        if zn < 0:
            sm = norm(np.cross(np.gradient(konc, axis=0), nk))
            tr = konc[3:] + nk[3:] * 0.016 + sm[3:] * 0.026
            tr = np.vstack([tr, [[-0.07, 1.505, -0.17], [-0.03, 1.50, -0.175]]])
            tr = gladko(tr[::3], 40)
            ntr = norm(gladko(np.vstack([nk[3::3], [[0, 0.5, -1], [0, 0.5, -1]]]), 40))
            dobavit("tranzit", "krasnyy", lenta(tr, ntr, 0.016, 0.005))
            dobavit("tranzit", "metall", okrugl_korobka((0.018, 0.03, 0.008), 0.003).preobr(
                matr(tr[2] + ntr[2] * 0.004, bazis(ntr[2]))))
            metka("tranzit", 9, tr[12] + ntr[12] * 0.01, ntr[12])

        # кольцо на бедре, куда сходятся лямка, обхват и боковая лента
        pb, nb = poverh(0.955, zn * 62, otst + 0.006)
        dobavit("lyamki", "metall", tor(0.02, 0.005, 28, 8).preobr(matr(pb, bazis(nb))))

        # боковые ленты: от кольца на бедре вокруг пояса к низу ранца
        bok, nbk = put_po_torsu([(0.955, zn * 64), (0.95, zn * 95), (0.95, zn * 130),
                                 (0.96, zn * 150)], otst)
        dobavit("lyamki", "lenta", lenta(bok, nbk, 0.04, 0.007))

        # ножной обхват: петля вокруг бедра, высоко спереди-снаружи, низко сзади-изнутри
        cb = np.array([zn * 0.088, 0.0, 0.015])
        rb = 0.096
        f0 = math.atan2(0.9, zn * 0.45)  # направление «спереди-снаружи» в плоскости xz
        pts, nrs = [], []
        for k in range(64):
            f = 2 * math.pi * k / 64
            d = np.array([math.cos(f), 0, math.sin(f)])
            y = 0.79 + 0.055 * math.cos(f - f0)
            pts.append(cb + d * rb + [0, y, 0])
            nrs.append(d)
        dobavit("obhvaty", "lenta", lenta(np.array(pts), np.array(nrs), 0.04, 0.007, zamk=True))
        # ход от кольца на бедре к петле и пряжка обхвата
        k0 = int(round((f0 % (2 * math.pi)) / (2 * math.pi) * 64)) % 64
        vhod = gladko([pb, (pb + pts[k0]) / 2 + nb * 0.01, pts[k0]], 14)
        dobavit("obhvaty", "lenta", lenta(vhod, np.tile(nb, (len(vhod), 1)), 0.04, 0.007))
        pr = pts[(k0 + zn * 6) % 64]
        npr = nrs[(k0 + zn * 6) % 64]
        dobavit("obhvaty", "metall", okrugl_korobka((0.05, 0.026, 0.008), 0.004).preobr(
            matr(np.array(pr) + np.array(npr) * 0.007, bazis(npr))))
        if zn > 0:
            metka("obhvaty", 14, np.array(pr) + np.array(npr) * 0.012, npr)

    # 13. Грудная перемычка с пряжкой и хвостом
    gr, ngr = put_po_torsu([(1.30, -40), (1.30, -15), (1.30, 0), (1.30, 15), (1.30, 40)], otst + 0.007, 40)
    dobavit("grudnaya", "lenta", lenta(gr, ngr, 0.04, 0.006))
    pg, ng = poverh(1.30, 24, otst + 0.012)
    dobavit("grudnaya", "metall", okrugl_korobka((0.03, 0.05, 0.008), 0.004).preobr(matr(pg, bazis(ng))))
    hv, nhv = put_po_torsu([(1.30, 27), (1.295, 31), (1.285, 34)], otst + 0.014, 8)
    dobavit("grudnaya", "lenta", lenta(hv, nhv, 0.034, 0.004))
    metka("grudnaya", 13, poverh(1.30, 6, otst + 0.012)[0], ng * [-1, 1, 1])

    # 10. Подушка отцепки — правая лямка, уровень живота, красная
    pp, npp = poverh(1.12, -50, otst + 0.018)
    dobavit("podushka", "krasnyy", okrugl_korobka((0.07, 0.048, 0.022), 0.01).preobr(
        matr(pp, bazis(npp))))
    metka("podushka", 10, pp + npp * 0.012, npp)

    # 11. Кольцо ПЗ — левая лямка, уровень живота: кармашек и металлическая ручка
    pk, nk_ = poverh(1.12, 50, otst + 0.012)
    b = bazis(nk_)
    dobavit("kolco_pz", "lenta", okrugl_korobka((0.05, 0.06, 0.012), 0.005).preobr(matr(pk, b)))
    ruchka = tor(0.024, 0.0055, 30, 10, dolya=0.62).preobr(
        matr((0, 0, 0), np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]]) @ rot_y(math.radians(0))))
    ruchka = ruchka.preobr(matr((-0.004, 0, 0)))
    dobavit("kolco_pz", "metall", ruchka.preobr(matr(pk + nk_ * 0.012, b @ bazis([0, 0.55, 1]))))
    metka("kolco_pz", 11, pk + nk_ * 0.03, nk_)

    return detali, sorted(metki, key=lambda m: m["n"])


# ---------- Запись GLB ----------

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


def main():
    detali, metki = postroit()
    zapisat_glb(detali, VYHOD)
    tri = sum(len(s.i) // 3 for d in detali.values() for s in d.values())
    METKI.parent.mkdir(parents=True, exist_ok=True)
    METKI.write_text("// Сгенерировано model/postroit-model.py — руками не править.\n"
                     "// kl — ключ детали (имя узла в GLB), n — номер метки, p — точка, nr — нормаль.\n"
                     "export const METKI = " + json.dumps(metki, ensure_ascii=False) + ";\n",
                     encoding="utf-8")
    print(f"{VYHOD.name}: {VYHOD.stat().st_size // 1024} КБ, {tri} треугольников, "
          f"{len(detali)} деталей, {len(metki)} меток")


if __name__ == "__main__":
    main()
