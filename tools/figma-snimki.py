#!/usr/bin/env python3
"""Съёмка кадров Figma без ключа доступа — через встроенный просмотрщик.

Когда ключа доступа нет, а файл открыт по ссылке (`link_access: view`),
макеты всё равно достижимы: встроенный просмотрщик Figma показывает их без
входа. Этот инструмент этим и пользуется.

Работает в два шага:

    --spisok   прочитать боковую панель просмотрщика и выписать кадры:
               идентификатор узла, тип и название. Список виртуальный,
               поэтому панель прокручивается от начала до конца. В опись
               идут только кадры и секции верхнего уровня — брошенные на
               холст картинки и надписи макетами не считаются.
    --stranica только одна страница файла («Page 2»).
    --snyat    открыть каждый кадр в режиме презентации и снять его.

Запуск:

    <venv>/bin/python tools/figma-snimki.py <ссылка> --spisok
    <venv>/bin/python tools/figma-snimki.py <ссылка> --snyat spisok.json \\
        [--katalog exchange/figma] [--vysota 4600]

⚠️ Это обходной путь, а не замена ключу доступа. Снимок — картинка: по нему
видно расхождения, но точных цветов, отступов и шрифтов из него не достать.
Для сверки по числам нужен ключ и `tools/figma-vygruzka.py`.
"""

import argparse
import json
import re
import sys
import urllib.parse
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sys.exit("нет playwright: запускать нужно питоном из venv, где он стоит")

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/131.0.0.0 Safari/537.36")

# ⚠️ Без правдоподобного User-Agent CloudFront отдаёт 403 «Request blocked»:
# headless-браузер по умолчанию он считает роботом.
DOVODY_BRAUZERA = ["--disable-blink-features=AutomationControlled"]

SOBRAT_STROKI = """() => {
  const out = [];
  // ⚠️ Строка слоя с вложенными слоями помечена иначе — `layer-row-with-children`.
  // Именно такие строки и есть макеты страниц: искали одно `layer-row` —
  // и опись выходила из картинок и надписей без единого макета.
  document.querySelectorAll('[data-testid="layer-row"], [data-testid="layer-row-with-children"]').forEach(r => {
    const id = [...r.querySelectorAll('[data-testid$="-layers-panel-row"]')]
      .map(e => e.dataset.testid.replace('-layers-panel-row',''))[0] || '';
    // Тип слоя — подпись значка строки: «Frame», «Rectangle», «Image», «Text».
    const znachok = r.querySelector('[role="img"][aria-label]');
    out.push({id, uroven: +r.getAttribute('aria-level'),
              nomer: +r.getAttribute('aria-rowindex'),
              vsego: +r.getAttribute('aria-setsize'),
              tip: znachok ? znachok.getAttribute('aria-label') : '',
              imya: r.innerText.trim().split('\\n')[0]});
  });
  return out;
}"""

# Контейнер прокрутки панели слоёв — ближайший предок строки, который
# прокручивается. Двигаем его напрямую: колесо мыши шагает как ему вздумается.
PROKRUTIT = """(y) => {
  const r = document.querySelector('[data-testid^="layer-row"]');
  if (!r) return -1;
  let e = r.parentElement;
  while (e && e !== document.body && !(e.scrollHeight > e.clientHeight + 4)) e = e.parentElement;
  if (!e || e === document.body) return -1;
  e.scrollTop = y;
  return e.scrollHeight;
}"""

# Что считать макетом страницы: кадры и секции верхнего уровня. Отдельные
# картинки, надписи и прямоугольники, брошенные на холст, — не макеты.
TIPY_MAKETA = {"Frame", "Section", "Component", "Component set", "Instance"}


def klyuch_fayla(ssylka: str) -> str:
    sovpadenie = re.search(r"/(?:file|design|proto)/([A-Za-z0-9]+)", ssylka)
    if not sovpadenie:
        sys.exit(f"в ссылке не видно ключа файла: {ssylka}")
    return sovpadenie.group(1)


def ubrat_pechenye(stranica) -> None:
    """Плашка про cookie закрывает низ окна и лезет в снимки."""
    for imya in ("Do not allow cookies", "Allow all cookies"):
        try:
            stranica.get_by_role("button", name=imya).click(timeout=4000)
            return
        except Exception:
            continue


def bezopasnoe_imya(imya: str) -> str:
    chistoe = re.sub(r"[^\w\-. ]", "", imya, flags=re.UNICODE).strip()
    return re.sub(r"\s+", "-", chistoe).lower()[:60] or "kadr"


