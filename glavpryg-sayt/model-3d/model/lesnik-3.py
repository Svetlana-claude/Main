#!/usr/bin/env python3
"""ПСсН «Лесник-3» на манекене → `lesnik-3.glb`.

Устройство — по своду `../../lesnik-3/ustroystvo-lesnik-3.md` (ТО 216-01ТО, рис. 1.13
и 1.14): ранец с **верхним** отсеком основного и **нижним** запасного, двухконусный
замок на спинке, стабилизирующий парашют в камере, ППК-У в кармане справа; кольцо ОП
на левой лямке, кольцо ЗПС и звено отсоединения — на правой. Передние лямки сверху
переходят в свободные концы запасного. Внешний вид — по фотографиям системы
заказчика (22.10.2026): синий ранец, серая камера стабилизатора сверху, синие лямки.

    /usr/bin/python3 lesnik-3.py
"""
import math

import numpy as np

from osnova import (KOLCO_Y, Rakovina, Sborka, bazis, cilindr, gladko, lenta, matr, norm, obhvat_bedra,
                    okrugl_korobka, poverh, put_po_torsu, ramka, tor, trubka, vypustit)

OTST = 0.008  # лямки над поверхностью торса


def postroit():
    sb = Sborka()
    dobavit, metka = sb.dobavit, sb.metka
    # ---------- Ранец ----------
    # По фотографиям заказчика: один объёмный синий ранец от плеч до ягодиц, по спине —
    # узор из чёрных лент «песочными часами»; сверху основной (1), снизу запасной (4)
    rak = Rakovina(
        [(0.0, 0.815), (0.09, 0.82), (0.155, 0.845), (0.19, 0.90), (0.203, 1.05), (0.205, 1.30),
         (0.198, 1.48), (0.178, 1.565), (0.13, 1.605), (0.06, 1.615)],
        centr=(0.0, 1.22), tolsh=([0.80, 0.90, 1.10, 1.35, 1.62], [0.13, 0.20, 0.225, 0.21, 0.15]),
        q=2.6, prileganie=0.85)
    verh_s, niz_s = rak.razrezat(rak.setka(72, 14), 1.17)
    dobavit("osn_otsek", "siniy_les", verh_s)
    dobavit("zap_otsek", "siniy_les", niz_s)
    kr = [rak.tochka(*xy, s_=0.985) for xy in rak.kontur(90)]
    dobavit("osn_otsek", "lenta", lenta(np.array([t[0] for t in kr]), np.array([t[1] for t in kr]), 0.014, 0.004, zamk=True))
    # чёрные ленты по спине: от верхних углов к «талии», перемычки, к нижним углам
    for zn in (-1, 1):
        for oporы in ([(zn * 0.175, 1.545), (zn * 0.10, 1.33), (zn * 0.06, 1.10), (zn * 0.175, 0.86)],):
            dobavit("osn_otsek", "lenta", lenta(*rak.po_poverhnosti(oporы, 0.004, 40), 0.022, 0.005))
    for y, x in ((1.33, 0.10), (1.10, 0.06), (1.545, 0.15)):
        dobavit("osn_otsek", "lenta", lenta(*rak.po_poverhnosti([(-x, y), (0, y), (x, y)], 0.004, 12), 0.022, 0.005))
    # чёрный карман справа вверху спины
    dobavit("osn_otsek", "chernyy", rak.naklejka(lambda a, v: (-0.11 + a * 0.06, 1.52 - 0.20 * v), 0.012))
    metka("osn_otsek", 1, *rak.tochka(0.12, 1.43, otstup=0.01))
    metka("zap_otsek", 4, *rak.tochka(0.12, 0.97, otstup=0.01))
    # шпилька запасного с кольцом контровки — внизу по центру
    pzs, nzs = rak.tochka(0.0, 0.95, otstup=0.006)
    dobavit("zap_otsek", "metall", tor(0.008, 0.002, 18, 6).preobr(matr(pzs, bazis(nzs))))

    # 2. Двухконусный замок: пластина жёсткости с окнами на верху спинки, под камерой стабилизатора
    pz_, nz_ = rak.tochka(0.0, 1.535, otstup=0.006)
    bz_ = bazis(nz_)
    dobavit("zamok", "metall", okrugl_korobka((0.16, 0.045, 0.008), 0.006).preobr(matr(pz_, bz_)))
    for x in (-0.045, 0.045):
        dobavit("zamok", "metall", cilindr(0.012, 0.022, 16).preobr(
            matr(pz_ + nz_ * 0.012 + [x, 0, 0], bazis([0, 1, 0], verh=[0, 0, 1]))))
    dobavit("zamok", "chernyy", okrugl_korobka((0.05, 0.03, 0.014), 0.006).preobr(matr(pz_ + nz_ * 0.008, bz_)))
    metka("zamok", 2, pz_ + nz_ * 0.025 + [0.07, 0, 0], nz_)
    zamok_t = pz_ + nz_ * 0.01

    # 3. Стабилизирующий парашют: серая камера-валик поперёк верха ранца, справа из неё
    #    выглядывает оранжевый купол; сверху лента с карабином
    # лежит на скруглённом верху ранца, над серединой его толщины
    kam_c = np.array([0.0, 1.625, rak.spina(0.0, 1.60) - 0.5 * rak.tolshchina(1.60)])
    dobavit("stabilizator", "seryy", okrugl_korobka((0.30, 0.095, 0.13), 0.045).preobr(matr(kam_c)))
    dobavit("stabilizator", "akcent", okrugl_korobka((0.06, 0.08, 0.11), 0.035).preobr(matr(kam_c + [-0.17, -0.005, 0])))
    dobavit("stabilizator", "lenta", okrugl_korobka((0.03, 0.10, 0.135), 0.006).preobr(matr(kam_c + [0.0, 0.003, 0])))
    karabin = tor(0.024, 0.0048, 28, 8, dolya=0.85).preobr(matr((0, 0, 0), bazis([0, 1, 0], verh=[0, 0, 1])))
    dobavit("stabilizator", "metall", karabin.preobr(matr(kam_c + [0.08, 0.05, -0.03])))
    zveno = gladko([kam_c + [0.06, 0.045, -0.05], kam_c + [0.02, -0.02, -0.075], zamok_t + [0, 0.02, 0]], 12)
    dobavit("stabilizator", "lenta", lenta(zveno, np.tile([0, 0.3, -1], (len(zveno), 1)), 0.022, 0.004))
    metka("stabilizator", 3, kam_c + [0.04, 0.045, -0.04], (0, 1, -0.6))

    # 5. ППК-У-240АД в кармане на правой стороне ранца (на фото — ниже середины), шланг к замку
    pb_, nb_ = rak.tochka(-0.20, 1.12, s_=0.995)
    karman = pb_ + nb_ * 0.025
    dobavit("ppku", "chernyy", okrugl_korobka((0.035, 0.15, 0.07), 0.014).preobr(matr(karman)))
    dobavit("ppku", "pribor", cilindr(0.013, 0.025, 14).preobr(matr(karman + [0, 0.088, 0])))
    shl = gladko([karman + [0, 0.10, 0], karman + [-0.005, 0.25, 0.0], karman + [0.0, 0.40, -0.02],
                  rak.tochka(-0.15, 1.585, otstup=0.01)[0], zamok_t + [-0.06, 0, 0]], 40)
    dobavit("ppku", "shlang", trubka(shl, 0.006))
    metka("ppku", 5, karman + [-0.04, 0, 0], (-1, 0, -0.2))
    zad_osn = zamok_t[2]
    zamok_y = zamok_t[1]

    # ---------- Подвесная система ----------
    for zn in (-1, 1):
        # 11. Передняя лямка: от бедра вверх, через плечо — свободный конец запасного
        put, nr = put_po_torsu([(KOLCO_Y + 0.005, zn * 62), (1.08, zn * 52), (1.22, zn * 42),
                                (1.36, zn * 37), (1.50, zn * 33)], OTST)
        dobavit("lyamki", "siniy_les", lenta(put, nr, 0.075, 0.016))
        put2, nr2 = put_po_torsu([(KOLCO_Y + 0.005, zn * 62), (1.08, zn * 52), (1.22, zn * 42),
                                  (1.36, zn * 37), (1.50, zn * 33)], OTST + 0.016)
        dobavit("lyamki", "lenta", lenta(put2, nr2, 0.04, 0.006))
        p_verh, n_verh = put[-1], nr[-1]
        cherez = gladko([p_verh, [zn * 0.11, 1.59, 0.05], [zn * 0.115, 1.63, -0.03],
                         [zn * 0.14, 1.59, -0.12], [zn * 0.175, 1.48, -0.17], [zn * 0.19, 1.25, -0.19],
                         [zn * 0.19, 1.13, -0.18]], 50)
        nch = norm(gladko(np.array([n_verh, [0, 1, 0.5], [0, 1, 0], [0, 0.7, -0.7], [zn * 0.3, 0.2, -1],
                                    [zn * 0.5, 0, -1], [zn * 0.5, 0, -1]]), 50))
        dobavit("lyamki", "lenta", lenta(cherez, nch, 0.046, 0.009))
        if zn < 0:
            metka("lyamki", 11, cherez[16] + nch[16] * 0.012, nch[16])

        # кольцо на бедре, поясной притяг, ножной обхват
        pb, nb = poverh(KOLCO_Y, zn * 62, OTST + 0.006)
        dobavit("lyamki", "metall", tor(0.02, 0.005, 28, 8).preobr(matr(pb, bazis(nb))))
        bok, nbk = put_po_torsu([(KOLCO_Y, zn * 64), (0.905, zn * 95), (0.935, zn * 130), (0.96, zn * 150)], OTST)
        dobavit("lyamki", "lenta", lenta(bok, nbk, 0.04, 0.007))
        obh, pr, npr = obhvat_bedra(zn, pb, nb)
        dobavit("obhvaty", "lenta", obh)
        # мягкая синяя подкладка обхвата
        dobavit("obhvaty", "siniy_les", obhvat_bedra(zn, pb, nb, shir=0.056, tol=0.003)[0])
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
        dobavit("konci_osn", "lenta", lenta(konc, nk, 0.05, 0.014))
        if zn > 0:
            metka("konci_osn", 6, pd + vverh * 0.035 + nd * 0.02, nd)

    # 7. Кольцо ОП — большое металлическое кольцо-«капля» на левой лямке у грудной перемычки
    #    (по фото заказчика: кольцо у внутреннего края лямки, над перемычкой); шланг к замку через плечо
    pk, nkk = poverh(1.30, 27, OTST + 0.03)
    b = bazis(nkk)
    kap = []
    for k in range(49):
        f = 2 * math.pi * k / 48
        # овал 6,4 × 7,6 см, наружный (к лямке) бок спрямлён — как у вытяжного кольца
        x, y = math.cos(f) * 0.032, math.sin(f) * 0.038
        kap.append([min(x, 0.022), y, 0])
    kap = gladko(kap, 72)
    dobavit("kolco_op", "metall", trubka(kap, 0.0045).preobr(matr(pk, b)))
    # малый карабин с красной чекой, которым кольцо держится на лямке
    zv = [[0.03 + math.cos(2 * math.pi * k / 24) * 0.009, 0.012 + math.sin(2 * math.pi * k / 24) * 0.016, 0]
          for k in range(25)]
    dobavit("kolco_op", "metall", trubka(gladko(zv, 36), 0.0028).preobr(matr(pk, b)))
    dobavit("kolco_op", "krasnyy", cilindr(0.0025, 0.03, 8).preobr(matr(pk + b[:, 0] * 0.042 + b[:, 1] * 0.012, b)))
    shl_op = [pk + b[:, 1] * 0.038 + nkk * 0.004]
    for y, u in ((1.38, 33), (1.48, 34)):
        shl_op.append(poverh(y, u, OTST + 0.02)[0])
    shl_op += [[0.15, 1.61, 0.03], [0.15, 1.64, -0.05], [0.13, 1.56, -0.16], [0.05, zamok_y + 0.01, zad_osn - 0.02]]
    dobavit("kolco_op", "shlang", trubka(gladko(shl_op, 50), 0.006))
    metka("kolco_op", 7, pk - b[:, 0] * 0.032 + nkk * 0.01, nkk)

    # 10. Рация — носимая (на фото Kenwood) в чёрном чехле на левой лямке, над кольцом ОП, снаружи
    pn, nn = poverh(1.39, 50, OTST + 0.03)
    bn = bazis(nn)
    dobavit("raciya", "chernyy", okrugl_korobka((0.062, 0.12, 0.034), 0.008).preobr(matr(pn, bn)))
    # лицевая панель рации в окне чехла и короткая антенна сверху
    dobavit("raciya", "pribor", okrugl_korobka((0.046, 0.075, 0.006), 0.004).preobr(
        matr(pn + nn * 0.016 + [0, -0.01, 0], bn)))
    dobavit("raciya", "chernyy", cilindr(0.006, 0.05, 12).preobr(
        matr(pn + [0, 0.083, 0] - bn[:, 0] * 0.016, np.eye(3))))
    metka("raciya", 10, pn + nn * 0.03 + [0, 0.02, 0], nn)

    # 8. Кольцо ЗПС — по фото заказчика: синий карман с окном на правой лямке над грудной
    #    перемычкой, из его внутреннего края торчит высокая прямоугольная рамка, внизу — красное кольцо
    pkz, nkz = poverh(1.37, -40, OTST + 0.022)
    dobavit("kolco_zps", "siniy_les", okrugl_korobka((0.06, 0.13, 0.014), 0.006).preobr(matr(pkz, bazis(nkz))))
    dobavit("kolco_zps", "pribor", okrugl_korobka((0.04, 0.05, 0.004), 0.003).preobr(
        matr(pkz + nkz * 0.007 + [0, -0.02, 0], bazis(nkz))))
    pz, nz = poverh(1.355, -29, OTST + 0.03)
    # рамка стоит ребром: плоскость развёрнута к середине груди
    nz_r = norm(nz + np.array([1.8, 0, 0]))
    bz = bazis(nz_r)
    dobavit("kolco_zps", "metall", ramka(0.03, 0.085, 0.008, 0.0055).preobr(matr(pz, bz)))
    dobavit("kolco_zps", "krasnyy", tor(0.011, 0.004, 20, 8).preobr(
        matr(pz + [0, -0.05, 0.004], bazis(norm(nz + np.array([-0.4, 0, 0]))))))
    metka("kolco_zps", 8, pz + nz * 0.012 + [0, 0.02, 0], nz)

    # 9. Звено отсоединения — правая лямка над кольцом ЗПС: основа на застёжке, ручка-втулка,
    #    два троса в боуденах к D-пряжкам (короткий — к правой, длинный — через грудь к левой)
    po, no = poverh(1.19, -44, OTST + 0.014)
    bo = bazis(no)
    dobavit("zveno_otc", "chernyy", okrugl_korobka((0.05, 0.06, 0.012), 0.005).preobr(matr(po, bo)))
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

    # 12. Грудная перемычка — по фото заказчика: мягкая синяя подкладка, чёрная лента;
    #     посередине груди Т-образный крюк-карабин заходит в D-пряжку (пряжка правее, крюк левее)
    pod, npod = put_po_torsu([(1.265, -22), (1.265, 0), (1.265, 20), (1.265, 34)], OTST + 0.004, 40)
    dobavit("grudnaya", "siniy_les", lenta(pod, npod, 0.085, 0.012))
    gr, ngr = put_po_torsu([(1.27, -40), (1.27, -15), (1.27, 0), (1.27, 15), (1.27, 40)], OTST + 0.016, 40)
    dobavit("grudnaya", "lenta", lenta(gr, ngr, 0.045, 0.006))
    pg2, ng2 = poverh(1.27, -8, OTST + 0.023)
    dobavit("grudnaya", "metall", ramka(0.03, 0.05, 0.012, 0.006).preobr(matr(pg2, bazis(ng2))))
    pg, ng = poverh(1.27, 12, OTST + 0.024)
    bg = bazis(ng)
    # перекладина Т — поперёк ленты, стержень — к D-пряжке
    dobavit("grudnaya", "metall", okrugl_korobka((0.012, 0.055, 0.005), 0.0025).preobr(matr(pg, bg)))
    pc = (pg + pg2) / 2 + ng * 0.001
    dobavit("grudnaya", "metall", okrugl_korobka((float(np.linalg.norm(pg - pg2)), 0.014, 0.005), 0.0025).preobr(
        matr(pc, bazis(ng))))
    metka("grudnaya", 12, pg + ng * 0.012 + [0, 0.035, 0], ng)

    return sb


if __name__ == "__main__":
    vypustit(postroit(), "lesnik-3")
