#!/usr/bin/env python3
"""Выдача документа одной командой: PDF в `downloads/` и проверка результата.

Правила 15 и 16 требуют трёх действий над каждым документом: исходник лежит в
каталоге проекта, в `downloads/` — собранный PDF, и после каждой правки PDF
пересобирается. Руками это три-четыре шага (выбрать `venv`, позвать `md2pdf`,
проверить, что файл обновился), а шаг агента стоит одинаково, что бы он ни
делал — см. `optimizaciya/ekonomnaya-rabota.md`. Поэтому один вызов:

    python3 tools/vydacha.py <файл.md ...> [--css оформление.css] [--vse]
    python3 tools/vydacha.py --proverka

Сам находит рабочий `venv` (в каталоге проекта, иначе `webui/.venv`), собирает
только то, что устарело, и печатает по строке на документ: куда лёг PDF, его
размер и число страниц. `--vse <каталог>` берёт все `.md` каталога.
Устаревшим считается PDF, которого нет или который старше исходника.
"""

import argparse
import pathlib
import re
import subprocess
import sys

KOREN = pathlib.Path(__file__).resolve().parent.parent
MD2PDF = KOREN / "tools" / "md2pdf.py"
# Меньше этого PDF не бывает даже у страницы текста: пустая выдача — отказ.
MIN_RAZMER = 5_000


def NaytiPython(istochnik: pathlib.Path) -> pathlib.Path | None:
    """Python с `markdown` и `playwright`: сперва в проекте, потом у `webui`."""
    kandidaty = []
    for roditel in [istochnik.resolve().parent, *istochnik.resolve().parents]:
        kandidaty.append(roditel / ".venv" / "bin" / "python")
        if roditel == KOREN:
            break
    kandidaty.append(KOREN / "webui" / ".venv" / "bin" / "python")
    for put in kandidaty:
        if put.is_file():
            return put
    return None


def ChisloStranic(pdf: pathlib.Path) -> int:
    """Страницы считаются по самому файлу, без сторонних библиотек."""
    telo = pdf.read_bytes()
    po_schetu = re.search(rb"/Count\s+(\d+)", telo)
    if po_schetu:
        return int(po_schetu.group(1))
    return len(re.findall(rb"/Type\s*/Page[^s]", telo))


def Ustarel(istochnik: pathlib.Path, pdf: pathlib.Path) -> bool:
    return not pdf.is_file() or pdf.stat().st_mtime < istochnik.stat().st_mtime


def Vylozhit(istochnik: pathlib.Path, css: str | None = None,
             silom: bool = False) -> tuple[bool, str]:
    """Собирает PDF, если нужно, и проверяет, что вышло. Возвращает (годно, строка)."""
    if not istochnik.is_file():
        return False, f"{istochnik}: нет такого файла"
    pdf = istochnik.parent / "downloads" / (istochnik.stem + ".pdf")
    # Свежий по времени, но пустой PDF выдачей не считается: такой огрызок
    # остаётся от прерванной сборки, а в «Файлах проекта» выглядит как документ.
    svezhiy = not Ustarel(istochnik, pdf) and pdf.stat().st_size >= MIN_RAZMER
    if not silom and svezhiy:
        return True, f"{istochnik.name}: PDF свежий, пересборка не нужна"

    python = NaytiPython(istochnik)
    if python is None:
        return False, f"{istochnik.name}: не найден venv с markdown и playwright"

    argv = [str(python), str(MD2PDF), str(istochnik)]
    if css:
        argv += ["--css", css]
    rezultat = subprocess.run(argv, capture_output=True, text=True)
    if rezultat.returncode != 0:
        oshibka = (rezultat.stderr or rezultat.stdout).strip().splitlines()
        return False, f"{istochnik.name}: md2pdf отказал — {oshibka[-1] if oshibka else 'без причины'}"

    if not pdf.is_file():
        return False, f"{istochnik.name}: md2pdf отработал, а PDF не появился ({pdf})"
    if Ustarel(istochnik, pdf):
        return False, f"{istochnik.name}: PDF старше исходника — пересборка не состоялась"
    razmer = pdf.stat().st_size
    if razmer < MIN_RAZMER:
        return False, f"{istochnik.name}: PDF подозрительно мал ({razmer} Б)"
    try:
        kuda = pdf.relative_to(KOREN)
    except ValueError:                       # файл вне репозитория — печатаем как есть
        kuda = pdf
    return True, (f"{istochnik.name} → {kuda}, "
                  f"{razmer // 1024} КБ, {ChisloStranic(pdf)} с.")


