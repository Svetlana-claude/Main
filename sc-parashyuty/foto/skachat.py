"""Скачивание фотографий для сопроводительного письма.

Сами файлы в git не лежат (правило 2 — бинарников в репозитории не держим),
поэтому берутся заново одной командой. Источников два:

* **Свой сайт** `главпрыг.рф` — снимки дропзоны: VR-тренажёр, тандемы,
  самостоятельный прыжок, аэродром. Это материалы заказчика, они и должны
  стоять в письме: чужой аэродром в рассказе о своём выглядит подлогом.
* **Викисклад** — только исторические кадры к разделу «Истории», и только в
  общественном достоянии: их можно печатать в коммерческой выдаче без
  разрешений и без указания автора.

⚠️ Каждый кадр в письме встречается **один раз**. Прежний набор этим правилом
грешил: `vr-trenazher.jpg` был обрезкой того же снимка, что и `vr-podveska.jpg`,
и в PDF один и тот же момент занятия показывался дважды. Обрезка убрана,
вместо неё взят другой кадр из зала — `vr-zanyatie.jpg`. Всего на сайте
нашлось **три** разных снимка тренажёра, все три в письме и стоят.

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
TILDA = "https://static.tildacdn.com/"

# Фотографии заказчика: имя файла у нас → адрес на сайте главпрыг.рф.
# Часть исходников — PNG, поэтому всё приводится к JPEG: так снимки попадают
# под `.gitignore` (`foto/*.jpg`) и не утяжеляют PDF.
SVOI = {
    # --- VR-тренажёр: три разных кадра, повторов нет -------------------
    # шлем крупно — заставка раздела
    "vr-ochki.jpg":
        "tild3536-3431-4964-a633-383131356565/orig.jpg",
    # запас: зал целиком — участница в подвесной системе, инструктор со шлемом,
    # ноутбук с картинкой из шлема. В письме не стоит: шлема на участнице
    # в кадре не видно, рядом с крупным планом очков снимок читался «не про VR»
    "vr-zanyatie.jpg":
        "tild3234-3931-4333-b639-666265376466/photo_2026-02-04_16-.jpg",
    # снизу из-под подвесной системы: поза та же, что под куполом
    "vr-podveska.jpg":
        "tild3235-6364-4031-b230-386663643839/photo_2026-02-04_16-.jpg",

    # --- Тандем --------------------------------------------------------
    # заставка письма
    "tandem-svobodnoe-padenie.jpg":
        "tild3563-3638-4164-a335-363830306361/69680806_13027973832.jpg",
    # запас: заход на приземление, встречают на поле
    "tandem-prizemlenie.jpg":
        "tild3265-6632-4962-a463-393666336364/uiGzg7ulM6c.jpg",
    # запас: камера на штанге в руке инструктора, штанга в кадре
    "tandem-kamera-instruktora.jpg":
        "tild6366-6535-4339-a639-353862653634/cAhGjU4tU4Q.jpg",
    # единственный снимок раздела: оператор летит рядом и снимает со стороны
    "tandem-operator.jpg":
        "tild3730-3539-4361-b336-316537663964/14072883_16696129707.jpg",

    # --- Самостоятельный прыжок и обучение -----------------------------
    # отделение со стабилизирующим парашютом (снимок обрезан слева:
    # на исходнике поверх кадра лежит подпись с другой страницы сайта)
    "stabilizaciya.jpg":
        "tild3732-3134-4135-a334-666636363536/photo_2026-02-13_13-.jpg",
    "svobodnoe-padenie-gruppa.jpg":
        "tild3236-3039-4561-b834-653034626664/photo_2026-02-04_15-.jpg",
    # запас: пункт об инструкторах в письме идёт без фотографий
    "instruktor-kiselev.jpg":
        "tild3965-3065-4661-a136-353038626634/kiselev-da.jpeg",

    # --- День на аэродроме ---------------------------------------------
    "pod-kupolom.jpg":
        "tild3039-3430-4433-b862-313134313139/photo_2026-02-04_16-.jpg",
    "posle-prizemleniya.jpg":
        "tild3931-6563-4039-a537-396330336665/IMG_3252.jpg",
    # запас: второй вид аэродрома, зимний
    "aerodrom-s-vysoty.jpg":
        "tild3239-6662-4834-a565-393237343965/photo_2026-02-04_15-.jpg",
    # аэродром летом с воздуха — к разделу «как добраться»
    "aerodrom-leto.jpg":
        "tild3866-6665-4636-b535-353036653266/__2026-02-04_175745.png",
}

# Снимки, которым нужна обрезка: имя файла → доли (слева, сверху, справа, снизу)
OBREZKA = {
    # на исходнике слева наложена подпись «…РЫЖКА: …УБ» — режем полосу
    "stabilizaciya.jpg": (0.21, 0.0, 1.0, 1.0),
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


def SaveJpeg(data, path, width=1400, crop=None):
    """Кладёт снимок как JPEG, уменьшив по ширине: в письме шире не нужно."""
    from PIL import Image

    image = Image.open(io.BytesIO(data))
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    if crop:
        left, top, right, bottom = crop
        image = image.crop((round(image.width * left), round(image.height * top),
                            round(image.width * right), round(image.height * bottom)))
    if image.width > width:
        height = round(image.height * width / image.width)
        image = image.resize((width, height), Image.LANCZOS)
    image.save(path, "JPEG", quality=86, optimize=True)


if __name__ == "__main__":
    for name, tail in SVOI.items():
        path = os.path.join(HERE, name)
        SaveJpeg(Fetch(TILDA + tail), path, crop=OBREZKA.get(name))
        print(f"{name} — {os.path.getsize(path) // 1024} КБ (главпрыг.рф)")
    for name, source in COMMONS_PHOTOS.items():
        path = os.path.join(HERE, name)
        url = COMMONS + urllib.parse.quote(source) + "?width=1100"
        open(path, "wb").write(Fetch(url))
        print(f"{name} — {os.path.getsize(path) // 1024} КБ (Викисклад)")
