"""Перевод шрифтов макета из вариативных в статические начертания.

Зачем. Google Fonts отдаёт woff2 как вариативные шрифты (таблицы `fvar`/`gvar`).
Браузеру это безразлично, но при печати в PDF движок Chromium не умеет встраивать
такой шрифт и выкладывает буквы как Type 3 — процедуры рисования. В Illustrator
такой текст не редактируется. Статический инстанс на нужном весе встраивается
как обычный TrueType, и текст остаётся текстом.

Скрипт вырезает из каждого файла `fonts/*.woff2` один вес — тот, что указан в
имени файла, — и перезаписывает файл на месте. Начертание не меняется: вес тот
же, что и был выставлен в `fonts.css`.

Запуск:  .venv/bin/python maket/static_fonts.py
"""
import os
import re

from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

HERE = os.path.dirname(os.path.abspath(__file__))
FONTS = os.path.join(HERE, "fonts")


def Weight(name):
    """Вес из имени файла: `jetbrains-mono-400-cyrillic.woff2` → 400."""
    m = re.search(r"-(\d{3})-", name)
    return int(m.group(1)) if m else None


if __name__ == "__main__":
    changed = 0
    for name in sorted(os.listdir(FONTS)):
        if not name.endswith(".woff2"):
            continue
        path = os.path.join(FONTS, name)
        font = TTFont(path)
        if "fvar" not in font:
            print(f"{name} — уже статический")
            continue
        weight = Weight(name)
        # остальные оси (например, ширина) фиксируем на их значении по умолчанию
        axes = {a.axisTag: a.defaultValue for a in font["fvar"].axes}
        if weight is not None and "wght" in axes:
            axes["wght"] = weight
        before = os.path.getsize(path)
        inst = instantiateVariableFont(font, axes, inplace=True, updateFontNames=True)
        inst.flavor = "woff2"
        inst.save(path)
        changed += 1
        print(f"{name} — wght {axes.get('wght', '—')}, {before // 1024} → "
              f"{os.path.getsize(path) // 1024} КБ")
    print(f"Переведено файлов: {changed}")
