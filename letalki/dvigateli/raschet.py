"""Оценочный расчёт «33» с разными силовыми установками.

Планер, взлётная масса и аэродинамика — общие для всех вариантов.
Аэродинамика подогнана под заявленную в справке дальность электрической
версии (800 км на 95 км/ч), поэтому все дальности — относительно неё:
не подтвердят испытания 800 км — остальные цифры снижаются в той же доле.
Запуск: python3 raschet.py  (печатает таблицу и пишет raschet.json рядом)
"""
import json
import math
from pathlib import Path

G = 9.81
RO0 = 1.225                      # плотность воздуха у земли, кг/м³
S = 1.10                         # площадь крыла, м² (из скорости сваливания 59 км/ч, Cy max ≈ 1,3)
RAZMAH = 3.2                     # размах, м (габарит 3200)
K_IND = 1 / (math.pi * 0.85 * RAZMAH ** 2 / S)   # индуктивная составляющая
M_VZL = 24.0                     # максимальная взлётная масса, кг
M_PLANER = 8.5                   # планер, бортовое оборудование, парашют — без двигателя и энергии
M_NAGR = 1.5                     # целевая нагрузка по справке
V_KREYS = 95 / 3.6               # экономическая скорость из справки, м/с

# Электрическая цепочка: аккумулятор Li-ion ≈ 230 Вт·ч/кг, используется 90 %,
# двигатель с регулятором 0,88, винт 0,75
EL_UDEL, EL_ISP, EL_MOTOR, VINT = 230, 0.90, 0.88, 0.75
BORT = 0.0                       # питание борта и нагрузки не учтено — как в справке, у всех одинаково
GENERATOR = 0.75                 # КПД генератора с выпрямителем у ДВС


def Soprotivlenie(m, v, cx0):
    q = RO0 * v * v / 2
    return q * S * cx0 + K_IND * (m * G) ** 2 / (q * S)


def Cx0PoSpravke():
    """Подбирает вредное сопротивление так, чтобы электричка давала 800 км."""
    m_akb = M_VZL - M_PLANER - M_NAGR - 1.0
    energiya = m_akb * EL_UDEL * EL_ISP * 3600 * EL_MOTOR * VINT   # Дж на винте
    lo, hi = 0.001, 0.05
    for _ in range(60):
        mid = (lo + hi) / 2
        d, _ = PoletAkb(m_akb, V_KREYS, mid)
        lo, hi = (mid, hi) if d > 800 else (lo, mid)
    return lo


def PoletAkb(m_akb, v, cx0):
    """Аккумулятор тратится на винт и на бортовое питание."""
    vt = m_akb * EL_UDEL * EL_ISP * 3600                              # Дж в аккумуляторе
    moshch = Soprotivlenie(M_VZL, v, cx0) * v / (VINT * EL_MOTOR) + BORT
    t = vt / moshch
    return v * t / 1000, t / 3600


CX0 = Cx0PoSpravke()

VARIANTY = {
    "elektro":  dict(imya="Электрический", m_du=1.0, tip="akb"),
    "benzin":   dict(imya="ДВС с инжектором, бензин", m_du=3.2, tip="vint", ud=0.65, ud_lo=0.90, ud_hi=0.55),
    "kerosin":  dict(imya="ДВС на керосине", m_du=4.0, tip="vint", ud=0.80, ud_lo=1.00, ud_hi=0.70),
    "reaktiv":  dict(imya="Реактивный (малый ТРД)", m_du=2.5, tip="trd", ud=0.25, ud_lo=0.35, ud_hi=0.21),
}
# ud — удельный расход: для ДВС кг/(кВт·ч) на валу при малой нагрузке,
# для ТРД кг/(Н·ч) тяги на неполном газе; ud_lo/ud_hi — худший и лучший случай


def Polet(kl, nagr, ud, v):
    """Дальность (км) и время (ч) при постоянной скорости v."""
    v_ = VARIANTY[kl]
    energ = M_VZL - M_PLANER - nagr - v_["m_du"]
    if energ <= 0:
        return 0.0, 0.0
    if v_["tip"] == "akb":
        return PoletAkb(energ, v, CX0)
    m, toplivo, t, dt = M_VZL, energ * 0.95, 0.0, 10.0     # 5 % — невырабатываемый остаток
    while toplivo > 0:
        tyaga = Soprotivlenie(m, v, CX0)
        if v_["tip"] == "vint":
            val = tyaga * v / VINT + BORT / GENERATOR         # Вт на валу: винт и генератор
            rashod = val / 1000 * ud / 3600                    # кг/с
        else:
            # у малых ТРД генератора обычно нет: бортовое питание — из аккумулятора
            # в массе установки, расход топлива на него не тратится
            rashod = tyaga * ud / 3600
        sg = rashod * dt
        toplivo -= sg
        m -= sg
        t += dt
    return v * t / 1000, t / 3600


def Raschet():
    rez = {"cx0": round(CX0, 4), "kachestvo": round(M_VZL * G / Soprotivlenie(M_VZL, V_KREYS, CX0), 1),
           "varianty": {}}
    for kl, v_ in VARIANTY.items():
        v = 150 / 3.6 if v_["tip"] == "trd" else V_KREYS
        r = {"imya": v_["imya"], "m_du": v_["m_du"],
             "m_energ": round(M_VZL - M_PLANER - M_NAGR - v_["m_du"], 1),
             "skorost_kreys": round(v * 3.6)}
        if v_["tip"] == "akb":
            d, t = Polet(kl, M_NAGR, None, v)
            r.update(dalnost=round(d), vremya=round(t, 1), dalnost_lo=round(d), dalnost_hi=round(d))
        else:
            d, t = Polet(kl, M_NAGR, v_["ud"], v)
            dlo, tlo = Polet(kl, M_NAGR, v_["ud_lo"], v)
            dhi, thi = Polet(kl, M_NAGR, v_["ud_hi"], v)
            r.update(dalnost=round(d), vremya=round(t, 1), dalnost_lo=round(dlo), dalnost_hi=round(dhi),
                     vremya_lo=round(tlo, 1), vremya_hi=round(thi, 1))
        r["po_nagruzke"] = {}
        for nagr in (1.5, 3.0, 5.0):
            d, _ = Polet(kl, nagr, v_.get("ud"), v)
            r["po_nagruzke"][str(nagr)] = round(d)
        if v_["tip"] != "akb":
            # подбор бака на 24 ч полёта, остаток массы — нагрузке
            lo, hi = 0.0, M_VZL - M_PLANER - v_["m_du"] - 0.1
            for _ in range(40):
                mid = (lo + hi) / 2
                _, tt = Polet(kl, mid, v_["ud"], v)
                lo, hi = (mid, hi) if tt > 24 else (lo, mid)
            r["nagr_24ch"] = round(lo, 1)
        rez["varianty"][kl] = r
    return rez


if __name__ == "__main__":
    rez = Raschet()
    Path(__file__).with_name("raschet.json").write_text(json.dumps(rez, ensure_ascii=False, indent=1), encoding="utf-8")
    print("Cx0 =", rez["cx0"], " качество на 95 км/ч =", rez["kachestvo"])
    for kl, r in rez["varianty"].items():
        print(f'{r["imya"]:28} ДУ {r["m_du"]} кг, энергия {r["m_energ"]} кг, {r["skorost_kreys"]} км/ч: '
              f'{r["dalnost"]} км ({r["dalnost_lo"]}–{r["dalnost_hi"]}), {r["vremya"]} ч; по нагрузке {r["po_nagruzke"]}')
