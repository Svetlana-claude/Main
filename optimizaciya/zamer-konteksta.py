#!/usr/bin/env python3
"""Замер расхода контекста по стенограммам сессий Claude Code.

Читает `~/.claude/projects/<каталог>/<сессия>.jsonl` и считает по шагам агента
то, за что платится на самом деле: размер контекста на шаге (вход + чтение кэша
+ запись кэша), число шагов в ответе и стоимость сообщения.

    python3 zamer-konteksta.py --svod [--tema ПОДСТРОКА] [--verh N]
    python3 zamer-konteksta.py --kalibrovka   # знаков на токен по нашим файлам
    python3 zamer-konteksta.py --proverka     # самопроверка на подставных данных

Цены — те же, что выведены подбором по базе в `webui/rashod-tokenov.md`
(Opus 5, кэш на час): чтение кэша $0.5/млн, запись $10/млн, выход $25/млн.
"""

import argparse
import json
import pathlib
import sys

CENA_CHTENIE = 0.5 / 1e6
CENA_ZAPIS = 10.0 / 1e6
CENA_VYHOD = 25.0 / 1e6
CENA_VHOD = 5.0 / 1e6

KORENX = pathlib.Path.home() / ".claude" / "projects"


def ReadZapisi(put):
    """Разбирает стенограмму в список записей, битые строки пропускает."""
    for stroka in put.open(encoding="utf-8", errors="replace"):
        stroka = stroka.strip()
        if not stroka:
            continue
        try:
            yield json.loads(stroka)
        except json.JSONDecodeError:
            continue


def RazmerKonteksta(usage):
    """Контекст на шаге — всё, что ушло на вход: обычный вход и обе части кэша."""
    return (
        usage.get("input_tokens", 0)
        + usage.get("cache_read_input_tokens", 0)
        + usage.get("cache_creation_input_tokens", 0)
    )


def CenaShaga(usage):
    return (
        usage.get("cache_read_input_tokens", 0) * CENA_CHTENIE
        + usage.get("cache_creation_input_tokens", 0) * CENA_ZAPIS
        + usage.get("input_tokens", 0) * CENA_VHOD
        + usage.get("output_tokens", 0) * CENA_VYHOD
    )


def ShagiSessii(put):
    """Шаги агента: по одному на ответ модели, с размером контекста и ценой."""
    shagi = []
    tekPrompt = None
    predZapros = None
    for zapis in ReadZapisi(put):
        # `promptId` стоит на записях пользователя — и на самом вопросе, и на
        # результатах инструментов внутри ответа; у ответов модели он пустой.
        # Поэтому номер сообщения берётся с последней записи пользователя.
        if zapis.get("promptId"):
            tekPrompt = zapis["promptId"]
        if zapis.get("type") != "assistant":
            continue
        usage = (zapis.get("message") or {}).get("usage") or {}
        if not usage:
            continue
        # Одна реплика модели лежит в стенограмме несколькими записями
        # (размышление, текст, вызов инструмента) — и в каждой повторён один
        # и тот же `usage`. Шаг — это запрос к модели, то есть `requestId`;
        # без этой проверки шаги и цена умножаются на 2–3.
        zapros = zapis.get("requestId")
        if zapros is not None and zapros == predZapros:
            continue
        predZapros = zapros
        shagi.append(
            {
                "kontekst": RazmerKonteksta(usage),
                "vyhod": usage.get("output_tokens", 0),
                "cena": CenaShaga(usage),
                "promptId": tekPrompt,
                "uuid": zapis.get("uuid"),
                "roditel": zapis.get("parentUuid"),
            }
        )
    return shagi


