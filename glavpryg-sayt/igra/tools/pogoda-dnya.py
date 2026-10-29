#!/usr/bin/env python3
"""Погода в Большом Грызлове на сегодня и завтра — для игры «Точно в круг».

    python3 pogoda-dnya.py <куда записать pogoda-dnya.json> [--iz файл-ответа.json]

Берёт прогноз Open-Meteo (без ключа, данные CC BY 4.0) по часам и сводит его к
тому, что понимает игра: ветер по высотам, облачные слои, порывы, запрет прыжков,
время года. Запускается по crontab каждые два часа (см. architect.md), файл
пишется целиком и подменяется разом — игра никогда не прочтёт половину.
`--iz` — разобрать сохранённый ответ вместо запроса (для проверок).

Высоты — над аэродромом, м. Направление ветра — «куда дует», в градусах мира игры:
метео «откуда» + 180 и поправка на поворот карты учебника к северу (+3,9°,
см. osm-karta.py).
"""
import sys, json, math, os, time, datetime, urllib.request, urllib.parse

LAT, LON, VYS_AERO = 54.7884, 37.6460, 243
POVOROT = 3.9
UROVNI = [1000, 975, 950, 925, 900, 850, 800, 700, 600, 500, 400, 300]   # гПа
CHASY = range(24)            # все часы: прыгают от восхода до заката, а он летом с 4 до 21 по Москве

def zapros():
    hourly = ['temperature_2m', 'dew_point_2m', 'wind_speed_10m', 'wind_direction_10m', 'wind_gusts_10m',
              'wind_speed_80m', 'wind_direction_80m', 'wind_speed_120m', 'wind_direction_120m',
              'wind_speed_180m', 'wind_direction_180m', 'cloud_cover_low', 'cloud_cover_mid', 'cloud_cover_high',
              'precipitation', 'snowfall', 'snow_depth', 'weather_code', 'visibility', 'cape']
    for p in UROVNI:
        hourly += [f'wind_speed_{p}hPa', f'wind_direction_{p}hPa', f'cloud_cover_{p}hPa', f'geopotential_height_{p}hPa']
    q = urllib.parse.urlencode({'latitude': LAT, 'longitude': LON, 'timezone': 'Europe/Moscow', 'forecast_days': 2,
                                'wind_speed_unit': 'ms', 'hourly': ','.join(hourly)})
    req = urllib.request.Request('https://api.open-meteo.com/v1/forecast?' + q, headers={'User-Agent': 'glavpryg-igra/1.0'})
    # Open-Meteo временами отвечает 503: с 25.10.2026 так пропадали сутки подряд и сводка в игре
    # застыла. Пробуем ещё через 1, 5 и 15 минут — запуск всё равно раз в два часа
    for pauza in (60, 300, 900, None):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except Exception as e:
            print(msk(), 'Open-Meteo:', e, '— ещё раз через', pauza, 'с' if pauza else '— сдаюсь', flush=True)
            if pauza is None: raise
            time.sleep(pauza)

def msk():
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=3))).strftime('%d.%m.%Y %H:%M МСК')

def kuda(otkuda):
    return round((otkuda + 180 + POVOROT) % 360)

def veter(H, i, elev):
    """[высота, скорость, куда] снизу вверх: 10–180 м — по мачтовым уровням, выше — по изобарам."""
    v = [[10, H['wind_speed_10m'][i], kuda(H['wind_direction_10m'][i])]]
    for z in (80, 120, 180):
        v.append([z, H[f'wind_speed_{z}m'][i], kuda(H[f'wind_direction_{z}m'][i])])
    for p in UROVNI:
        h = H[f'geopotential_height_{p}hPa'][i] - elev
        if 250 < h < 6000 and H[f'wind_speed_{p}hPa'][i] is not None:
            v.append([round(h), H[f'wind_speed_{p}hPa'][i], kuda(H[f'wind_direction_{p}hPa'][i])])
    return [[z, round(w, 1), d] for z, w, d in sorted(v)]

