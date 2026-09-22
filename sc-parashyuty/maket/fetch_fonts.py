"""Сборка шрифтов для выдачи дизайнеру: TTF тех начертаний, что стоят в макете.

В вёрстке шрифты подключены как woff2 (`maket/fonts/`) — браузеру этого хватает,
но в систему и в Illustrator ставятся TTF. Google Fonts отдаёт семейства одним
вариативным файлом; такой файл ставится целиком, и дизайнер сам ищет нужный вес,
а часть программ вариативные оси не понимает вовсе. Поэтому скрипт скачивает
вариативные исходники и нарезает из них статические начертания — ровно те, что
перечислены в `fonts.css` и стоят в вёрстке.

Запуск:  .venv/bin/python maket/fetch_fonts.py
Выход:   downloads/ai/fonts/*.ttf и лицензии OFL (файлы не версионируются)
"""
import os
import urllib.parse
import urllib.request
import zipfile

from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "downloads", "ai", "fonts")
BASE = "https://raw.githubusercontent.com/google/fonts/main/ofl"

# Общепринятые названия начертаний по весу
STYLE = {400: "Regular", 500: "Medium", 600: "SemiBold", 700: "Bold",
         800: "ExtraBold", 900: "Black"}

# Семейство → откуда брать и какие начертания нарезать.
# Веса — те же, что подключены в `maket/fonts.css`.
FAMILIES = [
    ("Manrope", "manrope", "Manrope[wght].ttf", [400, 600, 800]),
    ("Oswald", "oswald", "Oswald[wght].ttf", [500, 700]),
    ("JetBrains Mono", "jetbrainsmono", "JetBrainsMono[wght].ttf", [400, 700]),
    ("Caveat", "caveat", "Caveat[wght].ttf", [500]),
    ("Unbounded", "unbounded", "Unbounded[wght].ttf", [400, 600, 800]),
    ("Rubik", "rubik", "Rubik[wght].ttf", [900]),
    ("Rubik", "rubik", "Rubik-Italic[wght].ttf", [900]),
]


def Download(family, name, path):
    url = f"{BASE}/{family}/{urllib.parse.quote(name)}"
    with urllib.request.urlopen(url, timeout=60) as r, open(path, "wb") as f:
        f.write(r.read())


def SetNames(font, family, style, weight, italic):
    """Прописывает имена начертания.

    Своими руками, а не `updateFontNames`: тот берёт названия из таблицы STAT,
    а в ней описаны не все веса — на Caveat 500 он обрывается с ошибкой.
    """
    table = font["name"]
    # В коротких именах (1 и 2) семейством зовётся только четвёрка стандартных
    # начертаний, остальные веса уходят в имя семейства: так их различают
    # программы, показывающие лишь «обычный / полужирный / курсив».
    if style in ("Regular", "Bold", "Italic", "Bold Italic"):
        short_family, short_style = family, style
    else:
        short_family = f"{family} {style.replace('Italic', '').strip()}"
        short_style = "Italic" if italic else "Regular"
    full = f"{family} {style}"
    for name_id, value in ((1, short_family), (2, short_style), (3, f"{full}: 2026"),
                           (4, full), (6, f"{family}-{style.replace(' ', '')}"),
                           (16, family), (17, style)):
        table.setName(value, name_id, 3, 1, 0x409)  # windows, unicode, en-us
        table.setName(value, name_id, 1, 0, 0)      # macintosh, roman
    font["OS/2"].usWeightClass = weight
    bold = weight >= 700
    # биты «курсив» (0), «полужирный» (5) и «обычный» (6) взаимно исключают друг
    # друга, поэтому сперва гасим все три и только потом ставим нужный
    font["OS/2"].fsSelection = ((font["OS/2"].fsSelection & ~0b1100001)
                                | (0b100000 if bold else 0) | (0b1 if italic else 0)
                                | (0 if (bold or italic) else 0b1000000))
    font["head"].macStyle = (0b1 if bold else 0) | (0b10 if italic else 0)


def Cut(source, weight, family, style, italic, path):
    """Вырезает из вариативного шрифта одно начертание."""
    font = TTFont(source)
    axes = {a.axisTag: a.defaultValue for a in font["fvar"].axes}
    axes["wght"] = weight
    inst = instantiateVariableFont(font, axes, inplace=True)
    SetNames(inst, family, style, weight, italic)
    inst.save(path)
    return os.path.getsize(path)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    work = os.path.join(OUT, "_variable")
    os.makedirs(work, exist_ok=True)
    for name, slug, file_name, weights in FAMILIES:
        source = os.path.join(work, file_name)
        if not os.path.exists(source):
            Download(slug, file_name, source)
        plain = name.replace(" ", "")  # в именах файлов семейство без пробелов
        license_path = os.path.join(OUT, f"OFL-{plain}.txt")
        if not os.path.exists(license_path):
            Download(slug, "OFL.txt", license_path)
        italic = "Italic" in file_name
        for weight in weights:
            style = STYLE[weight] + (" Italic" if italic else "")
            path = os.path.join(OUT, f"{plain}-{style.replace(' ', '')}.ttf")
            size = Cut(source, weight, name, style, italic, path)
            print(f"{os.path.basename(path)} — {size // 1024} КБ")
    for left in os.listdir(work):
        os.remove(os.path.join(work, left))
    os.rmdir(work)
    # архив одним файлом: тринадцать шрифтов по одному качать неудобно
    archive = os.path.join(OUT, "..", "..", "shrifty-skycenter.zip")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in sorted(os.listdir(OUT)):
            zf.write(os.path.join(OUT, name), os.path.join("shrifty-skycenter", name))
    print(f"Готово: {OUT}")
    print(f"Архив: {os.path.normpath(archive)} — "
          f"{os.path.getsize(archive) // 1024} КБ")