def sobrat_spisok(klyuch: str, tolko: str | None = None) -> dict:
    adres = (f"https://embed.figma.com/design/{klyuch}/makety"
             f"?embed-host=share")
    with sync_playwright() as p:
        br = p.chromium.launch(args=DOVODY_BRAUZERA)
        ctx = br.new_context(viewport={"width": 1600, "height": 1000}, user_agent=UA)
        st = ctx.new_page()
        st.goto(adres, wait_until="load", timeout=90000)
        st.wait_for_timeout(20000)
        ubrat_pechenye(st)
        st.mouse.click(170, 36)          # значок боковой панели у названия файла
        st.wait_for_timeout(4000)

        stranicy = st.locator('[data-testid="PagesRowWrapper"]')
        imena = [stranicy.nth(i).inner_text().strip() for i in range(stranicy.count())]
        itog = {}
        if tolko and tolko not in imena:
            sys.exit(f"страницы «{tolko}» в файле нет; есть: {', '.join(imena)}")
        for i, imya_stranicy in enumerate(imena):
            if tolko and imya_stranicy != tolko:
                continue
            stranicy.nth(i).click()
            st.wait_for_timeout(6000)
            # ⚠️ Панель помнит прокрутку прежней страницы. Без возврата к
            # началу сбор на Page 2 начинался с 83-й строки из 121, и опись
            # выходила хвостом — без единого кадра из первых восьмидесяти.
            vysota = st.evaluate(PROKRUTIT, 0)
            st.wait_for_timeout(800)
            sobrano, vsego, y = {}, 0, 0
            for _ in range(400):
                for stroka in st.evaluate(SOBRAT_STROKI):
                    if stroka["id"]:
                        sobrano[stroka["nomer"]] = stroka
                vsego = max((s["vsego"] for s in sobrano.values()), default=0)
                if (vsego and len(sobrano) >= vsego) or vysota < 0 or y > vysota:
                    break
                y += 300
                vysota = st.evaluate(PROKRUTIT, y)
                st.wait_for_timeout(350)
            verkhniy = [s for s in sorted(sobrano.values(), key=lambda s: s["nomer"])
                        if s["uroven"] == 0]
            itog[imya_stranicy] = [s for s in verkhniy if s["tip"] in TIPY_MAKETA]
            print(f"{imya_stranicy}: строк {len(sobrano)} из {vsego}, "
                  f"верхнего уровня {len(verkhniy)}, из них макетов "
                  f"{len(itog[imya_stranicy])}")
            # ⚠️ Неполная опись — беда, а не повод снимать что нашлось.
            if vsego and len(sobrano) < vsego:
                print(f"  ⚠️ собрано {len(sobrano)} строк из {vsego} — опись неполная",
                      file=sys.stderr)
        br.close()
    return itog


PECHENYE = 70     # высота плашки про cookie внизу окна — в склейку не идёт