def sloi(H, i, elev):
    """Облачные слои: соседние изобары с облачностью от 25 % — один слой."""
    urov = []
    for p in UROVNI:
        h = H[f'geopotential_height_{p}hPa'][i] - elev
        if h > 0: urov.append((h, (H[f'cloud_cover_{p}hPa'][i] or 0) / 100))
    gruppy, tek = [], []
    for j, (h, c) in enumerate(urov):
        if c >= 0.25: tek.append(j)
        elif tek: gruppy.append(tek); tek = []
    if tek: gruppy.append(tek)
    # основание кучевых — по разнице температуры и точки росы (≈ 125 м на градус)
    osn = max(300, 125 * (H['temperature_2m'][i] - H['dew_point_2m'][i]))
    konv = (H['cape'][i] or 0) > 150
    out = []
    for g in gruppy:
        hs = [urov[j][0] for j in g]; pokr = max(urov[j][1] for j in g)
        niz = (hs[0] + urov[g[0] - 1][0]) / 2 if g[0] > 0 else hs[0] / 2
        verh = (hs[-1] + urov[g[-1] + 1][0]) / 2 if g[-1] + 1 < len(urov) else hs[-1] + 500
        if abs(niz - osn) < 600: niz = osn
        tip = 'ci' if niz > 5000 else 'cu' if (konv or pokr < 0.6) and niz < 3000 else 'sc'
        out.append({'tip': tip, 'niz': int(round(niz, -2)), 'verh': int(round(max(verh, niz + 300), -2)), 'pokr': round(min(1, pokr), 2)})
    # тонкая низкая облачность, которую изобары пропустили
    nizk = (H['cloud_cover_low'][i] or 0) / 100
    if nizk >= 0.25 and not any(L['niz'] < 2000 for L in out):
        out.append({'tip': 'cu' if nizk < 0.6 else 'sc', 'niz': int(round(osn, -2)), 'verh': int(round(osn + 500, -2)), 'pokr': round(nizk, 2)})
    vys = (H['cloud_cover_high'][i] or 0) / 100
    if vys >= 0.3 and not any(L['tip'] == 'ci' for L in out):
        out.append({'tip': 'ci', 'niz': 7000, 'verh': 8000, 'pokr': round(vys, 2)})
    return sorted(out, key=lambda L: L['niz'])

def zapret(H, i, sl):
    """Почему прыжков нет — по нормам AFF (с. 44) и здравому смыслу; None — прыгать можно."""
    w, g, kod = H['wind_speed_10m'][i], H['wind_gusts_10m'][i] or 0, H['weather_code'][i]
    if w > 10 or g > 12: return f'ветер у земли {w:.0f} м/с, порывы до {g:.0f} — выше нормы AFF (10 м/с)'
    if kod in (95, 96, 99): return 'гроза'
    if (H['precipitation'][i] or 0) >= 1 or kod in (65, 67, 75, 82, 86): return 'сильные осадки'
    if (H['visibility'][i] or 99999) < 2000: return 'видимость меньше 2 км'
    nizk = [L['niz'] for L in sl if L['pokr'] >= 0.8 and L['tip'] != 'ci']
    if nizk and min(nizk) < 900: return f'облачность {min(nizk)} м — ниже высоты раскрытия'
    return None

def sezon(data, sneg):
    """Время года для карты: снег лежит — зима, иначе по дате."""
    if sneg >= 0.03: return 'zima'
    m, d = data.month, data.day
    if m in (6, 7, 8) or (m == 9 and d < 15): return 'leto'
    if m in (9, 10): return 'osen'
    if m == 5 or (m == 4 and d >= 20): return 'vesna'
    return 'golaya'

def svesti(o):
    H, elev = o['hourly'], o.get('elevation', VYS_AERO)
    chasy = {}
    for i, t in enumerate(H['time']):
        if int(t[11:13]) not in CHASY: continue
        sl = sloi(H, i, elev)
        chasy[t[:13]] = {'t': H['temperature_2m'][i], 'veter': veter(H, i, elev), 'poryvy': round(H['wind_gusts_10m'][i] or 0, 1),
                         'sloi': sl, 'osadki': H['precipitation'][i], 'sneg': H['snowfall'][i], 'kod': H['weather_code'][i],
                         'zapret': zapret(H, i, sl)}
    segodnya = datetime.date.fromisoformat(H['time'][0][:10])
    sneg = max(x or 0 for x in H['snow_depth'][:24])
    return {'mesto': 'Большое Грызлово', 'data': segodnya.isoformat(), 'sezon': sezon(segodnya, sneg), 'snegM': sneg,
            'obnovleno': datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=3))).isoformat(timespec='minutes'),
            'istochnik': 'Open-Meteo', 'chasy': chasy}

if __name__ == '__main__':
    kuda_pisat = sys.argv[1]
    o = json.load(open(sys.argv[sys.argv.index('--iz') + 1])) if '--iz' in sys.argv else zapros()
    rez = svesti(o)
    vrem = kuda_pisat + '.tmp'
    with open(vrem, 'w') as f: json.dump(rez, f, ensure_ascii=False, separators=(',', ':'))
    os.chmod(vrem, 0o644); os.replace(vrem, kuda_pisat)
    print(msk(), rez['data'], rez['sezon'], len(rez['chasy']), 'ч')
