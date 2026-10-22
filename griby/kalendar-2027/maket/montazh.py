"""Монтажный шаблон календаря-трио: монтажные области по обрезному формату и вылеты 3 мм.

    /home/mokeeva/main/exchange/pwenv/bin/python montazh.py

Выдача — в griby/downloads/kalendar-2027/montazh/:
- montazh-trio-2027.svg — одна страница Inkscape на каждый лист плюс схема сборки;
  страница = обрезной формат, вылет и служебные линии — отдельными слоями;
- montazh-trio-2027.pdf — по листу на страницу: метки реза, TrimBox по обрезу,
  BleedBox по вылету, текст в кривых.
"""
import os, subprocess, sys, tempfile
import pikepdf

TUT = os.path.dirname(os.path.abspath(__file__))
VYHOD = os.path.join(TUT, '..', '..', 'downloads', 'kalendar-2027', 'montazh')
IMYA = 'montazh-trio-2027'

SHIR = 297       # ширина всех листов, мм
VYLET = 3        # вылет под обрез
BEZOP = 5        # безопасная зона от линии реза
PRUZH = 5        # зона пружины сверху блока (как в макете)
POLE = 13        # поле листа PDF за обрезом: вылет + отступ и длина меток реза
METKA = (VYLET + 2, VYLET + 7)   # метка реза: от и до, мм от обреза
PROMEZH = 40     # промежуток между страницами в SVG
PT = 72 / 25.4

LISTY = [  # файл, название, высота, есть ли пружина
    ('1-shapka', 'Шапка', 210, False),
    ('2-blok-1', 'Блок 1 (первый месяц квартала)', 148, True),
    ('3-blok-2', 'Блок 2 (второй месяц)', 148, True),
    ('4-blok-3', 'Блок 3 (третий месяц)', 148, True),
    ('5-polosa', 'Рекламная полоса', 74, False),
]
SHRIFT = "font-family:'IBM Plex Mono';font-weight:500"


def Sloy(imya, soderzhimoe, skryt=False):
    """Слой Inkscape; Illustrator и Figma открывают его группой с тем же названием."""
    vid = ' style="display:none"' if skryt else ''
    return f'<g inkscape:groupmode="layer" inkscape:label="{imya}"{vid}>{soderzhimoe}</g>'


def Metki(h):
    """Метки реза у четырёх углов, вне вылета."""
    a, b = METKA
    lin = []
    for x in (0, SHIR):
        for y in (0, h):
            sx = -1 if x == 0 else 1
            sy = -1 if y == 0 else 1
            lin.append(f'M{x + sx * a} {y}H{x + sx * b}M{x} {y + sy * a}V{y + sy * b}')
    return f'<path d="{"".join(lin)}" fill="none" stroke="#000" stroke-width="0.25"/>'


