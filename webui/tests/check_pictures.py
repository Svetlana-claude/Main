"""Проверка вкладки «Картинки»: что показано, что закрыто и что работает нажатием.

Четыре места, где раздел ломается заметно или опасно:

* **ключ из запроса не проверен** — `?src=p5/../../.config/webui/webui.env`
  отдаёт `SECRET_KEY` и пароль базы тем же способом, каким это ловится
  в «Файлах проекта». Сюда же: не-картинка по прямой ссылке и выход в папки,
  которых в сетке нет;
* **в галерею попало чужое** — питоновское окружение в `exchange/pwenv`
  приносит полсотни значков playwright, и своих снимков среди них не найти;
* **превью не делается или делается заново каждый раз** — сотня исходников
  по 4 МБ в сетке кладёт и страницу, и сервер;
* **страница не открылась или не листается** — вёрстка и скрипт проверяются
  нажатием в настоящем браузере, а не разбором разметки (правила 9 и 14).

Браузер — Playwright, чистая копия приложения на свободном порту; рабочая
служба не трогается.

Запуск:  .venv/bin/python tests/check_pictures.py
"""
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db, security as auth                  # noqa: E402
from app.routers import pictures as pic               # noqa: E402

PROJECT_DIR = Path(__file__).resolve().parent.parent
FAILED: list[str] = []


def check(ok: bool, what: str) -> None:
    if ok:
        print(f"  ok: {what}")
    else:
        FAILED.append(what)
        print(f"  ПРОВАЛ: {what}")


def png(path: Path, size=(40, 30), alpha: bool = False) -> None:
    from PIL import Image
    Image.new("RGBA" if alpha else "RGB", size, (200, 120, 40, 90)).save(path)


# ── Каталог: что попадает в сетку ────────────────────────────────────────

def check_catalog(base: Path) -> None:
    work = base / "проект"
    (work / "foto").mkdir(parents=True)
    (work / "downloads").mkdir()
    png(work / "заставка.png")
    png(work / "foto" / "купол.png")
    png(work / "downloads" / "макет.png")
    (work / "схема.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")

    # Не картинки и закрытое — в сетке их быть не должно
    (work / "заметка.md").write_text("текст", encoding="utf-8")
    (work / ".env").write_text("SECRET_KEY=xxx", encoding="utf-8")
    (work / "server.key").write_text("ключ", encoding="utf-8")
    (work / ".git").mkdir()
    png(work / ".git" / "аватар.png")
    (work / "__pycache__").mkdir()
    png(work / "__pycache__" / "мусор.png")

    # Питоновское окружение: имя любое, узнаётся по pyvenv.cfg
    venv = work / "pwenv"
    (venv / "lib" / "site-packages" / "playwright").mkdir(parents=True)
    (venv / "share").mkdir()
    (venv / "pyvenv.cfg").write_text("home = /usr", encoding="utf-8")
    png(venv / "lib" / "site-packages" / "playwright" / "значок.png")
    png(venv / "share" / "заставка-окружения.png")     # мимо `site-packages`

    # Ссылка наружу: строка в сетке обещала бы кадр, который всё равно отбивается
    outside = base / "чужое.png"
    png(outside)
    (work / "ссылка.png").symlink_to(outside)

    root = pic._Root("p1", "Проект", work.resolve(), "project", None)
    pic._roots = lambda: {"p1": root}                  # без базы: корень один, свой

    catalog = pic._catalog()
    group = catalog["groups"][0]
    shown = {i["src"] for f in group["folders"] for i in f["images"]}

    expected = {"p1/заставка.png", "p1/схема.svg", "p1/foto/купол.png",
                "p1/downloads/макет.png"}
    check(shown == expected,
          f"в сетке ровно картинки проекта (лишнее: {sorted(shown - expected)}, "
          f"пропало: {sorted(expected - shown)})")

    folders = {f["path"]: f["count"] for f in group["folders"]}
    check(folders == {"": 2, "downloads": 1, "foto": 1}, f"разбивка по папкам: {folders}")
    check([f["path"] for f in group["folders"]][0] == "",
          "корень проекта идёт первым, дальше папки по алфавиту")
    check(group["count"] == 4, f"счётчик группы: {group['count']}")

    svg = next(i for f in group["folders"] for i in f["images"] if i["src"].endswith(".svg"))
    raster = next(i for f in group["folders"] for i in f["images"] if i["name"] == "купол.png")
    check(svg["vector"] and raster["w"] == 40 and raster["h"] == 30,
          "у растра взяты ширина и высота, вектор помечен вектором")

    # Ключ из запроса: наружу не выпускать ничем
    escapes = {
        "p1/../чужое.png": "выход из каталога проекта",
        "p1/foto/../../чужое.png": ".. в середине пути",
        str(outside): "абсолютный путь",
        "p1/ссылка.png": "символьная ссылка наружу",
        "p1/.env": "файл настроек",
        "p1/заметка.md": "не картинка",
        "p1/.git/аватар.png": "картинка из служебной папки",
        "p1/pwenv/lib/site-packages/playwright/значок.png": "картинка из окружения",
        "p1/pwenv/share/заставка-окружения.png": "картинка из окружения мимо site-packages",
        "p1": "сам каталог проекта",
        "нет/картинка.png": "неизвестный источник",
    }
    for attempt, why in escapes.items():
        try:
            got = pic._resolve(attempt)
        except Exception as exc:                       # noqa: BLE001
            # Исключение вместо отказа — тот же провал: наружу страница отдаст 500
            check(False, f"{why} — ключ {attempt!r} уронил разбор: {exc}")
            break
        if got is not None:
            check(False, f"{why} — ключ {attempt!r} пропущен")
            break
    else:
        check(True, "ни один ключ наружу не выпущен: " + ", ".join(escapes.values()))

    inside = pic._resolve("p1/foto/купол.png")
    check(inside is not None and inside.path == (work / "foto" / "купол.png").resolve(),
          "обычный ключ внутри проекта разобран")


