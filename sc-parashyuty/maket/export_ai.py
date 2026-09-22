"""Выгрузка макетов в .ai (PDF-совместимый) с разбивкой по слоям.

Как это устроено. Макет живёт в `index.html` — он единственный источник правды.
Скрипт раскладывает изделия одного варианта на общий лист, затем печатает лист
столько раз, сколько нужно слоёв: для каждого изделия отдельно «фон», «графика»
и «текст» (остальное скрыто). Полученные страницы складываются в один PDF, где
каждая становится слоем — группой необязательного содержимого (OCG). Illustrator
и Acrobat показывают такие группы как слои, поэтому файл сохраняется с
расширением `.ai`: внутри это PDF, Illustrator открывает его напрямую.

Запуск:  .venv/bin/python maket/export_ai.py
Выход:   downloads/ai/*.ai  (файлы не версионируются, пересобираются скриптом)
"""
import functools
import http.server
import io
import os
import socketserver
import threading

import pikepdf
from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "downloads", "ai")
PT_PER_MM = 72 / 25.4

# Изделия каждого варианта: подпись на листе и селектор в index.html
VARIANTS = [
    ("variant-a-reys-sc-4000", [
        ("Сертификат · 210×99 мм", ".a-cert"),
        ("Конверт, лицевая · 220×110 мм", ".a-env:not(.a-env-back)"),
        ("Конверт, оборот · 220×110 мм", ".a-env-back"),
        ("Книжка, обложка · 105×148 мм", ".a-book"),
        ("Книжка, разворот · 210×148 мм", ".a-spread"),
    ]),
    ("variant-b-vysota", [
        ("Сертификат · 210×148 мм", ".b-cert"),
        ("Конверт, лицевая · 229×162 мм", ".b-env:not(.b-env-back)"),
        ("Конверт, оборот · 229×162 мм", ".b-env-back"),
        ("Книжка, обложка · 105×148 мм", ".b-book"),
        ("Книжка, разворот · 210×148 мм", ".b-spread"),
    ]),
    ("variant-c-svobodnoe-padenie", [
        ("Сертификат · 210×148 мм", ".c-cert"),
        ("Конверт, лицевая · 220×110 мм", ".c-env:not(.c-env-back)"),
        ("Конверт, оборот · 220×110 мм", ".c-env-back"),
        ("Книжка, обложка · 105×148 мм", ".c-book"),
        ("Книжка, разворот · 210×148 мм", ".c-spread"),
    ]),
]

# Раскладка изделий на листе и правила печати
BUILD_SHEET = """
(items) => {
  const MM = 96 / 25.4, GAP = 24 * MM, PAD = 18 * MM, MAXW = 780 * MM;
  // сперва снимаем размеры изделий, и только потом прячем страницу:
  // у скрытого элемента размеры нулевые
  const src = items.map(it => {
    const node = document.querySelector(it.sel);
    const box = node.getBoundingClientRect();
    return {node, w: box.width, h: box.height};
  });
  for (const el of [...document.body.children]) {
    if (el.tagName.toLowerCase() !== 'svg') el.style.display = 'none';  // defs со знаком оставляем
  }
  const sheet = document.createElement('div');
  sheet.id = 'sheet';
  // фон листа прозрачный: каждый слой печатается отдельной страницей,
  // и белая заливка закрывала бы слои под собой
  sheet.style.cssText = 'position:absolute;left:0;top:0;background:transparent';
  document.body.appendChild(sheet);
  let x = PAD, y = PAD, rowH = 0, maxX = 0;
  items.forEach((it, i) => {
    const box = src[i];
    if (x > PAD && x + box.w > MAXW) { x = PAD; y += rowH + GAP; rowH = 0; }
    const wrap = document.createElement('div');
    wrap.className = 'sheet-item';
    wrap.dataset.i = i;
    wrap.style.cssText = `position:absolute;left:${x}px;top:${y}px;width:${box.w}px`;
    wrap.appendChild(box.node.cloneNode(true));
    const cap = document.createElement('div');
    cap.textContent = it.name;
    cap.style.cssText = `font:600 ${3.2 * MM}px Manrope,sans-serif;color:#5A6B7A;margin-top:${4 * MM}px`;
    wrap.appendChild(cap);
    sheet.appendChild(wrap);
    x += box.w + GAP;
    rowH = Math.max(rowH, box.h + 9 * MM);
    maxX = Math.max(maxX, x - GAP);
  });
  // Закрепляем цвет каждого svg его же вычисленным значением: в слоях «фон»
  // и «текст» цвет текста гасится, а рисунки знака и фигуры залиты currentColor
  // и погасли бы вместе с ним. Инлайновый !important сильнее правил слоя.
  sheet.querySelectorAll('svg').forEach(s => {
    s.style.setProperty('color', getComputedStyle(s).color, 'important');
  });
  const W = maxX + PAD, H = y + rowH + PAD;
  sheet.style.width = W + 'px';
  sheet.style.height = H + 'px';
  const st = document.createElement('style');
  st.textContent = `@page{size:${W / MM}mm ${H / MM}mm;margin:0}
    html,body{background:transparent;margin:0}
    #sheet .shadow{box-shadow:none!important}
    #sheet .a-stub::before,#sheet .a-stub::after{display:none!important}`;
  document.head.appendChild(st);
  return {w: W / MM, h: H / MM};
}
"""

