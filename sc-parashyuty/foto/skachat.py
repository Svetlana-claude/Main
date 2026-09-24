"""Скачивание фотографий для сопроводительного письма.

Сами файлы в git не лежат (правило 2 — бинарников в репозитории не держим),
поэтому берутся заново с Викисклада одной командой. Отобраны только снимки
в общественном достоянии и под CC0: их можно печатать в коммерческой выдаче
без разрешений и без указания автора. Подписи и лицензии — в `istochniki.md`,
его же повторяет раздел «Фотографии» письма.

Запуск:  .venv/bin/python foto/skachat.py
Выход:   foto/*.jpg
"""
import os
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
API = "https://commons.wikimedia.org/wiki/Special:FilePath/"

# имя файла у нас → имя файла на Викискладе
PHOTOS = {
    # Фотографии Котельникова в свободных лицензиях нет: на Викискладе только
    # мемориальные доски под CC BY-SA. Берём юбилейную марку — она в
    # общественном достоянии и показывает и его самого, и ранцевый РК-1.
    "kotelnikov-marka.jpg": "2012. Марка России 1619m.jpg",
    "minov-moshkovskiy.jpg": "Леонид Минов и Яков Мошковский.jpg",
    "kittinger-1960.jpg": "Kittinger-jump.jpg",
    "tandem.jpg": "Skydive Tandem jump.jpg",
    "otdelenie.jpg": "Parachuting at the Lublin-Radawiec airfield, 2022 03.jpg",
    "raskrytie.jpg": "Parachuting at the Lublin-Radawiec airfield, 2022 02.jpg",
}

# Викисклад отдаёт файл только с внятным User-Agent, иначе 403
HEADERS = {"User-Agent": "SkyCenter-docs/1.0 (info@skycenter.su)"}


def Download(source, path, width=1100):
    url = API + urllib.parse.quote(source) + f"?width={width}"
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=60) as r, open(path, "wb") as f:
        f.write(r.read())


if __name__ == "__main__":
    for name, source in PHOTOS.items():
        path = os.path.join(HERE, name)
        Download(source, path)
        print(f"{name} — {os.path.getsize(path) // 1024} КБ")
