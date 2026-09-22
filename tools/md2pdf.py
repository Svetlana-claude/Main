"""Сборка PDF из Markdown — общий инструмент для всех проектов.

Markdown → HTML с печатными стилями → PDF через headless Chromium (Playwright).
Оформление задаётся базовым набором стилей; проект может добавить свой файл
`.css` — например, подключить фирменные шрифты (пути в нём считаются от каталога
исходника).

Запуск:
    <venv>/bin/python tools/md2pdf.py <файл.md> [--out файл.pdf]
        [--css оформление.css] [--title «Заголовок»] [--footer «Подпись внизу»]

По умолчанию PDF кладётся в `downloads/` рядом с исходником: эту папку показывает
кнопка «Файлы проекта». Заголовок берётся из первого `# ` исходника.
"""
import argparse
import html as html_mod
import re
import tempfile
from pathlib import Path

import markdown
from playwright.sync_api import sync_playwright

LIST_LINE = re.compile(r"^\s*(?:[-*]|\d+\.)\s")
IMPORT_LINE = re.compile(r"@import[^;]+;")

BASE_CSS = """
@page { size: A4; margin: 18mm 16mm 20mm; }
html { font-family: "DejaVu Sans", sans-serif; font-size: 10.5pt; color: #1b2430; line-height: 1.5; }
h1 { font-size: 21pt; color: #0b3d5c; margin: 0 0 5mm; line-height: 1.15; }
h2 { font-size: 14pt; color: #0b3d5c; border-bottom: 1.5pt solid #1d8fc9;
     padding-bottom: 1.5mm; margin: 8mm 0 3mm; break-after: avoid; }
h3 { font-size: 11.5pt; color: #125a86; margin: 5mm 0 2mm; break-after: avoid; }
p, li { orphans: 3; widows: 3; }
ul, ol { padding-left: 6mm; margin: 1.5mm 0 3mm; }
li { margin: 1mm 0; }
li.check { list-style: none; margin-left: -5mm; }
strong { color: #0b2c42; }
hr { border: 0; border-top: 0.6pt solid #cfdae3; margin: 5mm 0; }
blockquote { margin: 3mm 0; padding: 2mm 4mm; background: #fff6e0;
             border-left: 3pt solid #e0a100; }
blockquote p { margin: 0; }
table { width: 100%; border-collapse: collapse; margin: 3mm 0 4mm; font-size: 9.5pt; }
th, td { border: 0.6pt solid #b9c7d3; padding: 1.8mm 2.2mm; vertical-align: top; text-align: left; }
th { background: #e6f1f8; color: #0b3d5c; }
tr { break-inside: avoid; }
a { color: #125a86; text-decoration: none; }
code { font-family: "DejaVu Sans Mono", monospace; font-size: 9pt;
       background: #eef3f7; padding: 0.3mm 1mm; border-radius: 1mm; }
pre { background: #eef3f7; padding: 2.5mm 3mm; border-radius: 1.5mm; break-inside: avoid; }
pre code { background: none; padding: 0; }
img { max-width: 100%; }
"""


def Prepare(text):
    """Подгоняет исходник под python-markdown: пустая строка перед списком."""
    result = []
    for line in text.splitlines():
        prev = result[-1] if result else ""
        if LIST_LINE.match(line) and prev.strip() and not LIST_LINE.match(prev) \
                and not prev.startswith((" ", "#")):
            result.append("")
        result.append(line)
    return "\n".join(result)


def Title(text, fallback):
    """Заголовок документа — первый `# ` исходника, без разметки Markdown."""
    m = re.search(r"^#\s+(.+)$", text, re.M)
    if not m:
        return fallback
    return re.sub(r"[`*_]", "", m.group(1)).strip()


def Build(source, target, css_file=None, title=None, footer=None):
    text = source.read_text(encoding="utf-8")
    body = markdown.markdown(Prepare(text),
                             extensions=["tables", "sane_lists", "fenced_code"])
    # Флажки чек-листа «[ ]» — квадратиком для отметки ручкой
    body = body.replace("<li>[ ] ", '<li class="check">☐ ')
    title = title or Title(text, source.stem)
    extra = css_file.read_text(encoding="utf-8") if css_file else ""
    # `@import` действует только в самом начале стилей, поэтому правила проекта
    # разбираются: подключения наверх, остальное — после базового набора
    imports = "".join(m.group(0) for m in IMPORT_LINE.finditer(extra))
    extra = IMPORT_LINE.sub("", extra)
    page_html = (f'<!doctype html><html lang="ru"><head><meta charset="utf-8">'
                 f'<title>{html_mod.escape(title)}</title>'
                 f'<style>{imports}{BASE_CSS}{extra}</style></head><body>{body}</body></html>')
    target.parent.mkdir(parents=True, exist_ok=True)
    foot = html_mod.escape(footer if footer is not None else title)
    footer_html = ('<div style="font: 8pt DejaVu Sans, sans-serif; color: #7a8a99;'
                   ' width: 100%; text-align: center;">' + foot +
                   ' · <span class="pageNumber"></span> / <span class="totalPages"></span></div>')
    # Страница открывается файлом рядом с исходником: так работают относительные
    # пути на шрифты и картинки из проектного css
    tmp = tempfile.NamedTemporaryFile("w", suffix=".html", dir=source.parent,
                                      encoding="utf-8", delete=False)
    try:
        tmp.write(page_html)
        tmp.close()
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page()
            page.goto(Path(tmp.name).as_uri(), wait_until="load")
            page.evaluate("document.fonts.ready.then(() => 1)")
            page.wait_for_timeout(300)
            page.pdf(path=str(target), format="A4", print_background=True,
                     display_header_footer=True, header_template="<span></span>",
                     footer_template=footer_html,
                     margin={"top": "18mm", "bottom": "20mm",
                             "left": "16mm", "right": "16mm"})
            browser.close()
    finally:
        Path(tmp.name).unlink(missing_ok=True)
    return target


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Markdown → PDF")
    ap.add_argument("source", type=Path, help="исходник .md")
    ap.add_argument("--out", type=Path, help="куда класть PDF")
    ap.add_argument("--css", type=Path, help="дополнительное оформление проекта")
    ap.add_argument("--title", help="заголовок документа")
    ap.add_argument("--footer", help="подпись внизу страницы")
    a = ap.parse_args()
    out = a.out or a.source.parent / "downloads" / (a.source.stem + ".pdf")
    print(Build(a.source.resolve(), out.resolve(), a.css, a.title, a.footer))
