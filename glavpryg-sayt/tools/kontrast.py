#!/usr/bin/env python3
"""Замер контраста текста на стеклянных плашках — числом, а не на глаз.

    <venv>/bin/python glavpryg-sayt/tools/kontrast.py [адрес]
        [--shirina 1440] [--fon '#ffffff'] [--tekst '#ffffff']

Зачем отдельный инструмент. Плашки шапки и меню сделаны «стеклом»: полупрозрачная
заливка плюс размытие фона. Читаемость такой плашки зависит не от её цвета, а от
того, что за ней — на тёмном кадре белые буквы видны, на светлом небе исчезают.
Оценить это глазом нельзя, потому что картинка баннера меняется из админки.

⚠️ Меряется **чистое стекло**: всё содержимое плашки на время замера прячется.
Иначе в выборку попадают сами буквы, и худшим пикселем выходит текст на самом
себе — замер показывает 1 : 1 и выглядит как провал.

⚠️ Худший случай для белого текста — **самый светлый** пиксель за стеклом,
поэтому `--fon` позволяет подставить за баннер заведомо светлый цвет. Замер
без него говорит «как сейчас, на снимках заказчика», замер с ним — «как будет,
если в баннер поставят кадр со светлым небом».

⚠️ Чисто белый фон (`#ffffff`) подставлять бессмысленно: стекло с белой
заливкой на белом фоне и само становится белым, отношение выходит 1 : 1 на
любой вёрстке, и замер перестаёт о чём-либо говорить. Светлое небо — это
примерно `#dbeefc`, его и берём за худший правдоподобный случай.

Норма AA для обычного текста — 4,5 : 1, для крупного (от 18,66 px полужирного
или 24 px обычного) — 3 : 1.
"""

import argparse
import sys

from playwright.sync_api import sync_playwright

# Плашки ищутся по метке `data-steklo` в разметке, а не по классам заливки.
#
# ⚠️ Так сделано не для красоты. Сперва замер искал плашку по классу
# `bg-white/10` — и как только заливку поменяли на тёмную, перестал находить
# что-либо вовсе. Напечатал «не дотянули 0» на пустой выборке: зелёный
# результат, который ничего не доказывает, но выглядит как доказательство.
METKA = "[data-steklo]"

# Насколько отступить внутрь от края плашки: сглаженная граница — смесь стекла
# с фоном, а не стекло (см. `zamerit`).
OTSTUP = 3

STRANICY = [
    ("главная", ""),
    ("тандем", "services/tandem"),
    ("самостоятельный", "services/samostoyatelnyy"),
    ("обучение", "services/obuchenie"),
    ("спортивные", "services/sportivnye"),
    ("VR-тренажёр", "vr-trainer"),
    ("сертификат", "certificate"),
]

# Прячем содержимое плашки, оставляя её фон и размытие.
SPRYATAT = """(el) => {
  el.dataset.zamer = '1';
  for (const d of el.querySelectorAll('*')) { d.style.visibility = 'hidden'; }
}"""

VERNUT = """(el) => {
  for (const d of el.querySelectorAll('*')) { d.style.visibility = ''; }
  delete el.dataset.zamer;
}"""


def svetlota(r: int, g: int, b: int) -> float:
    """Относительная яркость цвета по WCAG."""
    def kanal(z: int) -> float:
        d = z / 255
        return d / 12.92 if d <= 0.03928 else ((d + 0.055) / 1.055) ** 2.4

    return 0.2126 * kanal(r) + 0.7152 * kanal(g) + 0.0722 * kanal(b)


def otnoshenie(a: float, b: float) -> float:
    svetlee, temnee = max(a, b), min(a, b)
    return (svetlee + 0.05) / (temnee + 0.05)


