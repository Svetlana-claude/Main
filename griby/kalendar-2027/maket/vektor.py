"""Векторные файлы вариантов календаря по слоям и шрифты к ним — для дизайнера.

    /home/mokeeva/main/exchange/pwenv/bin/python vektor.py [j k]

Для каждого варианта в griby/downloads/kalendar-2027/vektor/<вариант>/:
  <X>-sborka.svg          — вся сборка 297×728 мм, листы — слои, внутри листа — подслои;
  <X>-1-shapka.svg …      — каждый лист отдельным файлом;
  shrifty/                — шрифты, которыми набран текст;
и архив <вариант>.zip рядом. Текст в SVG — текстом, единицы — миллиметры.
Слои — в разметке Inkscape (inkscape:groupmode="layer"); Illustrator и Figma
открывают их группами с теми же именами.

Сверка: каждый лист SVG отрисовывается в браузере и сравнивается со снимком
макета; расхождение печатается, картинки сверки — в exchange/aevit/vektor/.
"""
import functools, http.server, json, os, re, shutil, sys, threading, zipfile
import numpy as np, cv2
from playwright.sync_api import sync_playwright

KOREN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # griby/kalendar-2027
VYHOD = os.path.join(KOREN, '..', 'downloads', 'kalendar-2027', 'vektor')
SVERKA = '/home/mokeeva/main/exchange/aevit/vektor'
VARIANTY = {'j': 'J-modul-molekula', 'k': 'K-vinyelli-molekula'}
POROG = 0.05   # % площади листа в сплошных пятнах расхождения
FAYLY_LISTOV = ['1-shapka', '2-dekabr', '3-yanvar', '4-fevral', '5-polosa']


def Server():
    class Tihiy(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    obr = functools.partial(Tihiy, directory=KOREN)
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), obr)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def Shrifty(spisok):
    """Семейство и насыщенность из браузера → файлы из fonts.css."""
    css = open(os.path.join(KOREN, 'maket', 'fonts.css')).read()
    grani = []
    for m in re.finditer(r'font-family:\s*"([^"]+)";([^}]*)src:\s*url\(([^)]+)\)', css):
        sem, ost, fayl = m.groups()
        ves = re.search(r'font-weight:\s*([\d ]+)', ost)
        vesa = [int(v) for v in ves.group(1).split()] if ves else [400]
        kursiv = 'italic' in ost
        grani.append((sem, min(vesa), max(vesa), kursiv, fayl))
    nuzhno = set()
    for z in spisok:
        sem, ves, stil = z.split('|')
        sem = sem.split(',')[0].strip().strip('"\'')
        for g in grani:
            if g[0] == sem and g[1] <= int(ves) <= g[2] and g[3] == (stil == 'italic'):
                nuzhno.add((sem, g[4]))
                break
        else:
            blizh = [g for g in grani if g[0] == sem and g[3] == (stil == 'italic')]
            if not blizh:
                print(f'  ! шрифт не найден в fonts.css: {z}')
                continue
            g = min(blizh, key=lambda g: min(abs(g[1] - int(ves)), abs(g[2] - int(ves))))
            nuzhno.add((sem, g[4]))
            print(f'  ! {sem} {ves}: такой грани нет, браузер дорисовывает её из {os.path.basename(g[4])}')
    return sorted(nuzhno)