# ── Превью ───────────────────────────────────────────────────────────────

def check_thumbs(base: Path) -> None:
    from PIL import Image

    pic.THUMB_DIR = base / "thumbs"
    big = base / "большая.png"
    png(big, size=(1600, 900))

    first = pic._thumb(big)
    check(first.is_file() and first.suffix == ".webp", "превью сделано и лежит в складе")
    with Image.open(first) as im:
        check(max(im.size) == pic.THUMB_MAX and im.size == (480, 270),
              f"превью вписано в {pic.THUMB_MAX} px с сохранением пропорций: {im.size}")

    stamp = first.stat().st_mtime_ns
    time.sleep(0.01)
    again = pic._thumb(big)
    check(again == first and again.stat().st_mtime_ns == stamp,
          "второе обращение берёт готовое превью, а не делает заново")

    # Картинку поправили — имя превью считается от времени изменения, значит
    # новое. Иначе в сетке навсегда осталась бы прежняя редакция.
    time.sleep(0.01)
    png(big, size=(1600, 900))
    check(pic._thumb(big) != first, "правка картинки даёт новое превью, а не старое")

    clear = base / "прозрачная.png"
    png(clear, size=(60, 60), alpha=True)
    with Image.open(pic._thumb(clear)) as im:
        check(im.mode in ("RGBA", "LA", "P"),
              f"прозрачность сохранена, а не залита чёрным: режим {im.mode}")

    # Уборка склада: старое превью уходит, свежее остаётся
    old = pic._thumb(big)
    os.utime(old, (time.time() - 40 * 86400, time.time() - 40 * 86400))
    kept = pic._thumb(clear)
    pic.purge_thumbs(days=30)
    check(not old.exists() and kept.exists(), "уборка сносит залежавшиеся превью и щадит свежие")


# ── В браузере ───────────────────────────────────────────────────────────

