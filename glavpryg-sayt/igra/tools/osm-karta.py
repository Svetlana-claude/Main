#!/usr/bin/env python3
"""Широкая карта вокруг аэродрома — из OpenStreetMap, в стиле игры.

    python osm-karta.py <каталог OSM> <каталог assets>

Каталог OSM — выгрузки Overpass (`priroda.json`, `voda.json`, `dorogi.json`,
`doma.json`, запрос — в `architect.md`). Карта учебника (дальний слой) покрывает
≈ 4×5 км; эта — 15×15 км вокруг, чтобы за краем учебника была местность, а не
пустой фон. Цвета — из палитры дальнего слоя, лес — тем же узором крон.

Привязка OSM к миру игры — аффинное преобразование `OSM2IGRA`: подобрано по лесу
маски игры (поиск по повороту и масштабу, затем ECC, совпадение 0,87); дороги OSM
ложатся на дороги снимка учебника. Мир игры повёрнут к северу на ≈ 3,9° и сжат
к настоящим метрам в ≈ 0,9 раза — так снят учебник.

На выходе в assets:
- `karta-shir.webp` — широкий слой (`MIR.shir`, 0,15 точки/м);
- `maska-shir.png` — лес 100 / вода 200, 10 м/точка (`MIR.maskaShir`);
- `karta-dal.webp` — тот же дальний слой, но с растушёванными краями
  (альфа ставится заново, повторный запуск ничего не портит).
Печатает строку `MESTA` — подписи населённых пунктов для кода игры.
"""
import sys, json, math, zlib, numpy as np, cv2
from PIL import Image

src, dst = sys.argv[1], sys.argv[2]
LAT0, LON0 = 54.7884, 37.6460                       # аэродром Большое Грызлово
KX = 111320 * math.cos(math.radians(LAT0)); KY = 110540
OSM2IGRA = np.array([[0.9002034, -0.0671706, 191.8802234],
                     [0.0613580, 0.8664672, 201.4459808]])
X0, Y0, X1, Y1, S = -7500, -7500, 7500, 7500, 0.15   # широкий слой, м и точек/м
MS = 0.1                                             # маска: 10 м/точка
W, H = int((X1 - X0) * S), int((Y1 - Y0) * S)

def igra(lat, lon):
    x, y = (lon - LON0) * KX, -(lat - LAT0) * KY
    return OSM2IGRA @ (x, y, 1)

def tochki(geom, k=S):
    return np.array([[(p[0] - X0) * k, (p[1] - Y0) * k] for p in (igra(q['lat'], q['lon']) for q in geom)], np.int32)

def koltsa(e):
    """Внешние и внутренние кольца линии или мультиполигона."""
    if 'geometry' in e: return [e['geometry']], []
    vn, vnutr = [], []
    for m in e.get('members', []):
        if 'geometry' in m and len(m['geometry']) > 2: (vnutr if m.get('role') == 'inner' else vn).append(m['geometry'])
    return vn, vnutr

def ploshad(geom):
    p = tochki(geom).astype(np.float64)
    return abs(cv2.contourArea(p.astype(np.float32))) if len(p) > 2 else 0

def zagruzit(imya):
    return json.load(open(f'{src}/{imya}.json'))['elements']

def cvet(e, nabor):
    """Цвет из набора — свой у каждого участка, но один и тот же при каждой сборке."""
    return nabor[zlib.crc32(str(e['id']).encode()) % len(nabor)]