def List(nazv, h, pruzh, metki):
    """Монтажная область одного листа; начало координат — левый верхний угол обреза."""
    v, b = VYLET, BEZOP
    sloi = [
        Sloy('Макет — фон и вёрстка сюда, фон до линии вылета', ''),
        Sloy('Вылет 3 мм',
             f'<path d="M{-v} {-v}h{SHIR + 2 * v}v{h + 2 * v}h{-SHIR - 2 * v}z M0 0v{h}h{SHIR}v{-h}z" '
             f'fill="#e03131" fill-opacity="0.12" fill-rule="evenodd"/>'
             f'<rect x="{-v}" y="{-v}" width="{SHIR + 2 * v}" height="{h + 2 * v}" fill="none" stroke="#e03131" stroke-width="0.2"/>'),
        Sloy('Линия реза', f'<rect x="0" y="0" width="{SHIR}" height="{h}" fill="none" stroke="#000" stroke-width="0.25"/>'),
        Sloy('Безопасная зона 5 мм',
             f'<rect x="{b}" y="{b}" width="{SHIR - 2 * b}" height="{h - 2 * b}" fill="none" stroke="#1971c2" '
             f'stroke-width="0.2" stroke-dasharray="2 1"/>'),
    ]
    if pruzh:
        sloi.append(Sloy('Зона пружины 5 мм',
                         f'<rect x="0" y="0" width="{SHIR}" height="{PRUZH}" fill="#868e96" fill-opacity="0.3"/>'
                         f'<text x="{SHIR / 2}" y="{PRUZH - 1.5}" text-anchor="middle" style="{SHRIFT};font-size:2.2px" '
                         f'fill="#495057">ЗОНА ПРУЖИНЫ {PRUZH} ММ — БЕЗ ТЕКСТА И ВАЖНЫХ ЭЛЕМЕНТОВ</text>'))
    if metki:
        sloi.append(Sloy('Метки реза', Metki(h)))
    sloi.append(Sloy('Подписи',
                     f'<text x="{METKA[1] + 3}" y="{-VYLET - 4}" style="{SHRIFT};font-size:3px" fill="#495057">'
                     f'{nazv.upper()} · ОБРЕЗ {SHIR}×{h} ММ · С ВЫЛЕТАМИ {SHIR + 2 * v}×{h + 2 * v} ММ</text>'
                     f'<text x="{SHIR - METKA[1] - 3}" y="{h + VYLET + 6}" text-anchor="end" style="{SHRIFT};font-size:2.4px" fill="#868e96">'
                     f'КРАСНАЯ — ВЫЛЕТ {v} ММ · ЧЁРНАЯ — РЕЗ · СИНЯЯ — БЕЗОПАСНАЯ ЗОНА {b} ММ</text>'))
    return ''.join(sloi)


def Shema():
    """Схема сборки: листы по обрезу один под другим, общая высота."""
    y, chasti = 0, []
    for _, nazv, h, _ in LISTY:
        chasti.append(f'<rect x="0" y="{y}" width="{SHIR}" height="{h}" fill="#f1f3f5" stroke="#000" stroke-width="0.3"/>'
                      f'<text x="{SHIR / 2}" y="{y + h / 2 + 2}" text-anchor="middle" style="{SHRIFT};font-size:6px" '
                      f'fill="#495057">{nazv.split(" (")[0].upper()} · {SHIR}×{h}</text>')
        y += h
    chasti.append(f'<text x="0" y="-7" style="{SHRIFT};font-size:3px" fill="#495057">'
                  f'СХЕМА СБОРКИ · ПО ОБРЕЗУ {SHIR}×{y} ММ</text>')
    return Sloy('Схема сборки', ''.join(chasti)), y


def Svg(w, h, telo, stranicy=''):
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" '
            f'xmlns:sodipodi="http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd" '
            f'width="{w}mm" height="{h}mm" viewBox="0 0 {w} {h}">'
            f'<sodipodi:namedview inkscape:document-units="mm">{stranicy}</sodipodi:namedview>{telo}</svg>\n')


def Mnogostranichnyy():
    """Один SVG, страницы Inkscape по обрезу листов одна под другой, схема — справа."""
    telo, stranicy, y = [], [], 0
    for fayl, nazv, h, pruzh in LISTY:
        stranicy.append(f'<inkscape:page id="{fayl}" inkscape:label="{nazv}" x="0" y="{y}" width="{SHIR}" height="{h}"/>')
        telo.append(f'<g id="list-{fayl}" inkscape:label="{nazv}" transform="translate(0 {y})">{List(nazv, h, pruzh, True)}</g>')
        y += h + PROMEZH
    shema, hs = Shema()
    x = SHIR + 2 * PROMEZH
    stranicy.append(f'<inkscape:page id="shema" inkscape:label="Схема сборки" x="{x}" y="0" width="{SHIR}" height="{hs}"/>')
    telo.append(f'<g transform="translate({x} 0)">{shema}</g>')
    return Svg(SHIR, LISTY[0][2], ''.join(telo), ''.join(stranicy))


