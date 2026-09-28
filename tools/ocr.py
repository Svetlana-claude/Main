#!/usr/bin/python3
"""Распознавание текста на изображениях — общий инструмент для всех проектов.

Изображение → подготовка (поворот, серый, увеличение, контраст) → tesseract →
текст. Разбор макета подбирается сам: несколько режимов прогоняются вподряд,
берётся тот, что прочитал больше текста уверенно.

Запуск (нужен именно системный python — Pillow стоит в нём, не в venv):
    /usr/bin/python3 tools/ocr.py <файл ...> [--lang rus+eng] [--psm N]
        [--boxes] [--out файл.txt] [--pages 1-3] [--keep]

Принимает PNG, JPEG, WEBP, BMP, TIFF, GIF и PDF (страницы раскладываются
через `pdftoppm` в 300 dpi). Текст печатается в вывод; `--out` пишет его
рядом файлом. `--boxes` вместо текста даёт слова с координатами и
уверенностью — этим удобно искать, где на макете стоит надпись.

Ничего не распознано — инструмент говорит об этом прямо и возвращает код 2:
пустой вывод не должен выглядеть как «на картинке нет текста».
"""
import argparse
import csv
import io
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageOps

# Режимы разбора макета: 3 — страница с колонками, 6 — сплошной блок
# (снимки экрана, макеты), 4 — колонка текста, 11 — разрозненные надписи.
PSM_ORDER = [3, 6, 4, 11]
# Ниже этой уверенности слово в счёт лучшего режима не идёт
CONF_MIN = 60
# До какой ширины разгонять картинку: tesseract ждёт букву высотой ~30 px
TARGET_WIDTH = 1800
MAX_SIDE = 5000
PDF_SUFFIXES = {".pdf"}


def Rotation(image_file):
    """Поворот страницы по мнению tesseract: 0, 90, 180 или 270 градусов."""
    try:
        out = subprocess.run(["tesseract", str(image_file), "stdout", "--psm", "0"],
                             capture_output=True, text=True, timeout=60).stdout
    except (OSError, subprocess.SubprocessError):
        return 0
    m = re.search(r"Rotate:\s*(\d+)", out)
    return int(m.group(1)) % 360 if m else 0


def Prepare(source, target, rotate=True):
    """Готовит картинку к распознаванию. Возвращает (файл, во сколько раз увеличено).

    Множитель нужен, чтобы координаты слов вернуть в систему исходного кадра.
    """
    scale = 1.0
    with Image.open(source) as img:
        img = ImageOps.exif_transpose(img)
        # Прозрачность на белый: иначе тёмный текст ложится на чёрный фон
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGBA")
            fon = Image.new("RGBA", img.size, "white")
            img = Image.alpha_composite(fon, img)
        img = img.convert("L")
        # Мелкий кадр разгоняется до рабочей ширины, крупный не трогаем
        rost = min(TARGET_WIDTH / img.width, MAX_SIDE / max(img.size))
        if rost > 1.05:
            scale = rost
            img = img.resize((round(img.width * rost), round(img.height * rost)),
                             Image.LANCZOS)
        img = ImageOps.autocontrast(img, cutoff=1)
        img.save(target)
    if rotate:
        angle = Rotation(target)
        if angle:
            with Image.open(target) as img:
                # tesseract сообщает, на сколько повернуть по часовой стрелке
                img.rotate(-angle, expand=True, fillcolor="white").save(target)
    return target, scale


def Tsv(image_file, lang, psm):
    """Слова, найденные tesseract: список (текст, уверенность, левый, верх, ш, в)."""
    out = subprocess.run(
        ["tesseract", str(image_file), "stdout", "-l", lang, "--psm", str(psm), "tsv"],
        capture_output=True, text=True).stdout
    words = []
    for row in csv.DictReader(io.StringIO(out), delimiter="\t", quoting=csv.QUOTE_NONE):
        text = (row.get("text") or "").strip()
        if not text:
            continue
        try:
            conf = float(row["conf"])
            box = (int(row["left"]), int(row["top"]),
                   int(row["width"]), int(row["height"]))
        except (KeyError, TypeError, ValueError):
            continue
        words.append((text, conf, *box))
    return words


def Score(words):
    """Оценка режима: сколько букв прочитано уверенно, при равенстве — средняя."""
    sure = [w for w in words if w[1] >= CONF_MIN]
    chars = sum(len(w[0]) for w in sure)
    average = sum(w[1] for w in sure) / len(sure) if sure else 0
    return chars, average


def Text(image_file, lang, psm):
    """Готовый текст страницы в выбранном режиме — со строками и абзацами."""
    return subprocess.run(
        ["tesseract", str(image_file), "stdout", "-l", lang, "--psm", str(psm)],
        capture_output=True, text=True).stdout.rstrip()


