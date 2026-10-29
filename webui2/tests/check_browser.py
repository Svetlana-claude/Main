"""Проверка в настоящем браузере: компьютер и телефон, с нажатием кнопок.

Поднимает второй экземпляр сайта на временной базе и свободном порту, проходит
первую настройку, вход, чат, проекты с темой, галочками и удалением, вкладки, замок (и в соседней вкладке), смену пароля,
выход. Снимки — в webui2/tests/shots/.

    exchange/pwenv/bin/python webui2/tests/check_browser.py [адрес живого сайта]

С адресом дополнительно открывает живой сайт и снимает страницу первой
настройки или входа (ничего там не вводит).
"""
import base64
import hashlib
import hmac
import os
import re
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

SITE = Path(__file__).resolve().parents[1]
SHOTS = SITE / "tests" / "shots"
SECRET = "JBSWY3DPEHPK3PXP"
PASSWORD = "очень-длинный-пароль"
LOCK = "2468"
used_steps: set[int] = set()


def totp() -> str:
    """Свежий код, ни разу не использованный (сайт повтор не принимает)."""
    while True:
        step = int(time.time()) // 30
        if step not in used_steps:
            used_steps.add(step)
            break
        time.sleep(1)
    key = base64.b32decode(SECRET)
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    off = digest[-1] & 0x0F
    return f"{(struct.unpack('>I', digest[off:off + 4])[0] & 0x7FFFFFFF) % 1_000_000:06d}"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


SITE_RUN: dict = {}


def start_site() -> tuple[subprocess.Popen, str]:
    tmp = Path(tempfile.mkdtemp(prefix="webui2-browser-"))
    env_file = tmp / "site.env"
    env_file.write_text(f"SECRET_KEY=browser-test\nDB_PATH={tmp / 'site.db'}\nLOGIN=Svetlana\n"
                        f"CLAUDE_BIN={SITE / 'tests/fake_claude.py'}\nCHAT_DIR={tmp / 'room'}\n"
                        f"PROJECTS_DIR={tmp / 'projects'}\n"
                        f"POWER_CMD={SITE / '.venv/bin/python'} {SITE / 'tests/fake_power.py'}\n")
    env = {**os.environ, "WEBUI2_ENV": str(env_file), "ROOT_PATH": "", "WEBUI2_INSECURE_COOKIE": "1",
           "FAKE_POWER_LOG": str(tmp / "power.log")}
    # Замеры нагрузки за сутки — чтобы были графики (с перерывом в середине)
    seed = ("import math; from datetime import datetime, timedelta, timezone; from app import db; db.init(); "
            f"db.run(\"INSERT INTO setup (key, value) VALUES ('totp_secret', '{SECRET}')\"); "
            "now = datetime.now(timezone.utc); "
            "[db.run('INSERT INTO load_samples (at, cpu, mem, disk) VALUES (?, ?, ?, ?)', "
            "((now - timedelta(minutes=5 * i)).isoformat(), 20 + 15 * math.sin(i / 20), 45 + i / 40, 57)) "
            "for i in range(1, 288) if not 100 < i < 112]")
    subprocess.run([str(SITE / ".venv/bin/python"), "-c", seed], cwd=SITE, env=env, check=True)
    SITE_RUN.update(env=env, port=free_port(), tmp=tmp)
    return launch(), f"http://127.0.0.1:{SITE_RUN['port']}"


