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

Второй обряд того же рода — **выдача правок приложения** (долг 11):

    python3 tools/vydacha.py --prilozhenie [--zhdat]

Правка кода `webui` доходит до браузера только перезапуском службы, а шаблоны
читаются с диска на каждый запрос. Поэтому коммит, добавляющий маршрут и ссылку
на него, разъезжается сам с собой: новый шаблон зовёт маршрут, которого старый
процесс не знает — `NoMatchFound` и 500 на странице. Так и вышло 03.10.2026:
`/Claude/chats` и `/Claude/projects` отдавали 500 два дня, остальные страницы
работали. Одна команда закрывает весь разрыв: сверка ссылок шаблонов со свежим
кодом, перезапуск, ожидание живости, обход страниц по коду ответа и чтение
журнала за время обхода.
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


# --- Выдача правок приложения: перезапуск службы и проверка страниц ---------
#
# Долг 11. Шаблоны читаются с диска на каждый запрос, код живёт в памяти
# процесса — поэтому «закоммичено» и «работает» это два разных состояния, и
# разрыв между ними ничем не закрывался. Здесь он закрыт одной командой.

SLUZHBA = "webui"
ADRES = "http://127.0.0.1:8000"
WEBUI = KOREN / "webui"
SHABLONY = WEBUI / "app" / "templates"

# Что обходим после перезапуска. Без входа защищённые страницы отвечают 303
# (переход на вход) — это годный ответ: он доказывает, что приложение живо и
# маршрут на месте. Отказ — 500 (разъехались шаблоны с кодом) и 404 (маршрут
# пропал). Страницы, на которых споткнулись 03.10, здесь все.
STRANICY = (
    ("/healthz", {200}),
    ("/login", {200}),
    ("/", {200, 303}),
    ("/chats", {200, 303}),
    ("/projects", {200, 303}),
    ("/journal", {200, 303}),
    ("/settings", {200, 303}),
    ("/search", {200, 303}),
    ("/pictures", {200, 303}),
)

ZHIVOST_SROK = 30.0         # сколько ждём, пока приложение поднимется
ZANYATOST_SROK = 1800.0     # предел ожидания ответов при --zhdat: как RUN_TIMEOUT_SEC


def Zapros(adres: str) -> tuple[int, str]:
    """Код ответа **без** перехода по редиректу: 303 на вход — это ответ, а не шаг."""
    import urllib.error
    import urllib.request

    class BezPerehodov(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *dovody, **imennye):
            return None

    otkryt = urllib.request.build_opener(BezPerehodov)
    try:
        with otkryt.open(adres, timeout=10) as otvet:
            return otvet.status, ""
    except urllib.error.HTTPError as exc:
        return exc.code, ""
    except Exception as exc:                 # сеть, отказ соединения, таймаут
        return 0, str(exc)


def ImenaMarshrutov(python: pathlib.Path, koren: pathlib.Path) -> tuple[set[str] | None, str]:
    """Имена маршрутов по **свежему** коду: приложение импортируется отдельным
    процессом, поэтому сверку можно сделать до перезапуска, а не после."""
    programma = (
        "import sys; sys.path.insert(0, '.')\n"
        "from app.main import app\n"
        "print('\\n'.join(sorted(r.name for r in app.routes if getattr(r, 'name', None))))\n"
    )
    rezultat = subprocess.run([str(python), "-c", programma], cwd=str(koren),
                              capture_output=True, text=True)
    if rezultat.returncode != 0:
        prichina = (rezultat.stderr or rezultat.stdout).strip().splitlines()
        return None, prichina[-1] if prichina else f"код возврата {rezultat.returncode}"
    return set(rezultat.stdout.split()), ""


def SsylkiShablonov(katalog: pathlib.Path) -> dict[str, pathlib.Path]:
    """Все `url_for('имя')` шаблонов: имя → файл, где встретилось первым."""
    nayden: dict[str, pathlib.Path] = {}
    for fayl in sorted(katalog.rglob("*.html")):
        telo = fayl.read_text(encoding="utf-8")
        for imya in re.findall(r"""url_for\(\s*['"]([^'"]+)['"]""", telo):
            nayden.setdefault(imya, fayl)
    return nayden


def NerazreshimyeSsylki(imena: set[str], katalog: pathlib.Path) -> list[str]:
    """Ссылки шаблонов, которым в коде не отвечает ни один маршрут."""
    return [f"{fayl.name}: url_for('{imya}') — такого маршрута в коде нет"
            for imya, fayl in SsylkiShablonov(katalog).items() if imya not in imena]


