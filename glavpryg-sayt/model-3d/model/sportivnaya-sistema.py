#!/usr/bin/env python3
"""Спортивная парашютная система на манекене → `sportivnaya-sistema.glb`.

Детали и номера меток — по `../ustroystvo-sportivnoy-sistemy.md`, раздел 2;
внешний вид — по фотографиям системы заказчика (ранец Aerodyne Icon), 22.10.2026.

    /usr/bin/python3 sportivnaya-sistema.py
"""
import math

import numpy as np

from osnova import (KOLCO_Y, OBHVAT_NAKLON, OBHVAT_Y, Rakovina, Sborka, bazis, bedro, cilindr, gladko, lenta, matr, norm, okrugl_korobka,
                    poverh, put_po_torsu, tor, vypustit)


def postroit():
    sb = Sborka()
    dobavit, metka = sb.dobavit, sb.metka

    # Ранец — по фотографиям заказчика (Aerodyne Icon): одна обтекаемая чёрная «раковина»
    # от лопаток до поясницы, сверху запасной, снизу основной; по центру бежевая вставка
    # клином вниз, клапаны основного сходятся крест-накрест к чеке внизу.
    rak = Rakovina(
        [(0.0, 0.875), (0.075, 0.88), (0.125, 0.905), (0.152, 0.96), (0.163, 1.08),
         (0.172, 1.25), (0.176, 1.40), (0.168, 1.50), (0.14, 1.555), (0.085, 1.575)],
        centr=(0.0, 1.22), tolsh=([0.86, 0.95, 1.15, 1.40, 1.58], [0.10, 0.15, 0.165, 0.14, 0.10]))
    verh_s, niz_s = rak.razrezat(rak.setka(), 1.29)
    dobavit("zap_otsek", "chernyy", verh_s)
    dobavit("osn_otsek", "chernyy", niz_s)

    # бежевая вставка: широкая у верха, клин сходится к середине ранца
    dobavit("zap_otsek", "bezh", rak.naklejka(lambda a, v: (a * 0.085 * (1 - v) ** 1.15, 1.545 - 0.30 * v), 0.0025))
    # нижний бежевый клин между клапанами основного
    dobavit("osn_otsek", "bezh", rak.naklejka(lambda a, v: (a * 0.05 * (1 - v), 1.17 - 0.16 * v), 0.0025))
    # кант по краю раковины
    kr = [rak.tochka(*xy, s_=0.985)[0] for xy in rak.kontur(80)]
    nkr = [rak.tochka(*xy, s_=0.985)[1] for xy in rak.kontur(80)]
    dobavit("osn_otsek", "kant", lenta(np.array(kr), np.array(nkr), 0.012, 0.004, zamk=True))
    metka("zap_otsek", 4, rak.tochka(0.12, 1.40)[0] + [0, 0, -0.01], rak.tochka(0.12, 1.40)[1])
    metka("osn_otsek", 1, rak.tochka(0.12, 1.06)[0] + [0, 0, -0.01], rak.tochka(0.12, 1.06)[1])

    # 2. Клапаны основного: боковые сходятся крест-накрест к чеке внизу по центру,
    #    под ними язык с петлёй; чека прикрыта клапаном
    chek = np.array([0.0, 0.985])
    for zn in (-1, 1):
        sh = rak.po_poverhnosti([(zn * 0.15, 1.25), (zn * 0.09, 1.13), (zn * 0.03, 1.02), chek + [-zn * 0.03, -0.02]], 0.004)
        dobavit("klapan_osn", "kant", lenta(*sh, 0.012, 0.005))
    yaz = rak.naklejka(lambda a, v: (a * 0.035, 0.975 - 0.07 * v), 0.006)
    dobavit("klapan_osn", "chernyy", yaz)
    pc, nc = rak.tochka(*chek, otstup=0.008)
    dobavit("klapan_osn", "belyy", tor(0.009, 0.0022, 20, 6).preobr(matr(pc + [0, 0.006, 0], bazis([1, 0, 0]))))
    dobavit("klapan_osn", "metall", cilindr(0.003, 0.03, 10).preobr(matr(pc + nc * 0.003 + [0.006, 0, 0], bazis([1, 0, 0]))))
    metka("klapan_osn", 2, pc + nc * 0.01, nc)

    # 3. Бобышка медузы — жёлтая, внизу ранца справа, торчит из кармана на нижнем крае
    pb_, nb_ = rak.tochka(-0.115, 0.905, s_=0.97)
    bob_p = pb_ + np.array([-0.025, -0.012, 0.0])
    dobavit("bobyshka", "chernyy", okrugl_korobka((0.09, 0.03, 0.05), 0.012).preobr(matr(pb_ + [0.01, 0.01, 0.012])))
    dobavit("bobyshka", "zheltyy", okrugl_korobka((0.055, 0.028, 0.03), 0.012).preobr(
        matr(bob_p, bazis([0, 0, 1], verh=[1, 0.4, 0]))))
    metka("bobyshka", 3, bob_p + [-0.03, -0.005, 0], (-1, -0.4, -0.5))

    # 5. Клапан запасного — полукруглый клапан у верхнего края, под ним шпилька и петля
    pz, nz = rak.tochka(0.0, 1.535, otstup=0.006)
    kl_z = rak.naklejka(lambda a, v: (a * 0.045 * math.sqrt(max(0.0, 1 - v * v)), 1.565 - 0.075 * v), 0.009)
    dobavit("klapan_zap", "chernyy", kl_z)
    dobavit("klapan_zap", "metall", tor(0.006, 0.0018, 16, 6).preobr(matr(pz + nz * 0.006 + [0, -0.035, 0], bazis(nz))))
    metka("klapan_zap", 5, pz + nz * 0.012 + [0, -0.02, 0], nz + [0, 0.5, 0])

    # 6. Страхующий прибор: блок управления под клапаном запасного (на фото не виден — место условное)
    pp_, np_ = rak.tochka(0.0, 1.43, otstup=0.004)
    dobavit("pribor", "pribor", okrugl_korobka((0.05, 0.03, 0.012), 0.005).preobr(matr(pp_, bazis(np_))))
    dobavit("pribor", "ekran", okrugl_korobka((0.026, 0.012, 0.004), 0.002).preobr(matr(pp_ + np_ * 0.007, bazis(np_))))
    metka("pribor", 6, pp_ + np_ * 0.012, np_)

    # Главные лямки: от замков КЗУ на ключицах вниз к бёдрам
    otst = 0.008
    for zn, storona in ((-1, "prav"), (1, "lev")):
        put, nr = put_po_torsu([(1.47, zn * 34), (1.36, zn * 37), (1.22, zn * 42),
                                (1.08, zn * 52), (KOLCO_Y + 0.005, zn * 62)], otst)
        dobavit("lyamki", "lenta", lenta(put, nr, 0.046, 0.007))
        # подложка под лямкой — двойная лента, как на настоящих системах
        if zn < 0:
            metka("lyamki", 12, *poverh(1.06, zn * 50, otst + 0.006))

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
        dobavit("konci", "siniy", lenta(konc, nk, 0.044, 0.012))
        # клапан свободных концов: шире и толще, на верхней части плеча
        kl_put = konc[14:]
        dobavit("konci", "chernyy", lenta(kl_put + nk[14:] * 0.012, nk[14:], 0.07, 0.016))
        dobavit("konci", "siniy", lenta(kl_put[:3] + nk[14:17] * 0.012, nk[14:17], 0.072, 0.017))
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
        pb, nb = poverh(KOLCO_Y, zn * 62, otst + 0.006)
        dobavit("lyamki", "metall", tor(0.02, 0.005, 28, 8).preobr(matr(pb, bazis(nb))))

        # боковые ленты: от кольца на бедре вокруг пояса к низу ранца
        bok, nbk = put_po_torsu([(KOLCO_Y, zn * 64), (0.905, zn * 95), (0.935, zn * 130),
                                 (0.96, zn * 150)], otst)
        dobavit("lyamki", "lenta", lenta(bok, nbk, 0.04, 0.007))

        # ножной обхват: петля вокруг бедра, высоко спереди-снаружи, низко сзади-изнутри
        f0 = math.atan2(0.9, zn * 0.45)  # направление «спереди-снаружи» в плоскости xz
        pts, nrs = [], []
        for k in range(64):
            f = 2 * math.pi * k / 64
            d = np.array([math.cos(f), 0, math.sin(f)])
            cb, rb = bedro(zn, OBHVAT_Y + OBHVAT_NAKLON * math.cos(f - f0))
            pts.append(cb + d * (rb + 0.0065))
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

    # Плечевые накладки: мягкие чёрные подушки на лямках от колец КЗУ до груди
    for zn in (-1, 1):
        nak, nnak = put_po_torsu([(1.445, zn * 34.5), (1.40, zn * 35.5), (1.34, zn * 37.5), (1.285, zn * 40)], otst + 0.008, 24)
        dobavit("lyamki", "chernyy", lenta(nak, nnak, 0.07, 0.016))

    # 10. Подушка отцепки — правая лямка, сразу под грудной перемычкой, красная, вытянута вниз
    pp, npp = poverh(1.215, -45, otst + 0.02)
    dobavit("podushka", "krasnyy", okrugl_korobka((0.045, 0.075, 0.026), 0.012).preobr(
        matr(pp, bazis(npp))))
    metka("podushka", 10, pp + npp * 0.014, npp)

    # 11. Ручка запасного — левая лямка, на той же высоте: синяя мягкая подушка
    pk, nk_ = poverh(1.215, 45, otst + 0.018)
    dobavit("kolco_pz", "siniy", okrugl_korobka((0.04, 0.06, 0.022), 0.011).preobr(matr(pk, bazis(nk_))))
    dobavit("kolco_pz", "metall", cilindr(0.0025, 0.03, 8).preobr(matr(pk + [0, 0.035, -0.004], bazis([0, 1, 0], verh=[0, 0, 1]))))
    metka("kolco_pz", 11, pk + nk_ * 0.014, nk_)

    return sb


if __name__ == "__main__":
    vypustit(postroit(), "sportivnaya-sistema")