def Proverit(pdf):
    """Каждая страница: TrimBox — обрез, BleedBox — обрез плюс вылет, MediaBox с полем под метки.
    Возвращает список расхождений."""
    oshibki = []
    with pikepdf.open(pdf) as d:
        for i, (fayl, _, h, _) in enumerate(LISTY):
            s = d.pages[i].obj
            zhdu = {'/TrimBox': (POLE, POLE, POLE + SHIR, POLE + h),
                    '/BleedBox': (POLE - VYLET, POLE - VYLET, POLE + SHIR + VYLET, POLE + h + VYLET),
                    '/MediaBox': (0, 0, SHIR + 2 * POLE, h + 2 * POLE)}
            for klyuch, ramka in zhdu.items():
                est = [float(c) / PT for c in s.get(klyuch, [])]
                if len(est) != 4 or max(abs(a - b) for a, b in zip(est, ramka)) > 0.05:
                    oshibki.append(f'{fayl} {klyuch}: {est and [round(c, 2) for c in est]} вместо {ramka}')
    return oshibki


def main():
    os.makedirs(VYHOD, exist_ok=True)
    svg = os.path.join(VYHOD, IMYA + '.svg')
    open(svg, 'w').write(Mnogostranichnyy())
    print(f'  {os.path.relpath(svg, TUT)}')

    with tempfile.TemporaryDirectory() as tmp:
        conf = os.path.join(tmp, 'fonts.conf')
        open(conf, 'w').write(f'<?xml version="1.0"?><fontconfig><include ignore_missing="yes">/etc/fonts/fonts.conf</include>'
                              f'<dir>{os.path.join(TUT, "fonts")}</dir><cachedir>{tmp}</cachedir></fontconfig>')
        env = dict(os.environ, FONTCONFIG_FILE=conf)
        stranicy = []
        for fayl, nazv, h, pruzh in LISTY + [('6-shema', None, None, None)]:
            if nazv:
                w, hh = SHIR + 2 * POLE, h + 2 * POLE
                telo = f'<g transform="translate({POLE} {POLE})">{List(nazv, h, pruzh, True)}</g>'
            else:
                shema, hs = Shema()
                w, hh = SHIR + 2 * POLE, hs + 2 * POLE
                telo = f'<g transform="translate({POLE} {POLE})">{shema}</g>'
            s = os.path.join(tmp, fayl + '.svg')
            open(s, 'w').write(Svg(w, hh, telo))
            p = os.path.join(tmp, fayl + '.pdf')
            subprocess.run(['inkscape', s, '--export-type=pdf', '--export-text-to-path', f'--export-filename={p}'],
                           env=env, check=True, capture_output=True)
            stranicy.append(p)
        obshchiy = os.path.join(tmp, 'vse.pdf')
        subprocess.run(['pdfunite', *stranicy, obshchiy], check=True)
        pdf = os.path.join(VYHOD, IMYA + '.pdf')
        with pikepdf.open(obshchiy) as d:
            for i, (_, _, h, _) in enumerate(LISTY):
                s = d.pages[i].obj
                s.TrimBox = pikepdf.Array([POLE * PT, POLE * PT, (POLE + SHIR) * PT, (POLE + h) * PT])
                s.BleedBox = pikepdf.Array([(POLE - VYLET) * PT, (POLE - VYLET) * PT,
                                            (POLE + SHIR + VYLET) * PT, (POLE + h + VYLET) * PT])
            d.save(pdf)
    print(f'  {os.path.relpath(pdf, TUT)}')

    oshibki = Proverit(pdf)
    shrifty = subprocess.run(['pdffonts', pdf], capture_output=True, text=True).stdout.splitlines()[2:]
    if shrifty:
        oshibki.append(f'в PDF остались шрифты: {len(shrifty)}')
    for o in oshibki:
        print('  !', o)
    print('  рамки страниц и кривые — ' + ('РАСХОДЯТСЯ' if oshibki else 'сходятся'))
    sys.exit(1 if oshibki else 0)


if __name__ == '__main__':
    main()