def SoobshcheniyaPoShagam(shagi):
    """Группирует шаги в сообщения: шаг — продолжение, если контекст вырос.

    Границу сообщения даёт падение размера контекста (новый ответ начинается
    с того же или меньшего контекста только после сжатия) либо смена `promptId`,
    если он есть в стенограмме.
    """
    soobshcheniya = []
    tek = []
    for shag in shagi:
        if tek:
            smena = (
                shag["promptId"] is not None
                and tek[-1]["promptId"] is not None
                and shag["promptId"] != tek[-1]["promptId"]
            )
            if smena:
                soobshcheniya.append(tek)
                tek = []
        tek.append(shag)
    if tek:
        soobshcheniya.append(tek)
    return soobshcheniya


def Svod(temaFiltr=None, verh=10):
    stroki = []
    for katalog in sorted(KORENX.iterdir()):
        if not katalog.is_dir():
            continue
        if temaFiltr and temaFiltr not in katalog.name:
            continue
        for sessiya in sorted(katalog.glob("*.jsonl")):
            shagi = ShagiSessii(sessiya)
            if not shagi:
                continue
            soobshcheniya = SoobshcheniyaPoShagam(shagi)
            stroki.append(
                {
                    "tema": katalog.name,
                    "sessiya": sessiya.stem[:8],
                    "shagov": len(shagi),
                    "soobshcheniy": len(soobshcheniya),
                    "maxKontekst": max(s["kontekst"] for s in shagi),
                    "chtenie": sum(s["kontekst"] for s in shagi),
                    "cena": sum(s["cena"] for s in shagi),
                    "dorogoe": max(
                        (sum(s["cena"] for s in m), len(m)) for m in soobshcheniya
                    ),
                }
            )
    stroki.sort(key=lambda s: -s["cena"])
    print(f"{'тема':<42} {'сесс':<9} {'шагов':>6} {'сообщ':>6} "
          f"{'контекст макс':>14} {'цена':>9} {'дороже всего':>22}")
    for s in stroki[:verh]:
        cenaSoobshcheniya, shagovSoobshcheniya = s["dorogoe"]
        print(
            f"{s['tema'][:42]:<42} {s['sessiya']:<9} {s['shagov']:>6} "
            f"{s['soobshcheniy']:>6} {s['maxKontekst']/1000:>12.0f}т "
            f"{s['cena']:>8.2f}$ {cenaSoobshcheniya:>14.2f}$ / {shagovSoobshcheniya:>3} шаг."
        )
    itogCena = sum(s["cena"] for s in stroki)
    itogShagi = sum(s["shagov"] for s in stroki)
    print(f"\nвсего: {len(stroki)} сессий, {itogShagi} шагов, {itogCena:.2f}$")
    return stroki


