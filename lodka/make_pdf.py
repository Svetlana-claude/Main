"""Сборка PDF из свода для инвесторов.

Markdown → HTML с печатными стилями → PDF через headless Chromium (Playwright).
Запуск из корня репозитория:
    webui/.venv/bin/python lodka/make_pdf.py
Результат кладётся в lodka/downloads/ (папка не версионируется).
"""
import re
from pathlib import Path

import markdown
from playwright.sync_api import sync_playwright

base = Path(__file__).resolve().parent
source = base / "prezentaciya-dlya-investorov.md"
target = base / "downloads" / "prezentaciya-dlya-investorov.pdf"

LIST_LINE = re.compile(r"^\s*(?:[-*]|\d+\.)\s")

CSS = """
@page { size: A4; margin: 18mm 16mm 20mm; }
html { font-family: "DejaVu Sans", sans-serif; font-size: 10pt; color: #1b2430; line-height: 1.45; }
h1 { font-size: 20pt; color: #0b3d5c; margin: 0 0 4mm; line-height: 1.2; }
h2 { font-size: 14pt; color: #0b3d5c; border-bottom: 1.5pt solid #1d8fc9;
     padding-bottom: 1.5mm; margin: 8mm 0 3mm; break-after: avoid; }
h3 { font-size: 11.5pt; color: #125a86; margin: 5mm 0 2mm; break-after: avoid; }
p, li { orphans: 3; widows: 3; }
ul, ol { padding-left: 6mm; margin: 1.5mm 0 3mm; }
li { margin: 0.8mm 0; }
li.check { list-style: none; margin-left: -5mm; }
strong { color: #0b2c42; }
hr { border: 0; margin: 4mm 0; }
blockquote { margin: 3mm 0; padding: 2mm 4mm; background: #fff6e0;
             border-left: 3pt solid #e0a100; }
blockquote p { margin: 0; }
table { width: 100%; border-collapse: collapse; margin: 3mm 0 4mm; font-size: 9pt; }
th, td { border: 0.6pt solid #b9c7d3; padding: 1.6mm 2mm; vertical-align: top; text-align: left; }
th { background: #e6f1f8; color: #0b3d5c; }
tr { break-inside: avoid; }
a { color: #125a86; text-decoration: none; }
code { font-family: "DejaVu Sans Mono", monospace; font-size: 9pt; }
"""


def Prepare(text):
    """Подгоняет исходник под python-markdown: пустая строка перед списком, флажки."""
    lines = text.splitlines()
    result = []
    for i, line in enumerate(lines):
        prev = result[-1] if result else ""
        if LIST_LINE.match(line) and prev.strip() and not LIST_LINE.match(prev) \
                and not prev.startswith((" ", "#")):
            result.append("")
        result.append(line)
    return "\n".join(result)


def Build():
    html_body = markdown.markdown(Prepare(source.read_text(encoding="utf-8")),
                                  extensions=["tables", "sane_lists"])
    # Флажки чек-листа «[ ]» — квадратиком для отметки ручкой
    html_body = html_body.replace("<li>[ ] ", '<li class="check">☐ ')
    html = (f'<!doctype html><html lang="ru"><head><meta charset="utf-8">'
            f'<title>Лодка 8–12 м: презентация инвесторам</title>'
            f'<style>{CSS}</style></head><body>{html_body}</body></html>')
    target.parent.mkdir(exist_ok=True)
    footer = ('<div style="font: 8pt DejaVu Sans, sans-serif; color: #7a8a99; width: 100%;'
              ' text-align: center;">Лодка 8–12 м · презентация инвесторам · '
              '<span class="pageNumber"></span> / <span class="totalPages"></span></div>')
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.set_content(html, wait_until="load")
        page.pdf(path=str(target), format="A4", print_background=True,
                 display_header_footer=True, header_template="<span></span>",
                 footer_template=footer,
                 margin={"top": "18mm", "bottom": "20mm", "left": "16mm", "right": "16mm"})
        browser.close()
    print(target)


if __name__ == "__main__":
    Build()
