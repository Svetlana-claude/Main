#!/usr/bin/env python3
"""Плакаты отказов: геометрия в ImageMagick, обработка в G'MIC и ImageMagick.

Запуск: python3 plakaty.py [папка-вывода]  (нужны пакеты imagemagick и gmic)
"""
import math, os, subprocess, sys, tempfile

SRC='/home/mokeeva/main/exchange/otkazy-yadisk/photo_2026-10-12_12-'
OUT=sys.argv[1] if len(sys.argv)>1 else os.path.dirname(os.path.abspath(__file__))
W,H=1200,848
U={
 '34-25':((82,83),(806,93),(812,1140),(115,1180),'cover'),
 '38-53':((224,303),(803,303),(799,1134),(228,1136),'cover'),
 '38-56':((118,152),(803,168),(797,1152),(152,1172),'cover'),
 '38-58':((127,130),(853,150),(850,1168),(160,1192),'cover'),
 '39-01':((100,152),(860,184),(834,1117),(93,1119),'cover'),
 '39-03':((104,234),(860,266),(834,1042),(98,1044),'cover'),
 '39-05':((119,151),(851,179),(819,1089),(119,1099),'cover'),
 '39-08':((119,101),(839,149),(821,1153),(126,1176),'cover'),
 '39-10':((133,121),(854,134),(849,1168),(164,1207),'cover'),
 '39-12':((151,81),(884,96),(879,1149),(181,1188),'cover'),
 '39-14':((113,101),(853,118),(867,1181),(129,1194),'cover'),
 '39-16':((103,116),(824,141),(819,1168),(128,1203),'cover'),
 '39-20':((148,96),(844,126),(841,1134),(146,1159),'cover'),
 '39-22':((163,101),(847,152),(810,1144),(131,1213),'cover'),
 '39-25':((151,148),(810,184),(814,1169),(133,1179),'cover'),
 '39-26':((96,134),(837,151),(834,1224),(121,1251),'cover'),
}
NIZ={'38-53':0.0,'39-01':0.0,'39-05':0.0}  # доля кадра снизу под логотипы; у фото без логотипов — 0
MYAGKO={'38-53','39-01'}                   # серое небо с тонкими стропами — сглаживать бережнее

def zapusk(*k): subprocess.run(k,check=True)

for i,(n,(tl,tr,br,bl,_)) in enumerate(sorted(U.items()),1):
    q=[tl,tr,br,bl]
    # поджимаем на 3,5 %: срезаем кромку листа и полоски нижних листов
    cx=sum(p[0] for p in q)/4; cy=sum(p[1] for p in q)/4
    q=[(cx+(x-cx)*0.965,cy+(y-cy)*0.965) for x,y in q]
    dl=lambda a,b: math.dist(q[a],q[b])
    k=1.6; w=int((dl(0,3)+dl(1,2))/2*k); h=int((dl(0,1)+dl(3,2))/2*k)
    # поворот на 90° против часовой: ЛВ фото → ЛН, ПВ → ЛВ, ПН → ПВ, ЛН → ПН
    dst=[(0,h),(0,0),(w,0),(w,h)]
    pary=' '.join(f'{x:.1f},{y:.1f} {u},{v}' for (x,y),(u,v) in zip(q,dst))
    hh=int(h*(1-NIZ.get(n,0.085)))
    with tempfile.TemporaryDirectory() as t:
        geo,gl=f'{t}/geo.png',f'{t}/gl.png'
        # 1. ImageMagick: перспектива, поворот, срез полосы логотипов
        zapusk('convert',SRC+n+'.jpg','-virtual-pixel','edge','-filter','Lanczos',
               '-define',f'distort:viewport={w}x{h}+0+0','-distort','Perspective',pary,
               '+repage','-crop',f'{w}x{hh}+0+0','+repage',geo)
        # 2. G'MIC: анизотропное сглаживание — убирает зерно и складки бумаги вдоль, не размывая стропы
        a='40,0.9,1,0.5,1.0,0.8,30,2,0,1' if n in MYAGKO else '70,0.9,1,0.6,1.2,0.8,30,2,0,1'
        zapusk('gmic','-v','-1',geo,'smooth',a,'-o',gl)
        # 3. ImageMagick: уровни, контраст, сочность, резкость, кадр 1200×848
        zapusk('convert',gl,'-channel','RGB','-contrast-stretch','0.2%x0.15%','+channel',
               '-sigmoidal-contrast','2,50%','-modulate','101,112,100',
               '-resize',f'{round(W*1.03)}x{round(H*1.03)}^','-gravity','center','-extent',f'{W}x{H}',
               '-unsharp','0x1.2+0.7+0.02','-strip','-quality','90',
               f'{OUT}/plakat-{i:02d}.jpg')
    print(f'plakat-{i:02d}.jpg ← {n}')