def launch() -> subprocess.Popen:
    base = f"http://127.0.0.1:{SITE_RUN['port']}"
    proc = subprocess.Popen([str(SITE / ".venv/bin/uvicorn"), "app.main:app", "--host", "127.0.0.1",
                             "--port", str(SITE_RUN["port"])], cwd=SITE, env=SITE_RUN["env"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    SITE_RUN["proc"] = proc
    for _ in range(50):
        try:
            urllib.request.urlopen(base + "/healthz", timeout=1)
            return proc
        except OSError:
            time.sleep(0.2)
    proc.kill()
    raise SystemExit("сайт не поднялся")


def restart_site() -> None:
    """Как сделала бы служба по команде обёртки: остановить и поднять снова."""
    SITE_RUN["proc"].terminate()
    SITE_RUN["proc"].wait(timeout=20)
    time.sleep(1.5)
    launch()


def watch(page, errors: list) -> None:
    # Отказ на неверный пароль или код — ожидаемый ответ, а не поломка; пока
    # сайт перезапускается, страница стучится в закрытую дверь — тоже ожидаемо
    expected = ("status of 400", "status of 401", "status of 429")
    page.on("console", lambda m: m.type == "error" and not any(e in m.text for e in expected)
            and not (SITE_RUN.get("restarting") and "ERR_CONNECTION_REFUSED" in m.text)
            and errors.append(f"{page.url}: {m.text}"))
    page.on("pageerror", lambda e: errors.append(f"{page.url}: {e}"))


def no_side_scroll(page, label: str) -> None:
    width = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
    assert width <= 0, f"{label}: страница едет вбок на {width}px"


def open_list(page, mobile: bool) -> None:
    """На телефоне список разговоров спрятан за кнопкой «‹ Разговоры»."""
    if mobile and page.locator("#to-list").is_visible():
        page.click("#to-list")


def ask(page, text: str, keys: bool = False) -> None:
    page.fill("#text", text)
    if keys:
        # Enter — новая строка, Ctrl+Enter — отправка
        page.press("#text", "Enter")
        expect(page.locator("#text")).to_have_value(text + "\n")
        page.press("#text", "Control+Enter")
    else:
        page.click("#send-btn")


def chat_flow(page, name: str, mobile: bool, viewport: dict, first: bool) -> None:
    tabs = page.locator("nav.tabs").bounding_box()
    if mobile:
        assert tabs["y"] > viewport["height"] - 80, "на телефоне вкладки не внизу"
    else:
        assert tabs["y"] < 60, "на компьютере вкладки не в шапке"
    if first:
        expect(page.locator(".conv-list")).to_contain_text("Разговоров пока нет")
        page.screenshot(path=SHOTS / f"{name}-4-chat-pusto.png")
    open_list(page, mobile)
    page.click("text=Новый разговор")
    expect(page.locator("#talk-title")).to_have_text("Новый разговор")

    # Ответ идёт потоком; пока идёт — дописка
    ask(page, "медленно расскажи про кота")
    expect(page.locator("#live")).to_be_visible()
    expect(page.locator("#send-btn")).to_have_text("Дописать")
    ask(page, "и про чай")
    expect(page.locator(".pending")).to_contain_text("и про чай")
    page.screenshot(path=SHOTS / f"{name}-5-chat-otvet-idet.png")
    expect(page.locator(".msg-assistant:not(.live)")).to_have_count(2, timeout=60000)
    expect(page.locator("#send-btn")).to_have_text("Отправить")
    expect(page.locator(".md table").first).to_be_visible()
    expect(page.locator("#talk-title")).to_have_text("медленно расскажи про кота")
    no_side_scroll(page, "разговор")
    page.screenshot(path=SHOTS / f"{name}-6-chat.png")

    # Уход со страницы во время ответа: ответ не обрывается
    ask(page, "медленно ещё раз")
    expect(page.locator("#live")).to_be_visible()
    page.click("[aria-label=Настройки]")
    page.go_back()
    expect(page.locator(".msg-assistant:not(.live)")).to_have_count(3, timeout=60000)

    # Модель, переименование
    page.select_option("#model", "opus")
    page.wait_for_load_state()
    expect(page.locator("#model")).to_have_value("opus")
    page.click("#rename-btn")
    page.fill("#rename-input", "Про кота и чай")
    page.click("#rename-form button[type=submit]")
    expect(page.locator("#talk-title")).to_have_text("Про кота и чай")

    # Поиск
    open_list(page, mobile)
    page.fill(".search input", "КОТА")
    page.press(".search input", "Enter")
    expect(page.locator(".results li").first).to_be_visible()
    page.screenshot(path=SHOTS / f"{name}-7-poisk.png", full_page=True)
    page.click(".results li a >> nth=0")
    expect(page.locator("#talk-title")).to_have_text("Про кота и чай")

    # Второй разговор и его удаление с вопросом
    open_list(page, mobile)
    page.click("text=Новый разговор")
    ask(page, "привет", keys=not mobile)
    expect(page.locator(".msg-assistant:not(.live)")).to_have_count(1, timeout=30000)
    page.once("dialog", lambda d: d.accept() if d.message == "Удалить?" else d.dismiss())
    page.click("[aria-label='Удалить разговор']")
    expect(page.locator("#talk-title")).to_have_text("Про кота и чай")


def settings_flow(page, name: str, mobile: bool) -> None:
    # Нагрузка: графики за сутки, подсказка при наведении, замер по кнопке
    expect(page.locator(".chart")).to_have_count(3)
    page.locator(".chart svg").first.scroll_into_view_if_needed()
    box = page.locator(".chart svg").first.bounding_box()
    page.mouse.move(box["x"] + box["width"] * 0.7, box["y"] + box["height"] * 0.4)
    expect(page.locator(".chart .tip").first).to_contain_text(" %")
    page.click("#load-btn")
    expect(page.locator("#load-cpu-note")).to_contain_text("сейчас")
    expect(page.locator("#load-mem-note")).to_contain_text("ГБ из")
    no_side_scroll(page, "настройки")
    page.screenshot(path=SHOTS / f"{name}-5-nastroyki.png", full_page=True)

    # Часовой пояс: Самара и обратно Москва
    page.select_option("#zone-select", "Europe/Samara")
    page.click("#zone-form button")
    expect(page.locator("#zone-form + p")).to_contain_text("по Самаре")
    page.select_option("#zone-select", "Europe/Moscow")
    page.click("#zone-form button")
    expect(page.locator("#zone-form + p")).to_contain_text("по Москве")

    # Перезапуск сайта: «Перезапускаю…», сайт поднялся — страница обновилась сама
    page.evaluate("window.__before = 1")
    page.once("dialog", lambda d: d.accept())
    page.click("[data-power=site]")
    expect(page.locator("#power-msg")).to_have_text("Перезапускаю сайт…")
    page.screenshot(path=SHOTS / f"{name}-5b-perezapusk.png")
    log = SITE_RUN["tmp"] / "power.log"
    assert log.read_text().split()[-1] == "restart-site"
    SITE_RUN["restarting"] = True
    restart_site()
    page.wait_for_function("window.__before === undefined", timeout=30000)
    SITE_RUN["restarting"] = False
    expect(page.locator(".panel h1")).to_have_text("Настройки")
    expect(page.locator("#power-msg")).to_be_hidden()
    expect(page.locator("[data-power=site]")).to_be_enabled()


def project_flow(page, name: str, mobile: bool) -> None:
    page.click("nav.tabs >> text=Проекты")
    expect(page.locator(".panel h1")).to_have_text("Проекты")
    title = f"Сайт про кота ({name})"
    page.fill("#project-name-input", title)
    page.click("#new-project button")
    expect(page.locator("#project-name")).to_have_text(title)
    expect(page.locator(".conv-list")).to_contain_text("Тем пока нет")
    no_side_scroll(page, "пустой проект")
    page.screenshot(path=SHOTS / f"{name}-p1-proekt.png")
    page.click("text=Новая тема")
    expect(page.locator("#talk-title")).to_have_text("Новая тема")
    expect(page.locator("#model")).to_have_value("opus")

    # Строка «что делает» под ответом
    ask(page, "медленно глянь файлы")
    expect(page.locator("#live-status")).to_have_text("Читаю CLAUDE.md…")
    page.screenshot(path=SHOTS / f"{name}-p2-tema-chitaet.png")
    expect(page.locator(".msg-assistant:not(.live)")).to_have_count(1, timeout=60000)
    expect(page.locator("#talk-title")).to_have_text("медленно глянь файлы")
    no_side_scroll(page, "тема")

    # Файлы: Claude кладёт файл в загрузки — список обновляется сам;
    # загрузка своего файла; просмотр .md
    sample = SHOTS / "план поездки.md"
    sample.write_text("# План\n\n- **лодка**\n- вёсла\n", encoding="utf-8")
    if mobile:
        # На телефоне — значок папки в шапке темы
        page.click("#files-btn")
        expect(page.locator(".files-title")).to_be_visible()
    else:
        expect(page.locator(".files-col")).to_be_visible()
        ask(page, "положи в загрузки")
        expect(page.locator(".file-list")).to_contain_text("ответ.md", timeout=30000)
    page.set_input_files("#upload-input", str(sample))
    expect(page.locator("#upload-msg")).to_have_text("Загружено", timeout=30000)
    expect(page.locator(".file-list li").first).to_contain_text("план поездки.md")
    no_side_scroll(page, "файлы")
    page.screenshot(path=SHOTS / f"{name}-p3a-faily.png")
    page.click(".file-list >> text=план поездки.md")
    expect(page.locator(".file-md strong")).to_have_text("лодка")
    page.screenshot(path=SHOTS / f"{name}-p3b-fayl.png", full_page=True)
    page.click(f"text=‹ {title}")
    expect(page.locator("#talk-title")).to_have_text("медленно глянь файлы")
    sample.unlink()

    # Разрешение: Claude просит — кружок оранжевый, на щите 1; «Разрешить» —
    # Claude продолжает, ответ дописан
    ask(page, "спроси разрешения")
    expect(page.locator("#live-status")).to_contain_text("Жду твоего разрешения", timeout=20000)
    expect(page.locator("#ask-count")).to_have_text("1", timeout=10000)
    expect(page.locator(".talk-head .light")).to_have_class(re.compile("wait"), timeout=10000)
    expect(page.locator(".conv-list [aria-current=page] .light")).to_have_class(re.compile("wait"))
    page.screenshot(path=SHOTS / f"{name}-p4a-zhdyot.png")
    page.click("[aria-label='Разрешения']")
    expect(page.locator(".asks")).to_contain_text("curl -s https://example.com")
    no_side_scroll(page, "разрешения")
    page.screenshot(path=SHOTS / f"{name}-p4b-razresheniya.png", full_page=True)
    page.click(".asks >> text=Разрешить")
    expect(page.locator(".done li").first).to_contain_text("разрешено")
    expect(page.locator("#ask-count")).to_be_hidden()
    page.click(".done li >> nth=0 >> a")
    expect(page.locator(".msg-assistant:not(.live)").last).to_contain_text("разрешили", timeout=30000)
    expect(page.locator(".talk-head .light")).to_have_class(re.compile("free"), timeout=10000)

    # Галочка «Запускать команды»
    open_list(page, mobile)
    with page.expect_navigation():
        page.check("text=Запускать команды")
    open_list(page, mobile)
    expect(page.locator("input[name=commands]")).to_be_checked()
    expect(page.locator(".access .small")).to_contain_text("запускает команды")
    page.screenshot(path=SHOTS / f"{name}-p3-galochki.png")

    # Удаление: список, «Отмена», снова — «Да, удалить»
    page.once("dialog", lambda d: d.accept())
    page.click("[aria-label='Удалить проект']")
    expect(page.locator("h1")).to_contain_text("Удаление проекта")
    expect(page.locator("#delete-report")).to_contain_text("fake-test.service", timeout=20000)
    no_side_scroll(page, "удаление проекта")
    page.screenshot(path=SHOTS / f"{name}-p4-udalenie.png", full_page=True)
    page.click("#delete-no")
    expect(page.locator("#talk-title")).to_have_text("медленно глянь файлы")
    open_list(page, mobile)
    page.once("dialog", lambda d: d.accept())
    page.click("[aria-label='Удалить проект']")
    expect(page.locator("#delete-yes")).to_be_visible(timeout=20000)
    page.click("#delete-yes")
    expect(page.locator(".panel h1")).to_have_text("Проекты", timeout=20000)
    expect(page.locator(".projects")).to_have_count(0)


def run(pw, base: str, name: str, viewport: dict, mobile: bool, first: bool) -> list:
    errors: list = []
    browser = pw.chromium.launch()
    ctx = browser.new_context(viewport=viewport, is_mobile=mobile, has_touch=mobile)
    page = ctx.new_page()
    watch(page, errors)

    page.goto(base + "/")
    if first:
        expect(page.locator("h1")).to_have_text("Первая настройка")
        no_side_scroll(page, "настройка")
        page.screenshot(path=SHOTS / f"{name}-1-nastroyka.png", full_page=True)
        page.fill("input[name=password]", PASSWORD)
        page.fill("input[name=password2]", PASSWORD)
        page.fill("input[name=lock]", LOCK)
        page.fill("input[name=lock2]", LOCK)
        page.fill("input[name=code]", totp())
        page.click("button[type=submit]")

    expect(page.locator("h1")).to_have_text("Вход")
    no_side_scroll(page, "вход")
    page.screenshot(path=SHOTS / f"{name}-2-vhod.png", full_page=True)
    page.fill("input[name=login]", "Svetlana")
    page.fill("input[name=password]", "не-тот-пароль")
    page.click("button[type=submit]")
    expect(page.locator(".error")).to_have_text("Неверный логин или пароль")
    page.fill("input[name=login]", "Svetlana")
    page.fill("input[name=password]", PASSWORD)
    page.click("button[type=submit]")
    expect(page.locator("h1")).to_have_text("Код с телефона")
    page.screenshot(path=SHOTS / f"{name}-3-kod.png", full_page=True)
    page.fill("input[name=code]", totp())
    page.click("button[type=submit]")

    chat_flow(page, name, mobile, viewport, first)
    project_flow(page, name, mobile)

    page.click("nav.tabs >> text=Проекты")
    expect(page.locator(".panel h1")).to_have_text("Проекты")
    page.click("[aria-label=Разрешения]")
    expect(page.locator(".panel h1")).to_have_text("Разрешения")
    page.click("[aria-label=Настройки]")
    expect(page.locator(".panel h1")).to_have_text("Настройки")
    settings_flow(page, name, mobile)

    # Замок: закрывается здесь — закрывается и в соседней вкладке
    other = ctx.new_page()
    watch(other, errors)
    other.goto(base + "/projects")
    expect(other.locator(".panel h1")).to_have_text("Проекты")
    page.bring_to_front()
    page.click("#lock-btn")
    expect(page.locator("h1")).to_have_text("Закрыто замком")
    page.screenshot(path=SHOTS / f"{name}-6-zamok.png", full_page=True)
    expect(other.locator("h1")).to_have_text("Закрыто замком", timeout=5000)
    page.reload()
    expect(page.locator("h1")).to_have_text("Закрыто замком")
    page.fill("input[name=code]", "0000")
    page.click("button.primary")
    expect(page.locator(".error")).to_have_text("Код не подошёл")
    page.fill("input[name=code]", LOCK)
    page.click("button.primary")
    expect(page.locator(".panel h1")).to_have_text("Настройки")
    other.bring_to_front()
    other.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
    expect(other.locator(".panel h1")).to_have_text("Проекты", timeout=5000)
    other.close()

    # Смена пароля туда и обратно
    page.bring_to_front()
    new = "второй-длинный-пароль"
    for old, fresh in ((PASSWORD, new), (new, PASSWORD)):
        page.fill("input[name=old]", old)
        page.fill("input[name=new]", fresh)
        page.fill("input[name=new2]", fresh)
        page.click("text=Сменить пароль")
        expect(page.locator(".ok")).to_have_text("Пароль изменён")

    page.click("text=Выйти")
    expect(page.locator("h1")).to_have_text("Вход")
    page.goto(base + "/settings")
    expect(page.locator("h1")).to_have_text("Вход")
    browser.close()
    return errors


def live(pw, url: str) -> list:
    errors: list = []
    browser = pw.chromium.launch()
    for name, vp, mobile in (("live-pc", {"width": 1440, "height": 900}, False),
                             ("live-phone", {"width": 390, "height": 844}, True)):
        page = browser.new_context(viewport=vp, is_mobile=mobile).new_page()
        watch(page, errors)
        page.goto(url)
        expect(page.locator("h1")).to_have_text("Первая настройка" if page.url.endswith("/setup") else "Вход")
        no_side_scroll(page, name)
        page.screenshot(path=SHOTS / f"{name}.png", full_page=True)
    browser.close()
    return errors


def main() -> None:
    SHOTS.mkdir(exist_ok=True)
    _, base = start_site()
    try:
        with sync_playwright() as pw:
            errors = run(pw, base, "pc", {"width": 1440, "height": 900}, False, first=True)
            errors += run(pw, base, "phone", {"width": 390, "height": 844}, True, first=False)
            if len(sys.argv) > 1:
                errors += live(pw, sys.argv[1])
    finally:
        SITE_RUN["proc"].terminate()
    if errors:
        raise SystemExit("ошибки в консоли:\n" + "\n".join(errors))
    print("всё прошло, снимки в", SHOTS)


if __name__ == "__main__":
    main()
