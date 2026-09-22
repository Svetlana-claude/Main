"""Образец шрифтов макета: PDF со всеми начертаниями.

Служит двум целям. Дизайнеру — шпаргалка: как выглядит каждое начертание и где
оно применяется. Проверке — доказательство, что собранные TTF действительно
ставятся и работают: страница набирается **системными** шрифтами по именам, без
`@font-face`, поэтому битый или неустановленный шрифт сразу виден подменой на
чужой. Ставятся шрифты так:

    cp downloads/ai/fonts/*.ttf ~/.local/share/fonts/ && fc-cache -f

Запуск:  .venv/bin/python maket/fonts_sample.py
Выход:   downloads/ai/shrifty-obrazec.pdf
"""
import os

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "downloads", "ai", "shrifty-obrazec.pdf")

# Начертание: семейство, вес, курсив, где применяется в макете
SAMPLES = [
    ("Oswald", 700, False, "заголовки, крупные числа, имя получателя"),
    ("Oswald", 500, False, "подзаголовки, шапки таблиц"),
    ("Manrope", 400, False, "основной текст, описания"),
    ("Manrope", 600, False, "подписи полей, выделения в тексте"),
    ("Manrope", 800, False, "заголовки варианта C"),
    ("JetBrains Mono", 400, False, "«билетные» данные: коды, даты, номера"),
    ("JetBrains Mono", 700, False, "шапки учётных таблиц книжки"),
    ("Caveat", 500, False, "рукописные пометки в книжке парашютиста"),
    ("Unbounded", 400, False, "надзаголовки варианта B, разрядка"),
    ("Unbounded", 600, False, "акценты варианта B"),
    ("Unbounded", 800, False, "контурные цифры «4000»"),
    ("Rubik", 900, False, "крупные выкрики варианта C"),
    ("Rubik", 900, True, "тот же выкрик с наклоном"),
]

PANGRAM = "Небо ждёт: прыжок с 4000 м — SkyCenter, DZ Пущино"
ALPHABET = "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ 0123456789 ABCDEFGHIJKLMNOPQRSTUVWXYZ"

CSS = """
@page { size: A4; margin: 16mm 14mm 18mm; }
html { font-family: Manrope, sans-serif; color: #0B1B2B; }
h1 { font-family: Oswald, sans-serif; font-weight: 700; text-transform: uppercase;
     font-size: 20pt; border-bottom: 2.5pt solid #30CFFA; padding-bottom: 3mm; margin: 0 0 3mm; }
.intro { font-size: 9.5pt; color: #40566B; margin: 0 0 6mm; line-height: 1.5; }
.row { border-top: 0.6pt solid #C9D3DC; padding: 3.5mm 0; break-inside: avoid; }
.head { display: flex; justify-content: space-between; align-items: baseline;
        font-size: 8pt; color: #5A6B7A; letter-spacing: .06em; text-transform: uppercase; }
.name { font-family: "JetBrains Mono", monospace; font-size: 9pt; color: #0075FF;
        letter-spacing: 0; text-transform: none; }
.pangram { font-size: 17pt; line-height: 1.25; margin: 1.5mm 0 1mm; }
.alphabet { font-size: 8.5pt; color: #40566B; line-height: 1.4; word-break: break-word; }
"""


def Build():
    rows = []
    for family, weight, italic, use in SAMPLES:
        # кавычки только одинарные: двойные оборвали бы атрибут style
        style = (f"font-family: '{family}'; font-weight: {weight};"
                 f" font-style: {'italic' if italic else 'normal'};")
        label = f"{family} {weight}{' курсив' if italic else ''}"
        rows.append(
            f'<div class="row"><div class="head"><span class="name">{label}</span>'
            f'<span>{use}</span></div>'
            f'<div class="pangram" style="{style}">{PANGRAM}</div>'
            f'<div class="alphabet" style="{style}">{ALPHABET}</div></div>')
    html = (f'<!doctype html><html lang="ru"><head><meta charset="utf-8">'
            f'<title>SkyCenter — шрифты макета</title><style>{CSS}</style></head>'
            f'<body><h1>Шрифты макета SkyCenter</h1>'
            f'<p class="intro">Все начертания, которые стоят в макетах сертификата, '
            f'конверта и книжки парашютиста. Файлы лежат рядом, в папке '
            f'<b>fonts</b>; лицензия SIL Open Font License — шрифты бесплатны, в том '
            f'числе для коммерческой печати. Набрано установленными шрифтами: если '
            f'строка выглядит чужой, шрифт в системе не встал.</p>{"".join(rows)}'
            f'</body></html>')
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    footer = ('<div style="font: 8pt Manrope, sans-serif; color: #7a8a99; width: 100%;'
              ' text-align: center;">SkyCenter · шрифты макета · '
              '<span class="pageNumber"></span> / <span class="totalPages"></span></div>')
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.set_content(html, wait_until="load")
        page.evaluate("document.fonts.ready.then(() => 1)")
        page.pdf(path=OUT, format="A4", print_background=True,
                 display_header_footer=True, header_template="<span></span>",
                 footer_template=footer,
                 margin={"top": "16mm", "bottom": "18mm", "left": "14mm", "right": "14mm"})
        browser.close()
    print(OUT)


if __name__ == "__main__":
    Build()
