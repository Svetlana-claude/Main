"""Проверка «Здоровья» в настоящем браузере: компьютер и телефон.

Поднимает второй экземпляр сайта на временной базе и свободном порту (Claude —
подставной), проходит первую настройку, вход с кодом, заводит членов семьи,
загружает бланк, проверяет и сохраняет разбор, смотрит график, записывает
болезнь и прививку, приглашает мужа, проводит запрос доступа «Принять» →
«Завершить». На каждой странице проверяет, что ничего не уезжает вбок.
Снимки — в zdorovye/tests/shots/.

    exchange/pwenv/bin/python zdorovye/tests/check_browser.py
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
BLANK = SITE / "tests" / "obrazec-blanka.png"
PASSWORD = "очень-длинный-пароль"
errors: list[str] = []


def totp(secret: str, shift: int = 0) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    digest = hmac.new(key, struct.pack(">Q", int(time.time()) // 30 + shift), hashlib.sha1).digest()
    o = digest[-1] & 0x0F
    return f"{(struct.unpack('>I', digest[o:o + 4])[0] & 0x7FFFFFFF) % 1_000_000:06d}"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_site() -> tuple[subprocess.Popen, str, str, str]:
    tmp = Path(tempfile.mkdtemp(prefix="zd-browser-"))
    (tmp / "site.env").write_text(f"SECRET_KEY=browser-test\nDATA_DIR={tmp / 'data'}\nLOGIN=Svetlana\n"
                                  f"CLAUDE_BIN={SITE / 'tests/fake_claude.py'}\n", encoding="utf-8")
    port = free_port()
    env = {**os.environ, "ZD_ENV": str(tmp / "site.env"), "ROOT_PATH": "", "ZD_INSECURE_COOKIE": "1",
           "ZD_KOPII": str(tmp / "kopii"), "FAKE_DATE": "2026-10-14", "FAKE_HB": "112"}
    out = subprocess.run([str(SITE / ".venv/bin/python"), "tools/prepare.py"], cwd=SITE, env=env,
                         capture_output=True, text=True, check=True).stdout.strip()
    token = out.rsplit("/", 1)[-1]
    seed = subprocess.run([str(SITE / ".venv/bin/python"), "-c",
                           "from app import db; print(db.one(\"SELECT value FROM setup WHERE key='totp_secret'\")['value'])"],
                          cwd=SITE, env=env, capture_output=True, text=True, check=True).stdout.strip()
    proc = subprocess.Popen([str(SITE / ".venv/bin/uvicorn"), "app.main:app", "--host", "127.0.0.1",
                             "--port", str(port)], cwd=SITE, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    for _ in range(50):
        try:
            urllib.request.urlopen(base + "/healthz", timeout=1)
            break
        except OSError:
            time.sleep(0.2)
    return proc, base, token, seed


def no_side_scroll(page, label: str) -> None:
    width = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
    if width > 1:
        errors.append(f"{label}: страница шире экрана на {width}px")


def shot(page, name: str) -> None:
    no_side_scroll(page, name)
    page.screenshot(path=str(SHOTS / f"{name}.png"), full_page=True)


def owner_flow(pw, base: str, token: str, secret: str, kind: str, size: dict, mobile: bool, first: bool):
    ctx = pw.chromium.launch().new_context(viewport=size, is_mobile=mobile, has_touch=mobile,
                                           accept_downloads=True)
    page = ctx.new_page()
    page.on("pageerror", lambda e: errors.append(f"{kind}: ошибка скрипта {e}"))
    page.on("console", lambda m: m.type == "error" and errors.append(f"{kind}: консоль {m.text}"))
    if first:
        page.goto(f"{base}/setup/{token}")
        expect(page.locator(".qr svg")).to_be_visible()
        shot(page, f"{kind}-0-nastroyka")
        page.fill("input[name=password]", PASSWORD)
        page.fill("input[name=password2]", PASSWORD)
        page.fill("input[name=code]", totp(secret))
        page.click("button[type=submit]")
        if page.locator(".error").count():
            errors.append(f"{kind}: настройка: {page.locator('.error').inner_text()}")
        expect(page.locator("h1")).to_have_text("Здоровье семьи")
    page.goto(f"{base}/login")
    shot(page, f"{kind}-1-vhod")
    page.fill("input[name=login]", "Svetlana")
    page.fill("input[name=password]", PASSWORD)
    page.click("button[type=submit]")
    page.fill("input[name=code]", totp(secret, 1))
    page.click("button[type=submit]")
    expect(page.locator("h1")).to_have_text("Семья")
    # Работник сайта зарегистрирован — телефон предложит «Установить»
    if not page.evaluate("navigator.serviceWorker.getRegistration().then(r => !!r)"):
        page.wait_for_timeout(1500)
        if not page.evaluate("navigator.serviceWorker.getRegistration().then(r => !!r)"):
            errors.append(f"{kind}: работник сайта не зарегистрировался")

    name = "Мария" if first else "Мария-2"
    page.click("summary:has-text('Добавить члена семьи')")
    page.fill("form[action$='/members/new'] input[name=name]", name)
    page.fill("form[action$='/members/new'] input[name=birth_date]", "1985-04-12")
    page.click("form[action$='/members/new'] button")
    expect(page.locator("h1")).to_contain_text(name)

    # Бланк: загрузить → разбор → проверка → сохранить
    page.set_input_files("input[type=file]", str(BLANK))
    page.click("text=Загрузить и разобрать")
    expect(page.locator("text=Сверь с бланком")).to_be_visible(timeout=30000)
    expect(page.locator("input[name=name]").first).to_have_value("Гемоглобин")
    shot(page, f"{kind}-2-blank-proverka")
    page.click("form.review button[type=submit]")
    expect(page.locator("h1")).to_contain_text(name)
    expect(page.locator("tr.out").first).to_contain_text("Гемоглобин")

    # Фигурка: кровь жёлтая (гемоглобин ниже нормы), подсказка и блок органа
    blood = page.locator('.organ[data-organ="blood"]')
    if "lvl-1" not in (blood.get_attribute("class") or ""):
        errors.append(f"{kind}: кровь не жёлтая при низком гемоглобине")
    if not mobile:
        page.locator('.organ[data-organ="liver"]').hover()
        expect(page.locator("#organ-tip")).to_contain_text("Печень")
        page.locator("#body").screenshot(path=str(SHOTS / f"{kind}-2b-figura-navedenie.png"))
    page.locator('.organ[data-organ="blood"]').click()
    expect(page.locator("#organ-blood")).to_be_visible()
    expect(page.locator("#organ-blood")).to_contain_text("Гемоглобин")
    page.locator("#body").screenshot(path=str(SHOTS / f"{kind}-2c-figura-krov.png"))
    page.click("button:has-text('Оценить')")
    expect(page.locator(".general")).to_contain_text("печень", timeout=30000)
    page.locator('.organ[data-organ="liver"]').click()
    expect(page.locator("#organ-liver")).to_contain_text("Пересдать АЛТ")
    no_side_scroll(page, f"{kind}-figura")
    page.locator("#body").screenshot(path=str(SHOTS / f"{kind}-2d-figura-ocenka.png"))

    # Болезнь и прививка
    page.click("summary:has-text('Записать болезнь')")
    page.fill("form[action$='/ill'] input[name=title]", "ОРВИ")
    page.fill("form[action$='/ill'] input[name=started]", "2026-02-01")
    page.fill("form[action$='/ill'] input[name=ended]", "2026-02-07")
    page.click("form[action$='/ill'] button")
    page.click("summary:has-text('Записать прививку')")
    page.fill("form[action$='/vac'] input[name=name]", "Грипп")
    page.fill("form[action$='/vac'] input[name=done_on]", "2025-10-01")
    page.fill("form[action$='/vac'] input[name=next_due]", "2026-11-20")
    page.click("form[action$='/vac'] button")
    expect(page.locator("#vac")).to_contain_text("скоро")
    shot(page, f"{kind}-3-stranichka")

    page.click("#labs table >> text=Гемоглобин")
    expect(page.locator("svg.chart")).to_be_visible()
    shot(page, f"{kind}-4-grafik")

    page.goto(f"{base}/")
    expect(page.locator(".person").first).to_contain_text("Вне нормы")
    shot(page, f"{kind}-5-semya")
    return ctx, page, name


def invite_flow(pw, base: str, ctx, page, kind: str, size: dict, mobile: bool):
    page.click("summary:has-text('Добавить члена семьи')")
    page.fill("form[action$='/members/new'] input[name=name]", "Андрей")
    page.click("form[action$='/members/new'] button")
    page.goto(f"{base}/access")
    page.select_option("select[name=member_id]", label="Андрей")
    page.click("text=Сделать ссылку")
    link = page.input_value("#invite")
    shot(page, f"{kind}-6-priglashenie")
    link = base + "/join/" + link.rsplit("/join/", 1)[1]

    other = pw.chromium.launch().new_context(viewport=size, is_mobile=mobile, has_touch=mobile).new_page()
    other.goto(link)
    other.fill("input[name=login]", "andrey")
    other.fill("input[name=password]", PASSWORD)
    other.fill("input[name=password2]", PASSWORD)
    other.click("button[type=submit]")
    expect(other.locator("h1")).to_have_text("Моя страничка")
    other.click("text=Попросить доступ >> nth=0")
    expect(other.locator("text=Запрос отправлен")).to_be_visible()
    shot(other, f"{kind}-7-muzh")

    page.goto(f"{base}/access")
    page.click("button:has-text('Принять')")
    expect(page.locator("button:has-text('Завершить')")).to_be_visible()
    shot(page, f"{kind}-8-dostupy")
    other.goto(f"{base}/")
    other.click("text=Открыть >> nth=1")
    expect(other.locator("h1")).not_to_contain_text("Не получилось")
    page.click("button:has-text('Завершить')")
    other.reload()
    expect(other.locator("h1")).to_have_text("Не получилось")


def main() -> None:
    SHOTS.mkdir(exist_ok=True)
    proc, base, token, secret = start_site()
    try:
        with sync_playwright() as pw:
            ctx, page, _ = owner_flow(pw, base, token, secret, "pc", {"width": 1280, "height": 900}, False, True)
            invite_flow(pw, base, ctx, page, "pc", {"width": 1280, "height": 900}, False)
            time.sleep(31)          # новый код для второго входа
            ctx, page, _ = owner_flow(pw, base, token, secret, "phone", {"width": 390, "height": 844}, True, False)
    finally:
        proc.terminate()
    if errors:
        print("\n".join(errors))
        sys.exit(1)
    print(f"всё прошло, снимки в {SHOTS}")


if __name__ == "__main__":
    main()