def Best(sheets, lang, psm=None):
    """Подбирает картинку и режим разбора. Возвращает (картинка, режим, слова, оценка).

    Соревнуются подготовленный кадр и исходный: на чётком снимке подготовка
    иногда только портит буквы, и тогда побеждает исходник. Так инструмент не
    оказывается хуже прямого вызова tesseract.
    """
    modes = [psm] if psm is not None else PSM_ORDER
    best = (sheets[0], modes[0], [], (0, 0))
    for sheet in sheets:
        for mode in modes:
            words = Tsv(sheet, lang, mode)
            mark = Score(words)
            if mark > best[3]:
                best = (sheet, mode, words, mark)
    return best


def PdfPages(source, work, pages=None):
    """Раскладывает PDF в PNG по 300 dpi и отдаёт список страниц."""
    if not shutil.which("pdftoppm"):
        sys.exit("Для PDF нужен pdftoppm: sudo apt-get install poppler-utils")
    cmd = ["pdftoppm", "-r", "300", "-png"]
    if pages:
        first, last = pages
        cmd += ["-f", str(first), "-l", str(last)]
    subprocess.run(cmd + [str(source), str(work / "str")], check=True)
    return sorted(work.glob("str-*.png"))


def Range(value):
    """Разбирает «3» и «1-5» в пару номеров страниц."""
    m = re.fullmatch(r"(\d+)(?:-(\d+))?", value.strip())
    if not m:
        raise argparse.ArgumentTypeError("страницы задаются как «3» или «1-5»")
    first = int(m.group(1))
    return first, int(m.group(2) or first)


def Recognize(source, work, lang, psm=None, pages=None, boxes=False):
    """Распознаёт файл целиком и собирает вывод по страницам."""
    pdf = source.suffix.lower() in PDF_SUFFIXES
    sheets = PdfPages(source, work, pages) if pdf else [source]

    parts = []
    for number, sheet in enumerate(sheets, 1):
        gotov, scale = Prepare(sheet, work / f"{sheet.stem}-podgotovlen.png",
                               rotate=not pdf)
        ishodnik = sheet
        sheet, mode, words, (chars, average) = Best([gotov, ishodnik], lang, psm)
        head = f"[страница {number}]" if len(sheets) > 1 else ""
        note = f"режим {mode}, букв {chars}, уверенность {average:.0f}%"
        if not chars:
            parts.append(f"{head} — текст не распознан ({note})".strip())
            continue
        if boxes:
            # Координаты приводятся к системе исходного кадра; если кадр
            # пришлось разворачивать, они считаются от выпрямленного
            delitel = scale if sheet == gotov else 1.0
            lines = [f"{w[1]:5.1f}%  x={round(w[2] / delitel):>5} "
                     f"y={round(w[3] / delitel):>5} ш={round(w[4] / delitel):>4} "
                     f"в={round(w[5] / delitel):>4}  {w[0]}" for w in words]
            body = "\n".join(lines)
        else:
            body = Text(sheet, lang, mode)
        parts.append("\n".join(x for x in (head, f"# {note}", body) if x))
    return "\n\n".join(parts)


def Main():
    parser = argparse.ArgumentParser(
        description="Распознавание текста на изображениях и в PDF (tesseract)")
    parser.add_argument("files", nargs="+", type=Path, help="картинки или PDF")
    parser.add_argument("--lang", default="rus+eng",
                        help="языки tesseract через «+» (по умолчанию rus+eng)")
    parser.add_argument("--psm", type=int, default=None,
                        help="режим разбора макета; без него подбирается сам")
    parser.add_argument("--boxes", action="store_true",
                        help="слова с координатами и уверенностью вместо текста")
    parser.add_argument("--pages", type=Range, default=None,
                        help="страницы PDF: «3» или «1-5»")
    parser.add_argument("--out", type=Path, default=None,
                        help="записать распознанное в файл")
    parser.add_argument("--keep", type=Path, default=None,
                        help="сохранить подготовленные картинки в эту папку")
    args = parser.parse_args()

    if not shutil.which("tesseract"):
        sys.exit("tesseract не установлен: "
                 "sudo apt-get install tesseract-ocr tesseract-ocr-rus tesseract-ocr-eng")

    chunks, found = [], False
    for source in args.files:
        if not source.exists():
            sys.exit(f"нет файла: {source}")
        work = Path(tempfile.mkdtemp(prefix="ocr-"))
        try:
            text = Recognize(source, work, args.lang, args.psm, args.pages, args.boxes)
            if args.keep:
                args.keep.mkdir(parents=True, exist_ok=True)
                for made in work.iterdir():
                    shutil.copy2(made, args.keep / made.name)
        finally:
            shutil.rmtree(work, ignore_errors=True)
        found = found or "не распознан" not in text
        head = f"=== {source} ===" if len(args.files) > 1 else ""
        chunks.append("\n".join(x for x in (head, text) if x))

    result = "\n\n".join(chunks)
    if args.out:
        args.out.write_text(result + "\n", encoding="utf-8")
        print(f"Распознанное: {args.out}")
    print(result)
    return 0 if found else 2


if __name__ == "__main__":
    sys.exit(Main())