def ZanyatoOtvetov(sluzhba: str = SLUZHBA, imya: str = "claude",
                   fayl: pathlib.Path | None = None) -> int:
    """Сколько готовящихся ответов оборвёт остановка службы.

    Считаются процессы **контрольной группы** службы, а не вывод `pgrep`:
    `pgrep -f claude` находит сам себя (правило 13), а `active_runs()` —
    счётчик внутри процесса приложения, снаружи его не видно. Остановка
    гасит группу целиком (`KillMode` по умолчанию), поэтому группа и есть
    верный признак — см. `webui/app/services/restart.py`.
    """
    if fayl is None:
        fayl = pathlib.Path(f"/sys/fs/cgroup/system.slice/{sluzhba}.service/cgroup.procs")
    if not fayl.is_file():
        return 0
    schet = 0
    for pid in fayl.read_text().split():
        try:
            if pathlib.Path(f"/proc/{pid}/comm").read_text().strip() == imya:
                schet += 1
        except OSError:                      # процесс кончился, пока читали
            pass
    return schet


def DozhdatsyaZhivosti(adres: str = ADRES, srok: float = ZHIVOST_SROK) -> tuple[bool, str]:
    """Ждём, пока `/healthz` ответит 200. Приложение проверяет заодно базу."""
    import time
    konec = time.monotonic() + srok
    posledniy = "не отвечает"
    while time.monotonic() < konec:
        kod, prichina = Zapros(adres + "/healthz")
        if kod == 200:
            return True, ""
        posledniy = f"код {kod}" if kod else prichina
        time.sleep(0.5)
    return False, posledniy


def ObhodStranic(adres: str = ADRES, stranicy=STRANICY) -> list[str]:
    """Страницы, ответившие не тем, чем должны."""
    plokho = []
    for put, godnye in stranicy:
        kod, prichina = Zapros(adres + put)
        zhdali = "/".join(str(k) for k in sorted(godnye))
        if kod not in godnye:
            hvost = f" — {prichina}" if prichina else ""
            plokho.append(f"{put}: код {kod or '—'}{hvost}, ждали {zhdali}")
    return plokho


def OshibkiZhurnala(sluzhba: str, s_momenta: float) -> list[str]:
    """Трассировки и 500 в журнале службы за время обхода."""
    rezultat = subprocess.run(
        ["journalctl", "-u", sluzhba, "--since", f"@{int(s_momenta)}", "--no-pager"],
        capture_output=True, text=True)
    if rezultat.returncode != 0:
        return []
    return [s for s in rezultat.stdout.splitlines()
            if "Traceback" in s or " 500 " in s]


def VylozhitPrilozhenie(sluzhba: str = SLUZHBA, adres: str = ADRES,
                        zhdat: bool = False) -> tuple[bool, list[str]]:
    """Перезапуск службы и проверка, что интерфейс после него работает."""
    import time

    stroki = []

    # 1. Сверка ссылок шаблонов со свежим кодом — **до** перезапуска. Если они
    #    разъехались, перезапускать нечего: 500 будет и после него.
    python = NaytiPython(WEBUI / "app")
    if python is None:
        return False, ["не найден venv приложения"]
    imena, prichina = ImenaMarshrutov(python, WEBUI)
    if imena is None:
        return False, [f"код приложения не импортируется: {prichina}"]
    plokho = NerazreshimyeSsylki(imena, SHABLONY)
    if plokho:
        return False, plokho + ["перезапуск не делался: шаблоны разъехались с кодом"]
    vsego = len(SsylkiShablonov(SHABLONY))
    stroki.append(f"ссылки шаблонов разрешаются: {vsego} из {vsego} "
                  f"(маршрутов в коде {len(imena)})")

    # 2. Занятость. Остановка гасит контрольную группу вместе с готовящимся
    #    ответом, а ответ пишется в базу только по завершении.
    zanyato = ZanyatoOtvetov(sluzhba)
    if zanyato and not zhdat:
        return False, stroki + [
            f"выполняется ответов: {zanyato} — остановка их оборвёт. "
            "Либо кнопка «Перезапустить приложение» (ставит перезапуск в "
            "очередь), либо --zhdat"]
    if zanyato:
        stroki.append(f"ждём завершения ответов: {zanyato}")
        konec = time.monotonic() + ZANYATOST_SROK
        while ZanyatoOtvetov(sluzhba) > 0 and time.monotonic() < konec:
            time.sleep(2.0)
        if ZanyatoOtvetov(sluzhba) > 0:
            return False, stroki + ["ответы не кончились за предельный срок"]

    # 3. Перезапуск
    nachalo = time.time()
    rezultat = subprocess.run(
        ["/usr/bin/sudo", "-n", "/usr/bin/systemctl", "restart", sluzhba],
        capture_output=True, text=True)
    if rezultat.returncode != 0:
        prichina = (rezultat.stderr or rezultat.stdout).strip().splitlines()
        return False, stroki + [f"перезапуск не удался: "
                                f"{prichina[-1] if prichina else rezultat.returncode}"]

    # 4. Живость
    zhiva, prichina = DozhdatsyaZhivosti(adres)
    if not zhiva:
        return False, stroki + [f"служба перезапущена, а /healthz молчит: {prichina}"]
    stroki.append(f"служба {sluzhba} перезапущена, /healthz отвечает")

    # 5. Обход страниц
    plokho = ObhodStranic(adres)
    if plokho:
        return False, stroki + plokho
    stroki.append(f"страницы: {len(STRANICY)} из {len(STRANICY)} отвечают как должны")

    # 6. Журнал за время обхода
    v_zhurnale = OshibkiZhurnala(sluzhba, nachalo)
    if v_zhurnale:
        return False, stroki + [f"в журнале после перезапуска {len(v_zhurnale)} "
                                f"строк с ошибкой, первая: {v_zhurnale[0][-160:]}"]
    stroki.append("журнал после перезапуска чист")
    return True, stroki