def zamerit(plashka, svet_teksta: float) -> float | None:
    """Худшее (наименьшее) отношение контраста текста к стеклу плашки."""
    from PIL import Image
    import io

    # ⚠️ Плашку, скрытую на этой ширине, мерить нельзя: кнопки телефона и меню
    # есть только на узком экране (`lg:hidden`), и попытка снять их на широком
    # вешала замер до таймаута — выглядело как поломка страницы.
    if not plashka.is_visible():
        return None

    # Скругление берём у самой плашки: `rounded-full` даёт радиус в полразмера,
    # `rounded-2xl` — 16 px, и углы у них разной величины.
    radius = plashka.evaluate(
        "(el) => parseFloat(getComputedStyle(el).borderTopLeftRadius) || 0"
    )

    plashka.evaluate(SPRYATAT)
    plashka.page.wait_for_timeout(350)   # дать размытию перерисоваться
    snimok = plashka.screenshot()
    plashka.evaluate(VERNUT)

    im = Image.open(io.BytesIO(snimok)).convert("RGB")
    sh, vy = im.size

    # ⚠️ Углы скруглённой плашки в снимок попадают, но стеклом не являются:
    # там сквозит сам баннер. На круглых кнопках шапки (40×40, `rounded-full`)
    # эти углы и давали «худший пиксель» — замер показывал 2,4 : 1 на кнопке,
    # у которой внутри всё в порядке, и обвинял продукт вместо оснастки.
    # Поэтому берём только точки внутри скруглённого прямоугольника.
    #
    # ⚠️ И не по самой границе, а отступив от неё: край плашки сглажен, и
    # крайний ряд пикселей — смесь стекла с тем, что за ним. На тёмном баннере
    # эта смесь тёмная и в глаза не бросается, а на светлом небе даёт ровно
    # 2,11 : 1 — одинаково на всех страницах, потому что меряется не вёрстка, а
    # собственная кайма снимка. Сужаем фигуру на OTSTUP пикселей со всех сторон.
    skruglenie = min(radius, sh / 2, vy / 2)
    vnutrennee = max(skruglenie - OTSTUP, 0.0)

    def vnutri(x: float, y: float) -> bool:
        dx = max(OTSTUP + vnutrennee - x, x - (sh - OTSTUP - vnutrennee), 0.0)
        dy = max(OTSTUP + vnutrennee - y, y - (vy - OTSTUP - vnutrennee), 0.0)
        return (x >= OTSTUP and y >= OTSTUP and x <= sh - OTSTUP and y <= vy - OTSTUP
                and dx * dx + dy * dy <= vnutrennee * vnutrennee)

    khudshee = None
    for y in range(0, vy, 2):
        for x in range(0, sh, 2):
            if not vnutri(x + 0.5, y + 0.5):
                continue
            o = otnoshenie(svet_teksta, svetlota(*im.getpixel((x, y))))
            if khudshee is None or o < khudshee:
                khudshee = o
    return khudshee


def main() -> int:
    razbor = argparse.ArgumentParser()
    razbor.add_argument("adres", nargs="?", default="https://mokeevasky.ru/glavpryg")
    razbor.add_argument("--shirina", type=int, default=1440)
    razbor.add_argument("--fon", default=None,
                        help="подставить за баннер этот цвет (худший случай, например #ffffff)")
    razbor.add_argument("--tekst", default="#ffffff", help="цвет текста плашки")
    razbor.add_argument("--norma", type=float, default=4.5)
    dovody = razbor.parse_args()

    osnova = dovody.adres.rstrip("/")
    t = dovody.tekst.lstrip("#")
    svet_teksta = svetlota(int(t[0:2], 16), int(t[2:4], 16), int(t[4:6], 16))

    bed = 0
    zamerov = 0
    with sync_playwright() as p:
        br = p.chromium.launch()
        kontekst = br.new_context(viewport={"width": dovody.shirina, "height": 950})
        for imya, put in STRANICY:
            st = kontekst.new_page()
            st.goto(f"{osnova}/{put}", wait_until="load", timeout=60000)
            st.wait_for_timeout(2500)

            if dovody.fon:
                # Белое небо — худший случай для белых букв. Красим всё, что
                # лежит за шапкой: сами картинки баннера и его подложку.
                st.evaluate(
                    """(cvet) => {
                        for (const el of document.querySelectorAll('img, [class*=bg-], section, div')) {
                            const st = getComputedStyle(el);
                            if (st.backgroundImage !== 'none' || el.tagName === 'IMG') {
                                el.style.backgroundImage = 'none';
                                el.style.background = cvet;
                                if (el.tagName === 'IMG') { el.style.visibility = 'hidden'; }
                            }
                        }
                        document.body.style.background = cvet;
                    }""",
                    dovody.fon,
                )
                st.wait_for_timeout(600)

            plashki = st.locator(METKA)
            vsego = plashki.count()
            if vsego == 0:
                # Не беда: часть страниц носит светлую шапку с тёмным текстом
                # (`nav-light.blade.php`), стекла на них нет. Беда — если
                # замеров не вышло **ни одного**, это проверяется ниже.
                print(f"       {imya:16s} стеклянных плашек нет (светлая шапка)")
            for i in range(vsego):
                plashka = plashki.nth(i)
                nazvanie = plashka.get_attribute("data-steklo") or "плашка"
                znachenie = zamerit(plashka, svet_teksta)
                if znachenie is None:
                    continue
                plokho = znachenie < dovody.norma
                bed += 1 if plokho else 0
                zamerov += 1
                print(f"{'БЕДА  ' if plokho else 'ок    '} {imya:16s} {nazvanie:16s} "
                      f"{znachenie:5.2f} : 1")
            st.close()
        br.close()

    # ⚠️ Пустая выборка — это беда, а не успех. Без этой строки замер однажды
    # напечатал «не дотянули 0», не померив ничего: плашки сменили класс.
    if zamerov == 0:
        print("\nБЕДА   не сделано ни одного замера — проверьте метки data-steklo")
        return 1

    print(f"\nзамеров {zamerov}, норма {dovody.norma} : 1, не дотянули {bed}")
    return 1 if bed else 0


if __name__ == "__main__":
    sys.exit(main())