def izmerit_sdvig(a, b, predel: int = 1000) -> int:
    """На сколько точек второй снимок сдвинут вниз относительно первого.

    Сдвиг не берётся из величины прокрутки: просмотрщик округляет её по-своему
    и у края кадра прокручивает меньше запрошенного. Поэтому он измеряется —
    ищется положение, при котором полосы снимков совпадают лучше всего.
    """
    sh, vy = a.size
    polosy = list(range(vy // 3, vy - PECHENYE - 8, 40))
    luchshiy, luchshaya = 0, None
    for s in range(40, predel, 2):
        ochki, schet = 0, 0
        for y in polosy:
            if y - s < 0:
                continue
            ra = list(a.crop((0, y, sh, y + 2)).getdata())
            rb = list(b.crop((0, y - s, sh, y - s + 2)).getdata())
            ochki += sum(abs(p1 - p2) for pa, pb in zip(ra, rb) for p1, p2 in zip(pa, pb))
            schet += 1
        if not schet:
            continue
        sredne = ochki / schet
        if luchshaya is None or sredne < luchshaya:
            luchshaya, luchshiy = sredne, s
    return luchshiy


def skleit(kuski: list, sdvigi: list[int]):
    """Куски окна — в одну высокую картинку по измеренным сдвигам."""
    from PIL import Image
    sh, vy = kuski[0].size
    vysota = vy - PECHENYE + sum(sdvigi)
    holst = Image.new("RGB", (sh, vysota), "white")
    holst.paste(kuski[0].crop((0, 0, sh, vy - PECHENYE)), (0, 0))
    y = 0
    for kusok, s in zip(kuski[1:], sdvigi):
        y += s
        holst.paste(kusok.crop((0, 0, sh, vy - PECHENYE)), (0, y))
    return holst


def obrezat_polya(im):
    """Вокруг кадра — поля просмотрщика. Обрезать до самого кадра."""
    sh, vy = im.size
    fon = im.getpixel((2, vy // 2))

    def ne_fon(x, y):
        return sum(abs(a - b) for a, b in zip(im.getpixel((x, y)), fon)) > 20

    xs = [x for x in range(0, sh, 4) if any(ne_fon(x, y) for y in range(0, vy, 24))]
    ys = [y for y in range(0, vy, 4) if any(ne_fon(x, y) for x in range(0, sh, 24))]
    if not xs or not ys:
        return im
    return im.crop((min(xs), min(ys), min(max(xs) + 4, sh), min(max(ys) + 4, vy)))


def snyat(klyuch: str, spisok: dict, katalog: Path, vysota: int, shirina: int) -> None:
    """Снимок каждого кадра целиком: окно обычной высоты и прокрутка.

    ⚠️ В высоком окне отрисовщик Figma выбрасывает фотографии — на снимке
    вместо них белые пятна. Поэтому высота окна обычная, а кадр собирается
    из кусков.
    """
    from PIL import Image
    katalog.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        br = p.chromium.launch(args=DOVODY_BRAUZERA)
        ctx = br.new_context(viewport={"width": shirina, "height": vysota}, user_agent=UA)
        st = ctx.new_page()
        nomer, pechenye_ubrano = 0, False
        for imya_stranicy, kadry in spisok.items():
            for kadr in kadry:
                nomer += 1
                uzel = kadr["id"].replace(":", "-")
                adres = (f"https://embed.figma.com/proto/{klyuch}/makety"
                         f"?node-id={uzel}&embed-host=share&hide-ui=1"
                         f"&scaling=scale-down-width&hotspot-hints=0")
                st.goto(adres, wait_until="load", timeout=90000)
                st.wait_for_timeout(15000)
                if not pechenye_ubrano:
                    ubrat_pechenye(st)      # отказ запоминается на всё окно
                    pechenye_ubrano = True
                st.wait_for_timeout(6000)

                vremenno = katalog / ".kusok.png"
                st.screenshot(path=str(vremenno))
                kuski, sdvigi = [Image.open(vremenno).convert("RGB")], []
                for _ in range(14):
                    st.mouse.move(shirina // 2, vysota // 2)
                    st.mouse.wheel(0, 800)
                    st.wait_for_timeout(5000)
                    st.screenshot(path=str(vremenno))
                    novyy = Image.open(vremenno).convert("RGB")
                    s = izmerit_sdvig(kuski[-1], novyy)
                    if s < 60:
                        break               # дальше не прокручивается — конец кадра
                    kuski.append(novyy)
                    sdvigi.append(s)
                vremenno.unlink(missing_ok=True)

                celoe = obrezat_polya(skleit(kuski, sdvigi))
                fayl = katalog / f"{nomer:02d}-{bezopasnoe_imya(kadr['imya'])}.png"
                celoe.save(fayl)
                print(f"  {fayl.name} {celoe.width}×{celoe.height} "
                      f"({len(kuski)} кусков)  ← {imya_stranicy} / "
                      f"{kadr['imya']} ({kadr['id']})", flush=True)
        br.close()


def main() -> int:
    razbor = argparse.ArgumentParser(description="Съёмка кадров Figma без ключа доступа")
    razbor.add_argument("ssylka", help="ссылка на макет или ключ файла")
    razbor.add_argument("--spisok", action="store_true", help="только выписать кадры")
    razbor.add_argument("--snyat", metavar="ФАЙЛ", help="снять кадры по готовому списку")
    razbor.add_argument("--katalog", default="exchange/figma")
    razbor.add_argument("--vysota", type=int, default=4600, help="высота окна съёмки")
    razbor.add_argument("--shirina", type=int, default=1440, help="ширина окна съёмки")
    razbor.add_argument("--stranica", help="только эта страница файла, например «Page 2»")
    dovody = razbor.parse_args()

    klyuch = klyuch_fayla(dovody.ssylka) if "/" in dovody.ssylka else dovody.ssylka
    katalog = Path(dovody.katalog)

    if dovody.snyat:
        spisok = json.load(open(dovody.snyat, encoding="utf-8"))
        snyat(klyuch, spisok, katalog, dovody.vysota, dovody.shirina)
        return 0

    spisok = sobrat_spisok(klyuch, dovody.stranica)
    katalog.mkdir(parents=True, exist_ok=True)
    put = katalog / "spisok.json"
    put.write_text(json.dumps(spisok, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"список: {put}")
    if not dovody.spisok:
        snyat(klyuch, spisok, katalog, dovody.vysota, dovody.shirina)
    return 0


if __name__ == "__main__":
    sys.exit(main())
