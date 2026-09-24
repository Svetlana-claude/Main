"""Догрузка веб-шрифтов для страницы шрифтовых вариантов.

`fonts.css` собран вручную под первые три варианта и трогать его незачем:
там ровно те начертания, что стоят в `index.html`, и на них завязана выгрузка
в Illustrator. Новым вариантам сертификата нужны другие семейства, поэтому они
живут отдельно — в `fonts-varianty.css`.

Скрипт спрашивает у Google Fonts обычный CSS (как браузер), оставляет из него
только подмножества `cyrillic` и `latin`, скачивает woff2 рядом, в `fonts/`,
и переписывает ссылки на локальные. Интернет нужен только здесь: страница
потом открывается без сети.

Запуск:  .venv/bin/python maket/fetch_web_fonts.py
Выход:   maket/fonts/*.woff2 и maket/fonts-varianty.css
"""
import os
import re
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
FONTS = os.path.join(HERE, "fonts")
CSS = os.path.join(HERE, "fonts-varianty.css")
API = "https://fonts.googleapis.com/css2"

# Без браузерного User-Agent Google отдаёт ttf вместо woff2
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/120.0.0.0 Safari/537.36")

# Семейство → начертания. Только то, что стоит на странице вариантов.
FAMILIES = [
    ("IBM Plex Sans", [400, 500, 600]),
    ("IBM Plex Mono", [400, 500]),
    ("Fira Sans Condensed", [500, 700]),
    ("Fira Sans", [400, 500]),
    ("Fira Mono", [400, 500]),
    ("PT Serif", [400, 700]),
    ("PT Sans", [400, 700]),
    ("Golos Text", [400, 600, 800]),
    ("Inter", [400, 600]),
]

# Блок @font-face целиком и отдельные его части
FACE = re.compile(r"/\*\s*(?P<subset>[\w-]+)\s*\*/\s*@font-face\s*\{(?P<body>[^}]+)\}")
SRC = re.compile(r"url\((https://[^)]+\.woff2)\)")
KEEP = ("cyrillic", "latin")


def Fetch(family, weights):
    query = urllib.parse.urlencode(
        {"family": f"{family}:wght@{';'.join(str(w) for w in weights)}",
         "display": "swap"}, safe=":;@")
    request = urllib.request.Request(f"{API}?{query}", headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=60) as r:
        return r.read().decode("utf-8")


def Download(url, path):
    with urllib.request.urlopen(url, timeout=60) as r, open(path, "wb") as f:
        f.write(r.read())


if __name__ == "__main__":
    os.makedirs(FONTS, exist_ok=True)
    blocks = ["/* Шрифты Google Fonts (OFL) для страницы вариантов сертификата.",
              "   Собирается maket/fetch_web_fonts.py — руками не править. */"]
    total = 0
    for family, weights in FAMILIES:
        css = Fetch(family, weights)
        slug = family.lower().replace(" ", "-")
        for face in FACE.finditer(css):
            subset = face.group("subset")
            if subset not in KEEP:
                continue
            body = face.group("body")
            weight = re.search(r"font-weight:\s*(\d+)", body).group(1)
            name = f"{slug}-{weight}-{subset}.woff2"
            path = os.path.join(FONTS, name)
            if not os.path.exists(path):
                Download(SRC.search(body).group(1), path)
                total += 1
            body = SRC.sub(f"url(fonts/{name})", body)
            # font-stretch у переменных шрифтов мешает подбору начертания
            body = re.sub(r"\s*font-stretch:[^;]+;", "", body)
            blocks.append("@font-face {" + body.rstrip() + "\n}")
        print(f"{family}: {', '.join(str(w) for w in weights)}")
    with open(CSS, "w", encoding="utf-8") as f:
        f.write("\n".join(blocks) + "\n")
    print(f"Скачано файлов: {total}. Стили: {os.path.relpath(CSS, HERE)}")