def Proverka() -> int:
    """Самопроверка на подставном проекте: пересборка, свежесть, отказы."""
    import shutil
    import tempfile

    vremennyy = pathlib.Path(tempfile.mkdtemp(prefix="vydacha-"))
    oshibki = []
    try:
        istochnik = vremennyy / "zapiska.md"
        istochnik.write_text("# Записка\n\nТекст записки.\n" * 20, encoding="utf-8")

        godno, stroka = Vylozhit(istochnik)
        if not godno:
            oshibki.append(f"сборка с нуля не удалась: {stroka}")
        pdf = vremennyy / "downloads" / "zapiska.pdf"
        if not pdf.is_file():
            oshibki.append("PDF не появился в downloads/")
            return Itog(oshibki)

        # Второй вызов не должен собирать заново: PDF свежий.
        bylo = pdf.stat().st_mtime_ns
        godno, stroka = Vylozhit(istochnik)
        if not godno or "свежий" not in stroka:
            oshibki.append(f"свежий PDF собран повторно: {stroka}")
        if pdf.stat().st_mtime_ns != bylo:
            oshibki.append("свежий PDF перезаписан")

        # Правка исходника — пересборка обязательна.
        istochnik.write_text(istochnik.read_text(encoding="utf-8") + "\nДописано.\n",
                             encoding="utf-8")
        godno, stroka = Vylozhit(istochnik)
        if not godno or "свежий" in stroka:
            oshibki.append(f"после правки PDF не пересобран: {stroka}")

        # Огрызок от прерванной сборки свежий по времени, но выдачей не является:
        # его нужно пересобрать, а не зачесть.
        pdf.write_bytes(b"%PDF-1.4 ")
        godno, stroka = Vylozhit(istochnik)
        if not godno or "свежий" in stroka:
            oshibki.append(f"огрызок PDF принят за выдачу: {stroka}")
        elif pdf.stat().st_size < MIN_RAZMER:
            oshibki.append("огрызок PDF не пересобран")

        # Отказ должен называть причину словами: «md2pdf отказал» на
        # несуществующем файле — это правильный ответ по неправильной причине.
        godno, stroka = Vylozhit(vremennyy / "net-takogo.md")
        if godno or "нет такого файла" not in stroka:
            oshibki.append(f"несуществующий файл: {stroka}")
    finally:
        shutil.rmtree(vremennyy, ignore_errors=True)
    return Itog(oshibki)


def Itog(oshibki: list[str]) -> int:
    for stroka in oshibki:
        print("НЕ СХОДИТСЯ:", stroka)
    print("самопроверка: " + ("падает" if oshibki else "сходится"))
    return 1 if oshibki else 0


def main() -> int:
    razbor = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    razbor.add_argument("fajly", nargs="*", help="документы .md или каталог при --vse")
    razbor.add_argument("--css", help="файл оформления для md2pdf")
    razbor.add_argument("--vse", action="store_true",
                        help="взять все .md указанного каталога")
    razbor.add_argument("--silom", action="store_true",
                        help="пересобрать, даже если PDF свежий")
    razbor.add_argument("--proverka", action="store_true", help="самопроверка")
    dovody = razbor.parse_args()

    if dovody.proverka:
        return Proverka()
    if not dovody.fajly:
        razbor.print_help()
        return 2

    istochniki = []
    for imya in dovody.fajly:
        put = pathlib.Path(imya)
        if dovody.vse and put.is_dir():
            istochniki += sorted(p for p in put.glob("*.md"))
        else:
            istochniki.append(put)

    plokho = 0
    for istochnik in istochniki:
        godno, stroka = Vylozhit(istochnik, dovody.css, dovody.silom)
        print(("     " if godno else "ОТКАЗ ") + stroka)
        plokho += 0 if godno else 1
    return 1 if plokho else 0


if __name__ == "__main__":
    sys.exit(main())