def ProverkaPrilozheniya() -> list[str]:
    """Самопроверка обряда выдачи приложения — на тех дефектах, что он ловит."""
    import http.server
    import os
    import shutil
    import socket
    import tempfile
    import threading

    oshibki = []

    # --- Сверка ссылок: подставные шаблоны и подставной список маршрутов ---
    vremennyy = pathlib.Path(tempfile.mkdtemp(prefix="vydacha-prilozhenie-"))
    try:
        (vremennyy / "stranica.html").write_text(
            '<a href="{{ url_for(\'chats\') }}">чатики</a>\n'
            '<form action="{{ url_for("chat_rezhim", chat_id=1) }}"></form>\n',
            encoding="utf-8")
        plokho = NerazreshimyeSsylki({"chats"}, vremennyy)
        if len(plokho) != 1 or "chat_rezhim" not in plokho[0]:
            oshibki.append(f"пропущена ссылка на несуществующий маршрут: {plokho}")
        if NerazreshimyeSsylki({"chats", "chat_rezhim"}, vremennyy):
            oshibki.append("годные ссылки объявлены негодными")
    finally:
        shutil.rmtree(vremennyy, ignore_errors=True)

    # --- Маршруты настоящего приложения читаются ---
    python = NaytiPython(WEBUI / "app")
    if python is None:
        oshibki.append("venv приложения не найден")
    else:
        imena, prichina = ImenaMarshrutov(python, WEBUI)
        if imena is None:
            oshibki.append(f"маршруты приложения не прочитались: {prichina}")
        elif "chats" not in imena:
            oshibki.append(f"в маршрутах приложения нет 'chats': {sorted(imena)[:5]}")

    # --- Обход страниц: подставной сервер, где /chats отдаёт 500 ---
    class Ruchka(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            kod = 500 if self.path == "/chats" else (303 if self.path == "/" else 200)
            self.send_response(kod)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *dovody):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Ruchka)
    nitka = threading.Thread(target=server.serve_forever, daemon=True)
    nitka.start()
    podstavnoy = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        plokho = ObhodStranic(podstavnoy)
        if len(plokho) != 1 or "/chats" not in plokho[0] or "500" not in plokho[0]:
            oshibki.append(f"обход не поймал 500 на /chats: {plokho}")
        zhiva, _ = DozhdatsyaZhivosti(podstavnoy, srok=2.0)
        if not zhiva:
            oshibki.append("живость не распознана на работающем сервере")
    finally:
        server.shutdown()
        server.server_close()

    # --- Живость: закрытый порт должен давать отказ, а не зависание ---
    gnezdo = socket.socket()
    gnezdo.bind(("127.0.0.1", 0))
    zakrytyy = gnezdo.getsockname()[1]
    gnezdo.close()
    zhiva, prichina = DozhdatsyaZhivosti(f"http://127.0.0.1:{zakrytyy}", srok=2.0)
    if zhiva:
        oshibki.append("молчащий порт объявлен живым")

    # --- Занятость: процесс в подставной группе должен находиться ---
    vremennyy = pathlib.Path(tempfile.mkdtemp(prefix="vydacha-group-"))
    try:
        procs = vremennyy / "cgroup.procs"
        procs.write_text(f"{os.getpid()}\n")
        svoe_imya = pathlib.Path(f"/proc/{os.getpid()}/comm").read_text().strip()
        if ZanyatoOtvetov(imya=svoe_imya, fayl=procs) != 1:
            oshibki.append("процесс в группе не посчитан")
        if ZanyatoOtvetov(imya="net-takogo-protsessa", fayl=procs) != 0:
            oshibki.append("посчитан процесс с чужим именем")
        if ZanyatoOtvetov(fayl=vremennyy / "net-takogo-fayla") != 0:
            oshibki.append("отсутствующая группа посчитана занятой")
    finally:
        shutil.rmtree(vremennyy, ignore_errors=True)

    return oshibki


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
    oshibki += ProverkaPrilozheniya()
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
    razbor.add_argument("--prilozhenie", action="store_true",
                        help="выдать правки webui: перезапуск и проверка страниц")
    razbor.add_argument("--zhdat", action="store_true",
                        help="с --prilozhenie: дождаться завершения ответов, а не отказать")
    razbor.add_argument("--proverka", action="store_true", help="самопроверка")
    dovody = razbor.parse_args()

    if dovody.proverka:
        return Proverka()
    if dovody.prilozhenie:
        godno, stroki = VylozhitPrilozhenie(zhdat=dovody.zhdat)
        for stroka in stroki:
            print(("     " if godno else "ОТКАЗ ") + stroka)
        return 0 if godno else 1
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
