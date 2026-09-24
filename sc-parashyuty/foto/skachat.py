"""Скачивание фотографий для сопроводительного письма.

Сами файлы в git не лежат (правило 2 — бинарников в репозитории не держим),
поэтому берутся заново одной командой. Источников два:

* **Свой сайт** `главпрыг.рф` — снимки дропзоны: VR-тренажёр, тандем, полёт
  под куполом, аэродром с высоты. Это материалы заказчика, они и должны стоять
  в письме: чужой аэродром в рассказе о своём выглядит подлогом.
* **Викисклад** — только исторические кадры к разделу «Истории», и только в
  общественном достоянии: их можно печатать в коммерческой выдаче без
  разрешений и без указания автора.

Подписи и лицензии — в `istochniki.md`, его же повторяет раздел «Фотографии»
письма.

Запуск:  .venv/bin/python foto/skachat.py
Выход:   foto/*.jpg
"""
import io
import os
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
COMMONS = "https://commons.wikimedia.org/wiki/Special:FilePath/"

# Фотографии заказчика: имя файла у нас → адрес на сайте главпрыг.рф.
# Часть исходников — PNG, поэтому всё приводится к JPEG: так снимки попадают
# под `.gitignore` (`foto/*.jpg`) и не утяжеляют PDF.
SVOI = {
    # VR-очки — заставка к разделу о наземной подготовке
    "vr-ochki.jpg":
        "https://static.tildacdn.com/tild3536-3431-4964-a633-383131356565/orig.jpg",
    # сам тренажёр: подвесная система, шлем, клеванты в руках
    "vr-trenazher.jpg":
        "https://static.tildacdn.com/tild6463-3663-4738-b233-363638383238/noroot.png",
    # тот же кадр целиком — виден ноутбук инструктора с картой аэродрома
    "vr-instruktor.jpg":
        "https://static.tildacdn.com/tild3235-6364-4031-b230-386663643839/"
        "photo_2026-02-04_16-.jpg",
    "tandem-svobodnoe-padenie.jpg":
        "https://static.tildacdn.com/tild3563-3638-4164-a335-363830306361/"
        "69680806_13027973832.jpg",
    "svobodnoe-padenie-gruppa.jpg":
        "https://static.tildacdn.com/tild3236-3039-4561-b834-653034626664/"
        "photo_2026-02-04_15-.jpg",
    "pod-kupolom.jpg":
        "https://static.tildacdn.com/tild3039-3430-4433-b862-313134313139/"
        "photo_2026-02-04_16-.jpg",
    "posle-prizemleniya.jpg":
        "https://static.tildacdn.com/tild3931-6563-4039-a537-396330336665/IMG_3252.jpg",
    "aerodrom-s-vysoty.jpg":
        "https://static.tildacdn.com/tild3239-6662-4834-a565-393237343965/"
        "photo_2026-02-04_15-.jpg",
}

# Историческое: имя файла у нас → имя файла на Викискладе
COMMONS_PHOTOS = {
    # Фотографии Котельникова в свободных лицензиях нет: на Викискладе только
    # мемориальные доски под CC BY-SA. Берём юбилейную марку — она в
    # общественном достоянии и показывает и его самого, и ранцевый РК-1.
    "kotelnikov-marka.jpg": "2012. Марка России 1619m.jpg",
    "minov-moshkovskiy.jpg": "Леонид Минов и Яков Мошковский.jpg",
    "kittinger-1960.jpg": "Kittinger-jump.jpg",
}

# И Викисклад, и Tilda отдают файл только с внятным User-Agent, иначе 403
HEADERS = {"User-Agent": "SkyCenter-docs/1.0 (info@skycenter.su)"}


def Fetch(url):
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=60) as r:
        return r.read()


def SaveJpeg(data, path, width=1400):
    """Кладёт снимок как JPEG, уменьшив по ширине: в письме шире не нужно."""
    from PIL import Image

    image = Image.open(io.BytesIO(data))
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    if image.width > width:
        height = round(image.height * width / image.width)
        image = image.resize((width, height), Image.LANCZOS)
    image.save(path, "JPEG", quality=86, optimize=True)


if __name__ == "__main__":
    for name, url in SVOI.items():
        path = os.path.join(HERE, name)
        SaveJpeg(Fetch(url), path)
        print(f"{name} — {os.path.getsize(path) // 1024} КБ (главпрыг.рф)")
    for name, source in COMMONS_PHOTOS.items():
        path = os.path.join(HERE, name)
        url = COMMONS + urllib.parse.quote(source) + "?width=1100"
        open(path, "wb").write(Fetch(url))
        print(f"{name} — {os.path.getsize(path) // 1024} КБ (Викисклад)")