BROWSER = r'''
import sys
from playwright.sync_api import sync_playwright

base, cookie = sys.argv[1:3]
fails = []
def check(ok, what):
    print(("OK   " if ok else "FAIL ") + what, flush=True)
    if not ok: fails.append(what)

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1500, "height": 900})
    ctx.add_cookies([{"name": "webui_session", "value": cookie, "url": base}])
    page = ctx.new_page()
    errors = []
    page.on("console", lambda m: m.type == "error" and errors.append(m.text))
    page.on("pageerror", lambda e: errors.append(str(e)))

    page.goto(base + "/pictures")
    page.wait_for_selector(".pic-tile", timeout=20000)

    # Вкладка стоит слева от «Журнала» — как просили
    nav = page.locator(".nav__item").all_inner_texts()
    check(nav.index("Картинки") == nav.index("Журнал") - 1,
          "вкладка «Картинки» стоит сразу слева от «Журнала»")

    tiles = page.locator(".pic-tile")
    check(tiles.count() > 5, "в сетке %d плиток" % tiles.count())
    groups = page.locator(".pic-node--group")
    folders = page.locator(".pic-node--folder")
    check(groups.count() >= 2 and folders.count() >= 2,
          "дерево разбито по проектам (%d) и папкам (%d)" % (groups.count(), folders.count()))

    # Превью не просто вставлены, а загрузились: битый адрес дал бы 0
    page.wait_for_function(
        "document.querySelector('.pic-tile img') && document.querySelector('.pic-tile img').naturalWidth > 0",
        timeout=20000)
    drawn = page.evaluate(
        "Array.from(document.querySelectorAll('.pic-tile img')).filter(i => i.naturalWidth > 0).length")
    check(drawn > 0, "превью действительно нарисованы (%d шт.)" % drawn)

    # Выбор папки в дереве меняет сетку
    was = tiles.count()
    folders.first.click()
    page.wait_for_timeout(200)
    check(page.locator(".pic-tile").count() != was or page.locator(".pic-node--folder.is-current").count() == 1,
          "нажатие на папку в дереве отбирает её кадры")
    page.locator(".pic-node--all").click()
    page.wait_for_timeout(200)

    # Просмотрщик: открылся, листается, масштаб меняется, закрывается
    first_name = page.locator(".pic-tile__name").first.inner_text()
    page.locator(".pic-tile").first.click()
    page.wait_for_selector("#pic-viewer[open]", timeout=5000)
    page.wait_for_function("document.getElementById('v-img').naturalWidth > 0", timeout=20000)
    check(page.locator("#v-name").inner_text() == first_name,
          "в просмотрщике открылась та картинка, по которой нажали")
    check(page.locator(".viewer__strip img").count() > 1, "лента кадров внизу собрана")

    shown_before = page.locator("#v-name").inner_text()
    page.locator("#v-next").click()
    page.wait_for_function("document.getElementById('v-img').naturalWidth > 0", timeout=20000)
    check(page.locator("#v-name").inner_text() != shown_before, "стрелка «вперёд» листает")
    page.locator("#v-prev").click()
    page.wait_for_timeout(200)
    check(page.locator("#v-name").inner_text() == shown_before, "стрелка «назад» возвращает")

    # «Вписать» — значит целиком, а не только по ширине: высокий кадр
    # (1280×1626 у первого же снимка) уезжал низом за нижний край окна
    box = page.evaluate("""() => {
        const img = document.getElementById('v-img'), st = document.getElementById('v-stage');
        return {w: img.clientWidth, h: img.clientHeight, sw: st.clientWidth, sh: st.clientHeight,
                over: st.scrollHeight - st.clientHeight};
    }""")
    check(box["h"] <= box["sh"] + 1 and box["w"] <= box["sw"] + 1 and box["over"] <= 1,
          "вписанный кадр помещается в окно целиком (%dx%d в %dx%d)"
          % (box["w"], box["h"], box["sw"], box["sh"]))

    # Масштаб. Сравнивать 1:1 со «вписать» нельзя: мелкий кадр вписывается
    # в своей величине, и оба значения совпали бы у исправного продукта
    fit_width = page.evaluate("document.getElementById('v-img').clientWidth")
    page.locator("#v-fit").click()          # «1:1»
    page.wait_for_timeout(200)
    one_to_one = page.evaluate("document.getElementById('v-img').clientWidth")
    natural = page.evaluate("document.getElementById('v-img').naturalWidth")
    check(one_to_one == natural,
          "кнопка 1:1 показывает кадр в натуральную величину (%d px)" % one_to_one)
    page.keyboard.press("+")
    page.keyboard.press("+")
    page.wait_for_timeout(200)
    bigger = page.evaluate("document.getElementById('v-img').clientWidth")
    check(bigger > natural, "«+» увеличивает кадр (%d px против %d)" % (bigger, natural))
    check(page.locator("#v-zoom").inner_text().startswith("156"),
          "показанный масштаб отвечает делу: " + page.locator("#v-zoom").inner_text())
    page.keyboard.press("0")
    page.wait_for_timeout(200)
    check(page.evaluate("document.getElementById('v-img').clientWidth") == fit_width,
          "клавиша 0 вписывает кадр обратно в окно")

    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    check(page.locator("#pic-viewer[open]").count() == 0, "Esc закрывает просмотрщик")

    # Поиск по имени
    page.fill("#pic-search", first_name[:4])
    page.wait_for_timeout(300)
    found = page.locator(".pic-tile").count()
    check(0 < found <= tiles.count(), "поиск по имени отбирает кадры (%d)" % found)

    check(not errors, "в консоли браузера пусто: " + "; ".join(errors[:3]))
    b.close()

print("BROWSER_FAILS", len(fails))
'''


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_ready(port: int, proc: subprocess.Popen, tries: int = 60) -> bool:
    for _ in range(tries):
        if proc.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=1) as res:
                if res.status == 200:
                    return True
        except Exception:                              # noqa: BLE001
            time.sleep(0.3)
    return False