# палитра дальнего слоя (RGB → BGR для cv2)
bgr = lambda c: (c[2], c[1], c[0])
PASHNYA = [bgr(c) for c in [(196, 156, 47), (180, 181, 45), (207, 166, 58), (134, 159, 41), (217, 198, 104), (110, 132, 15)]]
LUG = [bgr(c) for c in [(160, 183, 93), (131, 164, 91), (103, 147, 52), (107, 139, 80)]]
FON = bgr((160, 183, 93)); KUST = bgr((107, 139, 80)); BOLOTO = bgr((69, 121, 70))
ZHILYE = bgr((217, 198, 104)); KRYSHA = [bgr((255, 253, 222)), bgr((255, 224, 144))]
DOROGA = bgr((255, 253, 222)); PROEZD = bgr((255, 224, 144)); GRUNTOVKA = bgr((207, 183, 93))
ZHD = bgr((90, 88, 80))
LES = [bgr(c) for c in [(24, 70, 30), (36, 104, 40), (70, 150, 60)]]; KRAY_LESA = bgr((20, 45, 18))
VODA = [bgr(c) for c in [(40, 90, 150), (60, 130, 190), (140, 200, 230)]]

pr = zagruzit('priroda'); vd = zagruzit('voda'); dr = zagruzit('dorogi'); dm = zagruzit('doma')
out = np.zeros((H, W, 3), np.uint8); out[:] = FON
les = np.zeros((H, W), np.uint8); voda = np.zeros((H, W), np.uint8)
mles = np.zeros((int((Y1 - Y0) * MS), int((X1 - X0) * MS)), np.uint8); mvoda = np.zeros_like(mles)

def zalit(img, e, c, k=S):
    vn, vnutr = koltsa(e)
    for g in vn: cv2.fillPoly(img, [tochki(g, k)], c)
    for g in vnutr: cv2.fillPoly(img, [tochki(g, k)], 0 if img.ndim == 2 else FON)

# угодья — крупные снизу, мелкие сверху
ugodya = []
for e in pr:
    t = e.get('tags', {}); lu, nt, le = t.get('landuse'), t.get('natural'), t.get('leisure')
    if lu in ('forest',) or nt == 'wood':
        zalit(les, e, 1); zalit(mles, e, 1, MS); continue
    if nt == 'water' or lu in ('reservoir', 'basin'):
        zalit(voda, e, 1); zalit(mvoda, e, 1, MS); continue
    c = (cvet(e, PASHNYA) if lu == 'farmland' else cvet(e, LUG) if lu in ('meadow', 'grass', 'recreation_ground') or nt == 'grassland' or le == 'park'
         else KUST if nt in ('scrub', 'heath') or lu in ('orchard',) else BOLOTO if nt == 'wetland'
         else ZHILYE if lu in ('residential', 'allotments', 'industrial', 'commercial', 'garages', 'retail', 'farmyard', 'cemetery') else None)
    if c is None: continue
    vn, _ = koltsa(e)
    ugodya.append((sum(ploshad(g) for g in vn), e, c))
for _, e, c in sorted(ugodya, key=lambda u: -u[0]):
    zalit(out, e, c)

