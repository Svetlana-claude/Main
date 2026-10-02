#!/usr/bin/env python3
"""Подготовить присланные снимки к выкладке в фотоархив сайта.

Заказчик присылает съёмку как есть: кадры с телефона с поворотом в EXIF,
выгрузки из Illustrator в CMYK, файлы по 10 МБ и имена вида
`UvXc2jrzqj9kkxPxspnnswWXEaNYILA4_X__T-p7ps2.jpg`. В архив такое класть нельзя:
CMYK браузеры показывают вкривь, десятимегабайтный кадр грузится в слайдере
секундами, а по папкам архива ходят руками, и хэш в имени искать нечем.

    /usr/bin/python3 glavpryg-sayt/tools/podgotovit-foto.py <откуда> <куда>
        [--storona 1920] [--kachestvo 85]

Ждёт на входе папку с подпапками подразделов — русскими (`виар`,
`самостоятельный`, `спортивные`, `тандем`) или уже латинскими. На выходе
кладёт в `<куда>/<подраздел>/` кадры с именами `<подраздел>-01.jpg` и дальше
по порядку.

⚠️ Исходники не трогаются. Уменьшенное — для сайта, оригиналы остаются там,
где лежали.
"""

import argparse
import pathlib
import sys

from PIL import Image, ImageOps

# Папка от заказчика → подраздел фотоархива. Имена подразделов те же, что в
# App\Models\GalleryItem: по ним же называются папки на сервере.
PODRAZDELY = {
    "виар": "vr",
    "самостоятельный": "samostoyatelnyy",
    "спортивные": "sportivnyy",
    "спортивный": "sportivnyy",
    "тандем": "tandem",
    "vr": "vr",
    "samostoyatelnyy": "samostoyatelnyy",
    "sportivnyy": "sportivnyy",
    "tandem": "tandem",
}

RASSHIRENIYA = {".jpg", ".jpeg", ".png", ".webp"}


def podgotovit(fayl: pathlib.Path, kuda: pathlib.Path, storona: int, kachestvo: int) -> int:
    """Один кадр: поворот по EXIF, перевод в RGB, уменьшение, запись. Вернёт размер."""
    with Image.open(fayl) as im:
        # Телефон пишет кадр как снят, а поворот держит отдельной меткой EXIF.
        # Метку при пересохранении теряем, поэтому поворачиваем пиксели сами.
        im = ImageOps.exif_transpose(im)

        # CMYK — это из типографской вёрстки. Браузеры показывают такой JPEG
        # кто во что горазд, вплоть до вывернутых цветов.
        if im.mode != "RGB":
            im = im.convert("RGB")

        if max(im.size) > storona:
            im.thumbnail((storona, storona), Image.LANCZOS)

        im.save(kuda, "JPEG", quality=kachestvo, optimize=True, progressive=True)

    return kuda.stat().st_size


def main() -> int:
    razbor = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    razbor.add_argument("otkuda", type=pathlib.Path, help="папка с подпапками подразделов")
    razbor.add_argument("kuda", type=pathlib.Path, help="куда сложить подготовленное")
    razbor.add_argument("--storona", type=int, default=1920,
                        help="наибольшая сторона кадра, точек (по умолчанию 1920)")
    razbor.add_argument("--kachestvo", type=int, default=85, help="качество JPEG (по умолчанию 85)")
    dovody = razbor.parse_args()

    if not dovody.otkuda.is_dir():
        print(f"Нет такой папки: {dovody.otkuda}", file=sys.stderr)
        return 1

    neponyatnye = []
    vsego = 0
    for papka in sorted(p for p in dovody.otkuda.iterdir() if p.is_dir()):
        razdel = PODRAZDELY.get(papka.name.lower())
        if razdel is None:
            neponyatnye.append(papka.name)
            continue

        fayly = sorted(f for f in papka.iterdir()
                       if f.is_file() and f.suffix.lower() in RASSHIRENIYA)
        mesto = dovody.kuda / razdel
        mesto.mkdir(parents=True, exist_ok=True)

        print(f"== {papka.name} → {razdel} ({len(fayly)} шт.)")
        for n, fayl in enumerate(fayly, 1):
            tsel = mesto / f"{razdel}-{n:02d}.jpg"
            bylo = fayl.stat().st_size
            stalo = podgotovit(fayl, tsel, dovody.storona, dovody.kachestvo)
            print(f"   {tsel.name:24s} {bylo / 1024:7.0f} КБ → {stalo / 1024:6.0f} КБ   {fayl.name[:40]}")
            vsego += 1

    if neponyatnye:
        # Молча пропустить папку нельзя: снимки из неё просто не доедут до сайта.
        print(f"\n⚠️ Непонятные папки, пропущены: {', '.join(neponyatnye)}", file=sys.stderr)

    print(f"\nПодготовлено кадров: {vsego}")
    return 2 if neponyatnye else 0


if __name__ == "__main__":
    sys.exit(main())
