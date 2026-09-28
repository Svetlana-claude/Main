#!/usr/bin/python3
"""Проверка `tools/ocr.py`: мелкий шрифт, перевёрнутый кадр, пустая картинка.

Каждый случай — тот, на котором прямой вызов `tesseract` ошибается, а
инструмент обязан справиться. Прогон:

    /usr/bin/python3 tools/tests/check_ocr.py [--golyy]

`--golyy` прогоняет те же картинки голым tesseract — так видно, что проверка
ловит настоящий дефект, а не свою же оснастку.
"""
import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

KOREN = Path(__file__).resolve().parents[2]
OCR = KOREN / "tools" / "ocr.py"
SHRIFT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
OBRAZEC = "Прыжок с парашютом высота 4000 метров"


def Kartinka(target, text=OBRAZEC, size=28, angle=0, scale=1.0, quality=95):
    """Пишет образец на белом листе.

    `scale` уменьшает готовый кадр, `quality` жмёт его — так выглядит снимок
    экрана, ужатый мессенджером по дороге к нам. Именно на таком голый
    tesseract молчит.
    """
    font = ImageFont.truetype(SHRIFT, size)
    img = Image.new("RGB", (size * 26, size * 3), "white")
    ImageDraw.Draw(img).text((8, size), text, font=font, fill="black")
    if angle:
        img = img.rotate(angle, expand=True, fillcolor="white")
    if scale != 1.0:
        img = img.resize((round(img.width * scale), round(img.height * scale)),
                         Image.LANCZOS)
    img.save(target, quality=quality)
    return target


def Pusto(target):
    """Лист без единой буквы — на нём инструмент обязан сказать об этом прямо."""
    img = Image.new("RGB", (600, 400), "white")
    ImageDraw.Draw(img).ellipse((200, 120, 400, 280), outline="black", width=6)
    img.save(target)
    return target


def Slova(text):
    """Слова образца, найденные в распознанном, — без оглядки на регистр."""
    nizhniy = text.lower()
    return [w for w in OBRAZEC.lower().split() if w in nizhniy]


def Golyy(image_file):
    """Как прочитал бы прямой вызов tesseract — без подготовки картинки."""
    return subprocess.run(["tesseract", str(image_file), "stdout", "-l", "rus+eng"],
                          capture_output=True, text=True).stdout


def Instrument(image_file):
    """Как читает инструмент. Возвращает (текст, код возврата)."""
    done = subprocess.run(["/usr/bin/python3", str(OCR), str(image_file)],
                          capture_output=True, text=True)
    return done.stdout, done.returncode


def Main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--golyy", action="store_true",
                        help="прогнать те же случаи прямым вызовом tesseract")
    args = parser.parse_args()
    chitat = Golyy if args.golyy else lambda p: Instrument(p)[0]
    imya = "голый tesseract" if args.golyy else "tools/ocr.py"

    oshibki = []
    with tempfile.TemporaryDirectory(prefix="check-ocr-") as papka:
        papka = Path(papka)

        # 1. Ужатый снимок: буква высотой ~7 px, качество 50 — голый tesseract
        # молчит совсем. Случай нарочно у самого предела разбора, и точность там
        # гуляет, поэтому спрашивается не дословность, а половина слов образца.
        text = chitat(Kartinka(papka / "melkiy.jpg", scale=0.25, quality=50))
        nashel = Slova(text)
        print(f"[{imya}] ужатый снимок: слов образца {len(nashel)} из 6 — {nashel}")
        if len(nashel) < 3:
            oshibki.append("ужатый снимок не прочитан")

        # 2. Перевёрнутый кадр: поворот определяется по OSD и снимается
        text = chitat(Kartinka(papka / "vverh-nogami.png", angle=180))
        nashel = Slova(text)
        print(f"[{imya}] перевёрнутый кадр: слов образца {len(nashel)} из 6 — {nashel}")
        if len(nashel) < 5:
            oshibki.append("перевёрнутый кадр не прочитан")

        # 3. Картинка без текста: молчание должно быть названо словами
        text, kod = Instrument(Pusto(papka / "pusto.png"))
        if not args.golyy:
            print(f"[{imya}] лист без текста: код {kod}, "
                  f"сказано прямо — {'да' if 'не распознан' in text else 'нет'}")
            if "не распознан" not in text or kod != 2:
                oshibki.append("пустая картинка не отмечена как нераспознанная")

    if oshibki:
        print("ПРОВАЛ: " + "; ".join(oshibki))
        return 1
    print("Все проверки пройдены")
    return 0


if __name__ == "__main__":
    sys.exit(Main())