def Kalibrovka():
    """Знаков русского текста на токен — по приросту контекста между шагами.

    Между двумя соседними шагами одного ответа контекст прирастает на выход
    модели и на результат инструмента. Знаки того и другого стенограмма хранит,
    токены прироста известны из `usage` — отношение и даёт оценку.
    """
    pary = []
    for katalog in sorted(KORENX.iterdir()):
        if not katalog.is_dir():
            continue
        for sessiya in katalog.glob("*.jsonl"):
            predKontekst = None
            predVyhod = 0
            predZapros = None
            znakov = 0
            for zapis in ReadZapisi(sessiya):
                tip = zapis.get("type")
                if tip == "assistant":
                    usage = (zapis.get("message") or {}).get("usage") or {}
                    if not usage:
                        continue
                    zapros = zapis.get("requestId")
                    if zapros is not None and zapros == predZapros:
                        continue
                    predZapros = zapros
                    kontekst = RazmerKonteksta(usage)
                    if predKontekst is not None:
                        # Прирост контекста — это выход прошлого шага плюс
                        # подложенное инструментами. Выход известен в токенах,
                        # поэтому вычитается, и остаётся чистая оценка.
                        prirost = kontekst - predKontekst - predVyhod
                        if znakov > 1000 and prirost > 200:
                            pary.append((znakov, prirost))
                    predKontekst = kontekst
                    predVyhod = usage.get("output_tokens", 0)
                    znakov = 0
                elif tip in ("user", "attachment") and predKontekst is not None:
                    znakov += len(json.dumps(zapis.get("message")
                                             or zapis.get("attachment"),
                                             ensure_ascii=False))
    if not pary:
        print("нечего калибровать: подходящих пар шагов не нашлось")
        return None
    # Берётся медиана, а не наклон по сумме произведений: в выборке есть пары
    # со сжатием и с повторно подложенными файлами, и они уводят наклон вниз
    # в разы (на нашей выборке 0.30 против медианы 2.48).
    otnosheniya = sorted(z / t for z, t in pary)
    mediana = otnosheniya[len(pary) // 2]
    print(f"пар шагов: {len(pary)}")
    print(f"знаков на токен (медиана): {mediana:.2f}")
    print(f"четверти: {otnosheniya[len(pary) // 4]:.2f} … "
          f"{otnosheniya[3 * len(pary) // 4]:.2f}")
    return mediana


def Shag(zapros, zapis, chtenie, vyhod):
    """Запись ответа модели для подставной стенограммы."""
    return {"type": "assistant", "requestId": zapros, "message": {"usage": {
        "input_tokens": 4, "cache_creation_input_tokens": zapis,
        "cache_read_input_tokens": chtenie, "output_tokens": vyhod}}}


# Первое сообщение — три шага: холодный кэш, потом два по тёплому. Первый шаг
# записан дважды с одним `requestId`: так стенограмма хранит размышление и
# вызов инструмента одной реплики. Второе сообщение — один шаг.
def Modelirovanie(shagi, potolok, svodka=2000):
    """Во что обошлись бы те же шаги при заданном потолке контекста.

    Модель грубая и нарочно: считаются чтение контекста и выход, запись кэша и
    остывание не моделируются — поэтому числа годятся для **сравнения**
    потолков между собой, а не как предсказание счёта. Сжатие считается так:
    на шаге, где контекст перевалил за потолок, платится чтение контекста и
    выход сводки, а дальше контекст идёт от сводки.
    """
    smeshchenie = 0          # сколько токенов унесли сжатия
    cena = 0.0
    szhatiy = 0
    for shag in shagi:
        kontekst = max(shag["kontekst"] - smeshchenie, svodka)
        if potolok and kontekst > potolok:
            cena += kontekst * CENA_CHTENIE + svodka * CENA_VYHOD
            szhatiy += 1
            smeshchenie += kontekst - svodka
            kontekst = svodka
        cena += kontekst * CENA_CHTENIE + shag["vyhod"] * CENA_VYHOD
    return cena, szhatiy


def ImyaTemy(imyaKataloga):
    """`-home-mokeeva-main-glavpryg-sayt` → `glavpryg-sayt`, корень → `main`."""
    koren = str(pathlib.Path(__file__).resolve().parent.parent).replace("/", "-")
    imya = imyaKataloga[len(koren):].lstrip("-")
    return (imya or "main")[:34]


def SvodModelirovaniya(temaFiltr=None, potolki=(0, 100_000, 150_000, 250_000)):
    """Сравнение потолков по стенограммам: во что обошлась бы та же работа."""
    print(f"{'тема':<34} {'шагов':>6} {'факт':>8} " +
          " ".join(f"{('без потолка' if p == 0 else str(p // 1000) + ' тыс.'):>14}"
                   for p in potolki))
    for katalog in sorted(KORENX.iterdir()):
        if not katalog.is_dir() or (temaFiltr and temaFiltr not in katalog.name):
            continue
        for sessiya in sorted(katalog.glob("*.jsonl")):
            shagi = ShagiSessii(sessiya)
            if len(shagi) < 50:
                continue
            fakt = sum(s["cena"] for s in shagi)
            stroka = f"{ImyaTemy(katalog.name):<34} {len(shagi):>6} {fakt:>7.0f}$ "
            for potolok in potolki:
                cena, szhatiy = Modelirovanie(shagi, potolok)
                stroka += f"{cena:>9.0f}$ /{szhatiy:>3} "
            print(stroka)
    print("\nстолбцы: цена по модели и число сжатий. Модель считает чтение и выход,")
    print("запись кэша и остывание — нет, поэтому сравнивать можно столбцы между")
    print("собой, а не с графой «факт».")


FIKTIVNAYA = [
    {"type": "user", "promptId": "p1", "message": {"content": "задание"}},
    Shag("r1", 100000, 0, 1000),
    Shag("r1", 100000, 0, 1000),
    {"type": "user", "promptId": "p1", "message": {"content": [{"type": "tool_result"}]}},
    Shag("r2", 2000, 100000, 500),
    {"type": "user", "promptId": "p1", "message": {"content": [{"type": "tool_result"}]}},
    Shag("r3", 1000, 102000, 500),
    {"type": "user", "promptId": "p2", "message": {"content": "второе задание"}},
    Shag("r4", 500, 103000, 200),
]


def Proverka():
    """Самопроверка: подставная стенограмма с известными числами."""
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False,
                                     encoding="utf-8") as fajl:
        for zapis in FIKTIVNAYA:
            fajl.write(json.dumps(zapis, ensure_ascii=False) + "\n")
        put = pathlib.Path(fajl.name)
    try:
        shagi = ShagiSessii(put)
    finally:
        put.unlink()

    oshibki = []

    # 0. Повтор одной реплики не считается вторым шагом.
    if len(shagi) != 4:
        oshibki.append(f"шагов {len(shagi)}, ждали 4")
    if len(shagi) < 4:
        print("НЕ СХОДИТСЯ:", oshibki[-1])
        print("самопроверка: падает")
        return 1

    # 1. Контекст холодного шага считается по записи кэша, а не по чтению.
    if shagi[0]["kontekst"] != 100004:
        oshibki.append(f"контекст первого шага {shagi[0]['kontekst']}, ждали 100004")

    # 2. Цена холодного шага — запись по $10/млн плюс выход.
    cenaZhdem = 100000 * CENA_ZAPIS + 4 * CENA_VHOD + 1000 * CENA_VYHOD
    if abs(shagi[0]["cena"] - cenaZhdem) > 1e-9:
        oshibki.append(f"цена первого шага {shagi[0]['cena']:.4f}, ждали {cenaZhdem:.4f}")

    # 3. Шаги режутся на сообщения по смене promptId: 3 + 1.
    razbienie = [len(m) for m in SoobshcheniyaPoShagam(shagi)]
    if razbienie != [3, 1]:
        oshibki.append(f"разбиение на сообщения {razbienie}, ждали [3, 1]")

    # 4. Цена ответа из трёх шагов — сумма шагов.
    # 1.025 (холодный шаг) + 0.0825 + 0.0735 — считано по ценам вручную.
    cenaOtveta = sum(s["cena"] for s in shagi[:3])
    if abs(cenaOtveta - 1.1811) > 0.001:
        oshibki.append(f"цена ответа {cenaOtveta:.4f}, ждали 1.1811")

    for stroka in oshibki:
        print("НЕ СХОДИТСЯ:", stroka)
    print("самопроверка: " + ("падает" if oshibki else "сходится"))
    return 1 if oshibki else 0


def main():
    razbor = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    razbor.add_argument("--svod", action="store_true", help="сводка по сессиям")
    razbor.add_argument("--tema", help="брать только каталоги с этой подстрокой")
    razbor.add_argument("--verh", type=int, default=10, help="сколько строк печатать")
    razbor.add_argument("--kalibrovka", action="store_true",
                        help="оценить знаки на токен")
    razbor.add_argument("--modelirovanie", action="store_true",
                        help="сравнить потолки контекста по стенограммам")
    razbor.add_argument("--proverka", action="store_true", help="самопроверка")
    dovody = razbor.parse_args()

    if dovody.proverka:
        return Proverka()
    if dovody.modelirovanie:
        SvodModelirovaniya(dovody.tema)
        return 0
    if dovody.kalibrovka:
        Kalibrovka()
        return 0
    if dovody.svod or not any(vars(dovody).values()):
        Svod(dovody.tema, dovody.verh)
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
