"""Сборка шрифтов для выдачи дизайнеру: качает TTF из репозитория Google Fonts.

В макете шрифты подключены как woff2-подмножества (`maket/fonts/`) — браузеру
этого достаточно, но в Illustrator ставятся системные TTF. Скрипт кладёт
переменные (variable) начертания и лицензии в `downloads/ai/fonts/`, откуда
дизайнер их устанавливает. Файлы не версионируются: это выдача, а не исходник.

Запуск:  .venv/bin/python maket/fetch_fonts.py
"""
import os
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "downloads", "ai", "fonts")
BASE = "https://raw.githubusercontent.com/google/fonts/main/ofl"

# Семейство → файлы в репозитории Google Fonts (все под лицензией OFL)
FAMILIES = {
    "manrope": ["Manrope[wght].ttf", "OFL.txt"],
    "oswald": ["Oswald[wght].ttf", "OFL.txt"],
    "jetbrainsmono": ["JetBrainsMono[wght].ttf", "JetBrainsMono-Italic[wght].ttf", "OFL.txt"],
    "caveat": ["Caveat[wght].ttf", "OFL.txt"],
    "unbounded": ["Unbounded[wght].ttf", "OFL.txt"],
    "rubik": ["Rubik[wght].ttf", "Rubik-Italic[wght].ttf", "OFL.txt"],
}


def Fetch(family, name):
    url = f"{BASE}/{family}/{urllib.parse.quote(name)}"
    # лицензии одноимённые, поэтому раскладываем по папкам семейств
    path = os.path.join(OUT, family, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with urllib.request.urlopen(url, timeout=60) as r, open(path, "wb") as f:
        f.write(r.read())
    return os.path.getsize(path)


if __name__ == "__main__":
    total = 0
    for family, names in FAMILIES.items():
        for name in names:
            size = Fetch(family, name)
            total += size
            print(f"{family}/{name} — {size // 1024} КБ")
    print(f"Итого {total // 1024} КБ в {os.path.relpath(OUT, HERE)}")