# реки и ручьи — линиями
for e in vd:
    t = e.get('tags', {}); ww = t.get('waterway')
    if 'geometry' not in e or ww not in ('river', 'stream', 'canal'): continue
    shir = 4 if ww == 'river' else 1
    cv2.polylines(voda, [tochki(e['geometry'])], False, 1, shir)
    cv2.polylines(mvoda, [tochki(e['geometry'], MS)], False, 1, max(1, shir // 2))

# лес — узором крон, как в stilizovat-kartu.py
def plitka_lesa(shag):
    n = shag * 2; t = np.zeros((n, n, 3), np.uint8); t[:] = LES[0]
    for cx, cy in ((shag // 2, shag // 2), (shag + shag // 2, shag + shag // 2)):
        r = max(1, shag // 2 + (shag > 3))
        for dx, dy in ((0, 0), (n, 0), (0, n), (n, n), (-n, 0), (0, -n)):
            cv2.circle(t, (cx + dx, cy + dy), r, LES[1], -1)
            cv2.circle(t, (cx + dx - max(1, r // 3), cy + dy - max(1, r // 3)), max(1, r // 2), LES[2], -1)
    return t
les &= 1 - voda
t = plitka_lesa(3); n = t.shape[0]
uzor = np.tile(t, (H // n + 1, W // n + 1, 1))[:H, :W]
out[les == 1] = uzor[les == 1]
kray = cv2.morphologyEx(les, cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8))
out[(kray == 1) & (les == 0)] = KRAY_LESA
# вода — рябью
out[voda == 1] = VODA[0]
ys, xs = np.nonzero(voda)
ryab = ((xs + 2 * ys) % 9 == 0) & (ys % 3 == 0)
for x, y in zip(xs[ryab], ys[ryab]): cv2.line(out, (int(x), int(y)), (int(x + 2), int(y)), VODA[1], 1)
kray = cv2.morphologyEx(voda, cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8))
out[(kray == 1) & (voda == 0)] = VODA[2]

# постройки
for e in dm:
    if e['type'] == 'way' and 'geometry' in e and 'building' in e.get('tags', {}):
        p = tochki(e['geometry'])
        # огромные «здания» (склады, теплицы) — пятном застройки, а не белой крышей
        if len(p) > 2: cv2.fillPoly(out, [p], cvet(e, KRYSHA) if cv2.contourArea(p.astype(np.float32)) < 300 else ZHILYE)

# дороги: крупные — светлые и шире, грунтовки — тонкие
VID = {'motorway': (DOROGA, 3), 'trunk': (DOROGA, 3), 'primary': (DOROGA, 2), 'secondary': (DOROGA, 2), 'tertiary': (DOROGA, 1),
       'unclassified': (PROEZD, 1), 'residential': (PROEZD, 1), 'service': (PROEZD, 1), 'track': (GRUNTOVKA, 1)}
dorogi = []
for e in dr:
    t = e.get('tags', {})
    if 'geometry' not in e: continue
    if t.get('highway') in VID: dorogi.append((VID[t['highway']][1], e, *VID[t['highway']]))
    elif t.get('aeroway') == 'runway': dorogi.append((4, e, DOROGA, 3))
    elif t.get('railway') in ('rail',): dorogi.append((5, e, ZHD, 1))
for _, e, c, w in sorted(dorogi, key=lambda d: d[0]):
    cv2.polylines(out, [tochki(e['geometry'])], False, c, w)

Image.fromarray(cv2.cvtColor(out, cv2.COLOR_BGR2RGB)).save(f'{dst}/karta-shir.webp', lossless=True, quality=100, method=6)
maska = np.zeros_like(mles); maska[mles == 1] = 100; maska[mvoda == 1] = 200
cv2.imwrite(f'{dst}/maska-shir.png', maska)

# дальний слой — края растушёвываются в широкий
dal = np.array(Image.open(f'{dst}/karta-dal.webp').convert('RGB'))
h, w = dal.shape[:2]; F = 90                                   # 180 м при 0,5 точки/м
y = np.minimum(np.arange(h), np.arange(h)[::-1]); x = np.minimum(np.arange(w), np.arange(w)[::-1])
a = np.clip(np.minimum.outer(y, x) / F, 0, 1); a = (a * a * (3 - 2 * a) * 255).astype(np.uint8)
Image.fromarray(np.dstack([dal, a])).save(f'{dst}/karta-dal.webp', lossless=True, quality=100, method=6)

# подписи: города и сёла в пределах широкого слоя
mesta = []
for e in dm:
    t = e.get('tags', {})
    if e['type'] == 'node' and t.get('place') in ('town', 'village', 'hamlet', 'city') and t.get('name'):
        gx, gy = igra(e['lat'], e['lon'])
        if X0 < gx < X1 and Y0 < gy < Y1: mesta.append([t['name'], round(gx), round(gy), {'town': 2, 'city': 2, 'village': 1}.get(t['place'], 0)])
print('const MESTA = ' + json.dumps(mesta, ensure_ascii=False, separators=(',', ':')) + ';')
print('готово:', out.shape, 'лес', round(les.mean(), 2))
