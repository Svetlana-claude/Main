#!/usr/bin/env python3
"""Оглавление папки макетов: какой файл — какой кадр Figma — какая страница сайта.

    python3 glavpryg-sayt/tools/makety-oglavlenie.py [--katalog glavpryg-sayt/makety]

Зачем. Снимки кадров называются по именам слоёв, а слои в файле заказчика
названы «Frame 41», «Link», «768w light» — по имени не понять, что на макете.
Оглавление сводит в одну таблицу номер файла, кадр, страницу сайта и первые
строки текста с макета, чтобы нужный находился одним взглядом.

Страница сайта берётся из `KARTA`: шесть кадров подписал сам разработчик в
`routes/web.php`, остальные опознаны по тексту на снимках. Текст — через
`tools/ocr.py` (правило 17), по верхней части макета.

⚠️ Запускать системным python: Pillow для OCR стоит в нём (правило 17).
"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

KOREN = Path(__file__).resolve().parents[2]

# Кадр Figma → страница сайта. Пустое значение — фрагмент, а не страница.
KARTA = {
    "146:15": "Главная `/` (Frame 22, подписан в routes/web.php)",
    "195:3070": "Сертификат, лендинг `/certificate` (Frame 41, подписан в routes/web.php)",
    "196:820": "Оформление сертификата `/certificate/order` (Frame 43, подписан в routes/web.php)",
}

# Сколько строк текста с макета показывать в оглавлении.
STROK = 4
# Сколько точек сверху макета отдавать в распознавание: шапка и первый экран.
VERKH = 1400


def pervye_stroki(fayl: Path) -> str:
    """Первые осмысленные строки текста с верхней части макета."""
    with Image.open(fayl) as im:
        kusok = im.crop((0, 0, im.width, min(im.height, VERKH)))
        with tempfile.NamedTemporaryFile(suffix=".png") as vremennyy:
            kusok.save(vremennyy.name)
            otvet = subprocess.run(
                ["/usr/bin/python3", str(KOREN / "tools/ocr.py"), vremennyy.name,
                 "--lang", "rus+eng"],
                capture_output=True, text=True, timeout=300)
    stroki = [s.strip() for s in otvet.stdout.splitlines()
              if s.strip() and not s.startswith("#") and len(s.strip()) > 3]
    if otvet.returncode == 2 or not stroki:
        # Правило 17: «ничего не распознано» — это ответ, а не пустота.
        return "*(текст не распознан — смотреть глазами)*"
    return " / ".join(stroki[:STROK]).replace("|", "¦")


def main() -> int:
    razbor = argparse.ArgumentParser()
    razbor.add_argument("--katalog", default=str(KOREN / "glavpryg-sayt/makety"))
    dovody = razbor.parse_args()
    katalog = Path(dovody.katalog)

    spisok = json.loads((katalog / "spisok.json").read_text(encoding="utf-8"))
    kadry = [k for kadry in spisok.values() for k in kadry]
    snimki = sorted(katalog.glob("[0-9][0-9]-*.png"))
    if len(snimki) != len(kadry):
        print(f"⚠️ снимков {len(snimki)}, а кадров в описи {len(kadry)} — "
              f"съёмка не закончена или прервана", file=sys.stderr)

    stroki = []
    for nomer, kadr in enumerate(kadry, 1):
        fayl = next((s for s in snimki if s.name.startswith(f"{nomer:02d}-")), None)
        if fayl is None:
            stroki.append(f"| {nomer:02d} | — | {kadr['imya']} | `{kadr['id']}` | — | "
                          f"{KARTA.get(kadr['id'], '')} | *(не снят)* |")
            continue
        with Image.open(fayl) as im:
            razmer = f"{im.width}×{im.height}"
        tekst = pervye_stroki(fayl)
        stroki.append(f"| {nomer:02d} | [{fayl.name}]({fayl.name}) | {kadr['imya']} | "
                      f"`{kadr['id']}` | {razmer} | {KARTA.get(kadr['id'], '')} | {tekst} |")
        print(f"  {fayl.name}", flush=True)

    shapka = """# Макеты сайта «Главпрыг» из Figma

Снимки кадров страницы **Page 2** файла
`figma.com/design/lfmrbOlU0RBechopnY4OLH`. Сняты без ключа доступа, через
встроенный просмотрщик (`tools/figma-snimki.py`).

⚠️ Снимок — картинка: по нему видны расхождения, но точных цветов, отступов
и шрифтов не достать. Для сверки по числам нужен ключ доступа Figma.

**Переснять** (около получаса):

    webui/.venv/bin/python tools/figma-snimki.py lfmrbOlU0RBechopnY4OLH \\
        --spisok --stranica "Page 2" --katalog glavpryg-sayt/makety
    webui/.venv/bin/python tools/figma-snimki.py lfmrbOlU0RBechopnY4OLH \\
        --snyat glavpryg-sayt/makety/spisok.json --katalog glavpryg-sayt/makety
    /usr/bin/python3 glavpryg-sayt/tools/makety-oglavlenie.py

| № | Файл | Кадр в Figma | Узел | Размер | Страница сайта | Первые строки текста |
|---|---|---|---|---|---|---|
"""
    (katalog / "README.md").write_text(shapka + "\n".join(stroki) + "\n", encoding="utf-8")
    print(f"оглавление: {katalog / 'README.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