def check_browser(base: Path) -> None:
    user = db.query_one("SELECT id FROM users ORDER BY id LIMIT 1")
    if not user:
        check(False, "в базе нет пользователя — некому открыть страницу")
        return

    session_id = auth.new_session_id()
    db.execute(
        "INSERT INTO sessions (id, user_id, expires_at, ip, user_agent) "
        "VALUES (%s, %s, %s, %s, %s)",
        (session_id, user["id"], auth.session_expiry(), "127.0.0.1", "check_pictures"),
    )

    port = free_port()
    url = f"http://127.0.0.1:{port}"
    # ROOT_PATH пустой: стенд слушает без nginx, и запрос за списком по
    # «/Claude/pictures/list» получал бы 404 — провал лёг бы на продукт
    env = dict(os.environ, ROOT_PATH="")
    proc = subprocess.Popen(
        [str(PROJECT_DIR / ".venv/bin/python"), "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=str(PROJECT_DIR), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        if not wait_ready(port, proc):
            check(False, "второй экземпляр приложения не поднялся")
            return
        script = base / "browser.py"
        script.write_text(BROWSER, encoding="utf-8")
        run = subprocess.run(
            [str(PROJECT_DIR / ".venv/bin/python"), str(script),
             url, auth.sign_session_id(session_id)],
            capture_output=True, text=True, timeout=300,
        )
        for line in run.stdout.splitlines():
            if line.startswith("OK   "):
                print("  ok: " + line[5:])
            elif line.startswith("FAIL "):
                FAILED.append(line[5:])
                print("  ПРОВАЛ: " + line[5:])
        if "BROWSER_FAILS" not in run.stdout:
            check(False, "браузерная часть не доиграла: " + (run.stderr or "")[-400:])
    finally:
        proc.terminate()
        proc.wait(timeout=20)
        db.execute("DELETE FROM sessions WHERE id = %s", (session_id,))


def main() -> int:
    db.init_pool()
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp).resolve()
        print("Каталог и ключи:")
        check_catalog(base)
        print("Превью:")
        check_thumbs(base)
        print("В браузере:")
        check_browser(base)

    if FAILED:
        print(f"\nПРОВАЛЕНО {len(FAILED)}:")
        for what in FAILED:
            print(" -", what)
        return 1
    print("\nOK: галерея показывает своё, чужого не отдаёт, листается и масштабируется")
    return 0


if __name__ == "__main__":
    sys.exit(main())
