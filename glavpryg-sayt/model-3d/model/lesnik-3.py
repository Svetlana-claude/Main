#!/usr/bin/env python3
"""ПСсН «Лесник-3» на манекене → `lesnik-3.glb`.

Устройство — по своду `../../lesnik-3/ustroystvo-lesnik-3.md` (ТО 216-01ТО, рис. 1.13
и 1.14): ранец с **верхним** отсеком основного и **нижним** запасного, двухконусный
замок на спинке, стабилизирующий парашют в камере, ППК-У в кармане справа; кольцо ОП
на левой лямке, кольцо ЗПС и звено отсоединения — на правой. Передние лямки сверху
переходят в свободные концы запасного. Цвета и формы клапанов условные — до фото.

    /usr/bin/python3 lesnik-3.py
"""
import math

import numpy as np

from osnova import (Sborka, bazis, cilindr, gladko, lenta, matr, norm, obhvat_bedra,
                    okrugl_korobka, poverh, put_po_torsu, ramka, tor, trubka, vypustit)

OTST = 0.008  # лямки над поверхностью торса


def postroit():
    sb = Sborka()
    dobavit, metka = sb.dobavit, sb.metka
    zs = -0.10  # спина торса

    # ---------- Ранец ----------
    # 1. верхний отсек — основной (в камере); 4. нижний — запасной (в чехле)
    osn_c = np.array([0, 1.355, zs - 0.105])
    dobavit("osn_otsek", "olivka", okrugl_korobka((0.36, 0.33, 0.21), 0.05).preobr(matr(osn_c)))
    dobavit("osn_otsek", "olivka", okrugl_korobka((0.39, 0.74, 0.03), 0.014).preobr(matr((0, 1.22, zs - 0.005))))
    zad_osn = osn_c[2] - 0.105
    metka("osn_otsek", 1, (-0.13, 1.42, zad_osn + 0.012), (-0.6, 0.2, -1))

    zap_c = np.array([0, 1.05, zs - 0.09])
    dobavit("zap_otsek", "olivka_t", okrugl_korobka((0.37, 0.27, 0.18), 0.05).preobr(matr(zap_c)))
    zad_zap = zap_c[2] - 0.09
    # клапаны нижнего отсека и кольцо контровки шпильки
    dobavit("zap_otsek", "olivka_t", okrugl_korobka((0.26, 0.11, 0.012), 0.006).preobr(
        matr((0, 1.04, zad_zap - 0.004))))
    dobavit("zap_otsek", "metall", tor(0.008, 0.002, 18, 6).preobr(matr((0, 1.09, zad_zap - 0.012))))
    metka("zap_otsek", 4, (0.12, 1.0, zad_zap + 0.01), (0.5, 0, -1))

    # 2. Двухконусный замок: пластина жёсткости с окнами вверху спинки и два конуса
    zamok_y = 1.47
    dobavit("zamok", "metall", okrugl_korobka((0.16, 0.05, 0.008), 0.006).preobr(
        matr((0, zamok_y, zad_osn - 0.004))))
    for x in (-0.045, 0.045):
        dobavit("zamok", "metall", cilindr(0.012, 0.022, 16).preobr(
            matr((x, zamok_y, zad_osn - 0.015), bazis([0, 1, 0], verh=[0, 0, 1]))))
    dobavit("zamok", "olivka_t", okrugl_korobka((0.05, 0.035, 0.014), 0.006).preobr(
        matr((0, zamok_y, zad_osn - 0.012))))
    metka("zamok", 2, (0.045, zamok_y, zad_osn - 0.03), (0, 0.1, -1))

    # 3. Стабилизирующий парашют в камере на спинке, карабин сверху
    kam_c = np.array([0, 1.33, zad_osn - 0.035])
    dobavit("stabilizator", "olivka_t", okrugl_korobka((0.22, 0.17, 0.06), 0.025).preobr(matr(kam_c)))
    dobavit("stabilizator", "akcent", okrugl_korobka((0.225, 0.012, 0.062), 0.005).preobr(
        matr(kam_c + [0, -0.06, 0])))
    karabin = tor(0.022, 0.0045, 28, 8, dolya=0.85).preobr(matr((0, 0, 0), bazis([1, 0, 0])))
    dobavit("stabilizator", "metall", karabin.preobr(matr(kam_c + [0.07, 0.1, -0.012])))
    # соединительное звено от камеры к силовому треугольнику у замка
    zveno = gladko([kam_c + [0.07, 0.085, -0.01], kam_c + [0.04, 0.12, -0.015], (0.0, zamok_y - 0.02, zad_osn - 0.02)], 12)
    dobavit("stabilizator", "lenta_ol", lenta(zveno, np.tile([0, 0, -1], (len(zveno), 1)), 0.022, 0.004))
    metka("stabilizator", 3, kam_c + [-0.05, 0, -0.035], (0, 0, -1))

    # 5. ППК-У-240АД в кармане на правой стороне ранца, шланг к замку
    bok_x = -0.18
    karman = np.array([bok_x - 0.012, 1.30, osn_c[2] - 0.02])
    dobavit("ppku", "olivka_t", okrugl_korobka((0.03, 0.15, 0.08), 0.012).preobr(matr(karman)))
    dobavit("ppku", "pribor", cilindr(0.012, 0.02, 14).preobr(matr(karman + [0, 0.085, 0])))
    shl = gladko([karman + [0, 0.09, 0], karman + [0.0, 0.15, -0.04], (-0.12, zamok_y + 0.03, zad_osn - 0.02),
                  (-0.06, zamok_y, zad_osn - 0.02)], 30)
    dobavit("ppku", "shlang", trubka(shl, 0.006))
    metka("ppku", 5, karman + [-0.02, 0, 0], (-1, 0, -0.2))

    # ---------- Подвесная система ----------
    for zn in (-1, 1):
        # 11. Передняя лямка: от бедра вверх, через плечо — свободный конец запасного
        put, nr = put_po_torsu([(0.96, zn * 62), (1.08, zn * 52), (1.22, zn * 42),
                                (1.36, zn * 37), (1.50, zn * 33)], OTST)
        dobavit("lyamki", "lenta_ol", lenta(put, nr, 0.046, 0.008))
        p_verh, n_verh = put[-1], nr[-1]
        cherez = gladko([p_verh, [zn * 0.11, 1.59, 0.05], [zn * 0.115, 1.63, -0.03],
                         [zn * 0.14, 1.59, -0.12], [zn * 0.175, 1.48, -0.17], [zn * 0.19, 1.25, -0.19],
                         [zn * 0.19, 1.13, -0.18]], 50)
        nch = norm(gladko(np.array([n_verh, [0, 1, 0.5], [0, 1, 0], [0, 0.7, -0.7], [zn * 0.3, 0.2, -1],
                                    [zn * 0.5, 0, -1], [zn * 0.5, 0, -1]]), 50))
        dobavit("lyamki", "lenta_ol", lenta(cherez, nch, 0.046, 0.009))
        if zn < 0:
            metka("lyamki", 11, cherez[16] + nch[16] * 0.012, nch[16])

        # кольцо на бедре, поясной притяг, ножной обхват
        pb, nb = poverh(0.955, zn * 62, OTST + 0.006)
        dobavit("lyamki", "metall", tor(0.02, 0.005, 28, 8).preobr(matr(pb, bazis(nb))))
        bok, nbk = put_po_torsu([(0.955, zn * 64), (0.95, zn * 95), (0.95, zn * 130), (0.96, zn * 150)], OTST)
        dobavit("lyamki", "lenta_ol", lenta(bok, nbk, 0.04, 0.007))
        obh, pr, npr = obhvat_bedra(zn, pb, nb)
        dobavit("obhvaty", "lenta_ol", obh)
        dobavit("obhvaty", "metall", okrugl_korobka((0.05, 0.026, 0.008), 0.004).preobr(
            matr(pr + npr * 0.007, bazis(npr))))
        if zn > 0:
            metka("obhvaty", 13, pr + npr * 0.012, npr)

        # 6. D-пряжка на лямке, на ней КЗУ и свободные концы основного — через плечо к верхнему отсеку
        pd, nd = poverh(1.40, zn * 36, OTST + 0.01)
        vverh = norm(np.array([0, 1, 0]) - nd * nd[1])
        D = tor(0.022, 0.005, 26, 8, dolya=0.55).preobr(matr((0, 0, 0), np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]])))
        dobavit("konci_osn", "metall", D.preobr(matr(pd, bazis(nd))))
        for k, (R, r) in enumerate(((0.017, 0.0038), (0.011, 0.003))):
            c = pd + vverh * (0.026 + k * 0.02) + nd * 0.006
            dobavit("konci_osn", "metall", tor(R, r, 26, 8).preobr(matr(c, bazis(nd))))
        konc = gladko([pd + vverh * 0.06 + nd * 0.012, [zn * 0.125, 1.60, 0.07], [zn * 0.13, 1.645, -0.02],
                       [zn * 0.115, 1.60, -0.13], [zn * 0.10, 1.53, -0.19]], 40)
        nk = norm(gladko(np.array([nd, [0, 1, 0.5], [0, 1, 0], [0, 0.6, -0.8], [0, 0.3, -1]]), 40))
        dobavit("konci_osn", "olivka", lenta(konc, nk, 0.05, 0.014))
        if zn > 0:
            metka("konci_osn", 6, pd + vverh * 0.035 + nd * 0.02, nd)

    # 7. Кольцо ОП — левая лямка: карман и металлическая рамка; шланг к замку через плечо
    pk, nkk = poverh(1.20, 47, OTST + 0.012)
    b = bazis(nkk)
    dobavit("kolco_op", "olivka_t", okrugl_korobka((0.055, 0.075, 0.014), 0.006).preobr(matr(pk, b)))
    dobavit("kolco_op", "metall", ramka(0.05, 0.034, 0.008, 0.006).preobr(matr(pk + nkk * 0.014, b)))
    shl_op = []
    for y, u in ((1.24, 47), (1.36, 41), (1.48, 36)):
        shl_op.append(poverh(y, u + 8, OTST + 0.02)[0])
    shl_op += [[0.15, 1.61, 0.03], [0.15, 1.64, -0.05], [0.13, 1.56, -0.16], [0.05, zamok_y + 0.01, zad_osn - 0.02]]
    dobavit("kolco_op", "shlang", trubka(gladko(shl_op, 50), 0.006))
    metka("kolco_op", 7, pk + nkk * 0.03, nkk)

    # 10. Нож-стропорез — карман над кольцом ОП, рукоять наружу
    pn, nn = poverh(1.31, 46, OTST + 0.014)
    dobavit("nozh", "olivka_t", okrugl_korobka((0.045, 0.06, 0.012), 0.005).preobr(matr(pn, bazis(nn))))
    dobavit("nozh", "akcent", okrugl_korobka((0.016, 0.04, 0.012), 0.006).preobr(
        matr(pn + nn * 0.01 + [0, 0.035, 0], bazis(nn))))
    metka("nozh", 10, pn + nn * 0.03 + [0, 0.02, 0], nn)

    # 8. Кольцо ЗПС — правая лямка: карман, рамка, трос со шпилькой уходит к нижнему отсеку
    pz, nz = poverh(1.20, -47, OTST + 0.012)
    bz = bazis(nz)
    dobavit("kolco_zps", "olivka_t", okrugl_korobka((0.055, 0.075, 0.014), 0.006).preobr(matr(pz, bz)))
    dobavit("kolco_zps", "metall", ramka(0.05, 0.034, 0.008, 0.006).preobr(matr(pz + nz * 0.014, bz)))
    dobavit("kolco_zps", "krasnyy", okrugl_korobka((0.03, 0.012, 0.008), 0.004).preobr(
        matr(pz + nz * 0.02 + [0, -0.012, 0], bz)))
    metka("kolco_zps", 8, pz + nz * 0.03, nz)

    # 9. Звено отсоединения — правая лямка над кольцом ЗПС: основа на застёжке, ручка-втулка,
    #    два троса в боуденах к D-пряжкам (короткий — к правой, длинный — через грудь к левой)
    po, no = poverh(1.31, -44, OTST + 0.014)
    bo = bazis(no)
    dobavit("zveno_otc", "olivka", okrugl_korobka((0.05, 0.06, 0.012), 0.005).preobr(matr(po, bo)))
    dobavit("zveno_otc", "krasnyy", cilindr(0.008, 0.045, 14).preobr(
        matr(po + no * 0.012, bo @ np.array([[0, 1, 0], [1, 0, 0], [0, 0, 1]]))))
    pd_l = poverh(1.40, 36, OTST + 0.02)[0]
    pd_p = poverh(1.40, -36, OTST + 0.02)[0]
    dobavit("zveno_otc", "shlang", trubka(gladko([po + no * 0.01 + [0, 0.03, 0], (po + pd_p) / 2 + no * 0.012, pd_p], 16), 0.004))
    grud = [po + no * 0.01 + [0.01, 0.03, 0]]
    for u in (-30, -10, 10, 30):
        grud.append(poverh(1.385, u, OTST + 0.016)[0])
    grud.append(pd_l)
    dobavit("zveno_otc", "shlang", trubka(gladko(grud, 40), 0.004))
    metka("zveno_otc", 9, po + no * 0.03, no)

    # 12. Грудная перемычка: карабин слева, пряжка справа
    gr, ngr = put_po_torsu([(1.27, -40), (1.27, -15), (1.27, 0), (1.27, 15), (1.27, 40)], OTST + 0.007, 40)
    dobavit("grudnaya", "lenta_ol", lenta(gr, ngr, 0.04, 0.006))
    pg, ng = poverh(1.27, 30, OTST + 0.014)
    dobavit("grudnaya", "metall", tor(0.02, 0.0045, 26, 8, dolya=0.9).preobr(matr(pg, bazis(ng))))
    pg2, ng2 = poverh(1.27, -30, OTST + 0.012)
    dobavit("grudnaya", "metall", okrugl_korobka((0.03, 0.045, 0.008), 0.004).preobr(matr(pg2, bazis(ng2))))
    metka("grudnaya", 12, poverh(1.27, 8, OTST + 0.012)[0], poverh(1.27, 8)[1])

    return sb


if __name__ == "__main__":
    vypustit(postroit(), "lesnik-3")