def Sverit(pg, url, svg, etalon, imya):
    """Лист SVG — в браузер с теми же шрифтами, снимок, сравнение с макетом."""
    pg.goto(url + '/maket/vektor-sverka.html')
    pg.evaluate('s => { document.body.innerHTML = s.replace(/^<\\?xml[^>]*>/, ""); }', svg)
    pg.evaluate('Promise.all([...document.fonts].map(f => f.load()))')
    pg.wait_for_timeout(300)
    snimok = cv2.imdecode(np.frombuffer(pg.locator('svg').first.screenshot(), np.uint8), 1)
    if snimok.shape != etalon.shape:
        snimok = cv2.resize(snimok, (etalon.shape[1], etalon.shape[0]))
    sdvig = cv2.phaseCorrelate(np.float32(cv2.cvtColor(etalon, cv2.COLOR_BGR2GRAY)), np.float32(cv2.cvtColor(snimok, cv2.COLOR_BGR2GRAY)))[0]
    if max(map(abs, sdvig)) > 1:
        print(f'    ! сдвиг всего листа {sdvig[0]:+.2f}, {sdvig[1]:+.2f} точки')
    raz = cv2.absdiff(snimok, etalon).max(axis=2)
    # кайма сглаживания по краям — тонкие линии, их снимает размыкание;
    # остаются сплошные пятна: пропавший или сдвинутый элемент
    pyatna = cv2.morphologyEx(np.uint8(raz > 60), cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    cv2.imwrite(os.path.join(SVERKA, imya + '.jpg'), np.hstack([etalon, snimok, cv2.cvtColor(raz, cv2.COLOR_GRAY2BGR)]))
    return float(pyatna.mean()) * 100


def main():
    vybor = sys.argv[1:] or list(VARIANTY)
    os.makedirs(SVERKA, exist_ok=True)
    srv = Server()
    url = f'http://127.0.0.1:{srv.server_port}'
    oshibki = 0
    with sync_playwright() as p:
        br = p.chromium.launch()
        pg = br.new_page(viewport={'width': 1300, 'height': 1000}, device_scale_factor=2)
        for v in vybor:
            papka = os.path.join(VYHOD, VARIANTY[v])
            shutil.rmtree(papka, ignore_errors=True)
            os.makedirs(os.path.join(papka, 'shrifty'))
            pg.goto(f'{url}/maket/index.html?v={v}')
            pg.evaluate('document.fonts.ready')
            pg.wait_for_timeout(500)
            listy = pg.locator(f'#var-{v} .trio > *')
            etalony = [cv2.imdecode(np.frombuffer(listy.nth(i).screenshot(), np.uint8), 1) for i in range(listy.count())]
            # слой сетки: в выгрузку идёт скрытым, для этого включаем его на странице
            pg.add_script_tag(url=f'{url}/maket/vektor.js')
            pg.evaluate('document.body.classList.add("setka")')
            itog = pg.evaluate(f'VyvestiSvg("#var-{v}")')
            X = v.upper()
            open(os.path.join(papka, f'{X}-sborka.svg'), 'w').write(itog['polnyy'])
            print(f'{X}: {len(itog["polnyy"]) // 1024} КБ сборка')
            for i, l in enumerate(itog['otdelno']):
                open(os.path.join(papka, f'{X}-{FAYLY_LISTOV[i]}.svg'), 'w').write(l['svg'])
            for sem, fayl in Shrifty(itog['shrifty']):
                shutil.copy(os.path.join(KOREN, 'maket', fayl), os.path.join(papka, 'shrifty'))
                print(f'  шрифт {sem}: {os.path.basename(fayl)}')
            for pr in itog['preduprezhdeniya']:
                print('  ·', pr)
            for i, l in enumerate(itog['otdelno']):
                d = Sverit(pg, url, l['svg'], etalony[i], f'{v}-{FAYLY_LISTOV[i]}')
                print(f'  сверка {l["imya"]}: пятна расхождения {d:.3f} % — {"сходится" if d < POROG else "РАСХОДИТСЯ"}')
                oshibki += d >= POROG
            with zipfile.ZipFile(papka + '.zip', 'w', zipfile.ZIP_DEFLATED) as z:
                for kor, _, fayly in os.walk(papka):
                    for f in sorted(fayly):
                        z.write(os.path.join(kor, f), os.path.relpath(os.path.join(kor, f), VYHOD))
        br.close()
    srv.shutdown()
    if oshibki:
        sys.exit(f'листов с расхождением: {oshibki} — смотри картинки в {SVERKA}')


if __name__ == '__main__':
    main()