# Слои: что оставляем видимым на каждом проходе.
# «фон и текстуры» — все заливки, градиенты, фоновые картинки и рамки;
# «знаки и иллюстрации» — только svg и img; «текст» — только буквы.
# Заливки нельзя делить между слоями: фон самого изделия рисуется поверх всего
# слоя, который лежит ниже, и закрыл бы плашки внутри изделия (так пропадала
# оранжевая лента варианта C). Поэтому заливки целиком идут в нижний слой.
# Текст с фольгой (.foil-text) отдаётся в слой текста обычным серебряным цветом:
# так его можно править, а градиент дизайнер вернёт сам.
# Гашение текста не должно попадать внутрь svg: рисунки залиты currentColor,
# и прозрачный цвет на потомках svg стёр бы их (`:not(svg *)`).
LAYERS = [
    ("фон и текстуры", """
      {S} *:not(svg):not(svg *), {S} {{ color: transparent !important;
        text-shadow: none !important; -webkit-text-stroke-color: transparent !important; }}
      {S} svg, {S} img {{ visibility: hidden !important; }}
      {S} .foil-text {{ background-image: none !important; }}
    """),
    ("знаки и иллюстрации", """
      {S} *:not(svg):not(svg *), {S} {{ color: transparent !important;
        text-shadow: none !important; -webkit-text-stroke-color: transparent !important; }}
      {S} *, {S} {{ background: none !important; border-color: transparent !important; }}
    """),
    ("текст", """
      {S} *, {S} {{ background: none !important; border-color: transparent !important; }}
      {S} svg, {S} img {{ visibility: hidden !important; }}
      {S} .foil-text {{ color: #C9D3DC !important; }}
    """),
]


def Serve(directory):
    """Локальный сервер: страница открывается по http, а не file:// — так работают шрифты."""
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    handler = functools.partial(Quiet, directory=directory)
    srv = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


def RenderLayers(page, items):
    """Печатает лист по одному слою за проход. Возвращает [(имя слоя, pdf-байты)]."""
    size = page.evaluate(BUILD_SHEET, [{"name": n, "sel": s} for n, s in items])
    page.add_style_tag(content="#layer-css{}")  # плейсхолдер, чтобы стиль был последним
    out = []
    for i, (name, _sel) in enumerate(items):
        scope = f'#sheet .sheet-item[data-i="{i}"]'
        for layer, css in LAYERS:
            page.evaluate(
                """([css]) => {
                    let st = document.getElementById('layer-css');
                    if (!st) { st = document.createElement('style'); st.id = 'layer-css';
                               document.head.appendChild(st); }
                    st.textContent = css;
                }""",
                ['#sheet .sheet-item{visibility:hidden}'
                 f'{scope}{{visibility:visible}}' + css.format(S=scope)],
            )
            pdf = page.pdf(width=f"{size['w']}mm", height=f"{size['h']}mm",
                           print_background=True, prefer_css_page_size=True)
            out.append((f"{name.split(' · ')[0]} — {layer}", pdf))
    return out, size


def MergeLayers(layers, size, path):
    """Складывает страницы в один PDF: каждая становится слоем (OCG)."""
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(size["w"] * PT_PER_MM, size["h"] * PT_PER_MM))
    ocgs, ops = [], []
    for name, data in layers:
        src = pikepdf.open(io.BytesIO(data))
        form = pdf.copy_foreign(pikepdf.Page(src.pages[0]).as_form_xobject())
        ocg = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.OCG, Name=name))
        form.OC = ocg
        key = pikepdf.Page(page).add_resource(form, pikepdf.Name.XObject)
        ocgs.append(ocg)
        ops.append(f"q /{key} Do Q")
    pikepdf.Page(page).contents_add(pikepdf.Stream(pdf, "\n".join(ops).encode()))
    order = pikepdf.Array(ocgs)
    pdf.Root.OCProperties = pikepdf.Dictionary(
        OCGs=order,
        D=pikepdf.Dictionary(Order=order, ON=order, OFF=pikepdf.Array([]),
                             BaseState=pikepdf.Name.ON, Name="Слои SkyCenter"),
    )
    pdf.save(path)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    srv, port = Serve(HERE)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for name, items in VARIANTS:
                page = browser.new_page(viewport={"width": 1600, "height": 1000})
                page.goto(f"http://127.0.0.1:{port}/index.html", wait_until="load")
                page.evaluate("document.fonts.ready.then(() => 1)")
                page.wait_for_timeout(400)
                layers, size = RenderLayers(page, items)
                path = os.path.join(OUT, name + ".ai")
                MergeLayers(layers, size, path)
                print(f"{name}.ai — лист {size['w']:.0f}×{size['h']:.0f} мм, "
                      f"слоёв: {len(layers)}, {os.path.getsize(path) // 1024} КБ")
                page.close()
            browser.close()
    finally:
        srv.shutdown()
