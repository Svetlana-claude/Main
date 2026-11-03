#!/usr/bin/env python3
"""Контроль оплат и состояния сайтов — каждое утро по расписанию (crontab mokeeva).

    python3 infra/kontrol/kontrol.py               — проверить, письмо по правилам ниже
    python3 infra/kontrol/kontrol.py --pismo       — письмо в любом случае
    python3 infra/kontrol/kontrol.py --bez-pisma   — только отчёт в «Файлы проекта»

Письмо уходит, если: что-то сломано или устарело; до оплаты 30, 7, 3, 2, 1 день или срок
прошёл; по понедельникам — сводка в любом случае. Отчёт всегда кладётся в
glavpryg-sayt/downloads/kontrol-sostoyanie.txt.

Что проверяется:
  оплаты  — сроки доменов (whois), счёт и дни до блокировки Beget (API, нужен
            ~/.config/kontrol/beget-api.json), даты из oplaty.json, записанные вручную;
            счёт Selectel — нет: ключ на чтение счёта открывает весь аккаунт, пишет сам Selectel;
  сайты   — страницы и админка отвечают, картинки и видео главной грузятся, формы на месте,
            сертификат HTTPS не истекает;
  свежесть — ночные копии (образ и Главпрыг ушли в Selectel), копия Главпрыга на сервере,
            погода игры, правки, ждущие выкладки на хостинг, место на диске сервера;
  почта   — записи SPF и DKIM домена (без них Gmail отвергает письма сервера).
Время в письме — московское. Пароли и ключи в отчёт не попадают.
"""
import json
import os
import re
import shutil
import socket
import ssl
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path

H = Path("/home/mokeeva")
MSK = timezone(timedelta(hours=3))
SEYCHAS = datetime.now(timezone.utc)
NASTROYKI = json.loads((Path(__file__).parent / "oplaty.json").read_text(encoding="utf-8"))
KLYUCHI = H / ".config/kontrol"
OTCHET = H / "main/glavpryg-sayt/downloads/kontrol-sostoyanie.txt"
OT_KOGO = "glavpryg@mokeevasky.ru"
SROKI_PISMA = {30, 7, 3, 2, 1}

# Сайты: адрес — что проверяем. Главпрыг живёт на Beget (glavprig.ru), пока Beget лежит —
# временная копия на mokeevasky.ru/glavpryg; проверяются обе.
SAYTY = {
    "glavprig.ru (боевой Главпрыг, Beget)": "http://glavprig.ru",
    "mokeevasky.ru/glavpryg (копия Главпрыга на нашем сервере)": "https://mokeevasky.ru/glavpryg",
}
STRANICY = ["/", "/test", "/services/obuchenie", "/certificate", "/certificate/order", "/admin/login"]
FORMY = {"/certificate/order": "заказ сертификата"}
NASH_SAYT = "https://mokeevasky.ru/"

beda, oplaty, nuzhno, horosho = [], [], [], []


def msk(dt: datetime) -> str:
    return dt.astimezone(MSK).strftime("%d.%m.%Y %H:%M") + " мск"


def zapros(url: str, timeout: int = 20) -> tuple[int, bytes, str]:
    """Код ответа, тело, конечный адрес. 0 — сайт не ответил."""
    req = urllib.request.Request(url, headers={"User-Agent": "kontrol-mokeevasky/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(3_000_000), r.geturl()
    except urllib.error.HTTPError as e:
        return e.code, b"", url
    except Exception:
        return 0, b"", url


# ── Оплаты ──────────────────────────────────────────────────────────────────
def srok(chto: str, do: datetime | None, gde: str, skolko: str = "") -> None:
    if do is None:
        nuzhno.append(f"{chto}: не знаю, до какого числа оплачено ({gde}). Напиши дату.")
        return
    dney = (do.astimezone(MSK).date() - SEYCHAS.astimezone(MSK).date()).days
    stroka = f"{chto}: оплачено до {do.astimezone(MSK):%d.%m.%Y}, осталось {dney} дн. Где платить: {gde}.{skolko}"
    if dney < 0:
        beda.append(f"{chto}: СРОК ОПЛАТЫ ПРОШЁЛ {do.astimezone(MSK):%d.%m.%Y}. Где платить: {gde}.")
    elif dney <= 30:
        oplaty.append((dney, stroka))
    else:
        horosho.append(stroka)


def domeny() -> None:
    for d in NASTROYKI["domeny"]:
        imya = d.get("imya", d["domen"])
        try:
            t = subprocess.run(["whois", d["domen"]], capture_output=True, text=True, timeout=60).stdout
            m = re.search(r"paid-till:\s*(\S+)", t) or re.search(r"Expiry Date:\s*(\S+)", t)
            do = datetime.fromisoformat(m.group(1).replace("Z", "+00:00"))
        except Exception:
            nuzhno.append(f"Домен {imya}: не удалось узнать срок — проверю завтра.")
            continue
        srok(f"Домен {imya}", do, d["gde"])


def beget() -> None:
    f = KLYUCHI / "beget-api.json"
    if not f.exists():
        nuzhno.append("Хостинг Beget: нет доступа к счёту — нужен API-пароль Beget (как сделать — в переписке).")
        return
    k = json.loads(f.read_text())
    q = urllib.parse.urlencode({"login": k["login"], "passwd": k["passwd"], "output_format": "json"})
    kod, telo, _ = zapros(f"https://api.beget.com/api/user/getAccountInfo?{q}")
    try:
        r = json.loads(telo)["answer"]["result"]
    except Exception:
        beda.append(f"Хостинг Beget: счёт не узнать — Beget не отвечает (код {kod}).")
        return
    balans = float(r.get("user_balance", 0))
    dney = int(r.get("user_days_to_block", 0))
    srok("Хостинг Beget", SEYCHAS + timedelta(days=dney), "beget.com → Финансы → Пополнить",
         f" На счёте {balans:.0f} ₽, тариф {r.get('plan_name', '?')}.")


def selectel() -> None:
    f = KLYUCHI / "selectel-api.json"
    if not f.exists():
        # Ключ на чтение счёта у Selectel даёт права на весь аккаунт — не берём; о низком
        # счёте Selectel пишет сам (уведомления в «Биллинге»)
        horosho.append("Хранилище копий Selectel: о низком счёте предупреждает сам Selectel.")
        return
    tok = json.loads(f.read_text())["token"]
    req = urllib.request.Request("https://api.selectel.ru/v3/balances", headers={"X-Token": tok})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.load(r)
    except Exception as e:
        beda.append(f"Хранилище копий Selectel: счёт не узнать ({type(e).__name__}).")
        return
    # Сумма в копейках; берём основной счёт
    dannye = d.get("data", d)
    rub = None
    for klyuch in ("main", "balance", "total"):
        if isinstance(dannye.get(klyuch), (int, float)):
            rub = dannye[klyuch] / 100
            break
    if rub is None:
        nuzhno.append("Selectel: ответ о счёте непонятного вида — разберусь.")
        return
    stroka = f"Хранилище копий Selectel: на счёте {rub:.0f} ₽. Где пополнять: my.selectel.ru → Биллинг."
    if rub < 100:
        beda.append(stroka + " Осталось меньше 100 ₽ — при нуле копии удалят через 30 дней.")
    else:
        horosho.append(stroka)


def ruchnye() -> None:
    for o in NASTROYKI["ruchnye"]:
        do = datetime.fromisoformat(o["do"]).replace(tzinfo=MSK) if o["do"] else None
        srok(o["chto"], do, o["gde"])


# ── Сайты ───────────────────────────────────────────────────────────────────
def sayt(nazvanie: str, osnova: str) -> None:
    plohie = []
    kod, telo, konec = zapros(osnova + "/")
    if kod == 0:
        beda.append(f"{nazvanie}: не открывается — сервер не отвечает.")
        return
    if konec.split("/")[2] != osnova.split("/")[2]:
        horosho.append(f"{nazvanie}: переадресует на {konec.split('/')[2]} — так и задумано.")
        return
    for put in STRANICY:
        k, t, _ = zapros(osnova + put)
        if k >= 400 or k == 0:
            plohie.append(f"{put} — ошибка {k or 'нет ответа'}")
        elif put in FORMY and b"<form" not in t:
            plohie.append(f"{put} — пропала форма «{FORMY[put]}»")
    # Картинки и видео главной: до 12 штук
    html = telo.decode("utf-8", "replace")
    faily = []
    for m in re.finditer(r'(?:src|poster)="([^"]+\.(?:webp|jpe?g|png|svg|mp4|webm))"', html):
        u = urllib.parse.urljoin(osnova + "/", m.group(1))
        if u not in faily:
            faily.append(u)
    for u in faily[:12]:
        k, _, _ = zapros(u)
        if k >= 400 or k == 0:
            plohie.append(f"не грузится {urllib.parse.urlparse(u).path}")
    if plohie:
        beda.append(f"{nazvanie}: " + "; ".join(plohie) + ".")
    else:
        horosho.append(f"{nazvanie}: {len(STRANICY)} страниц, формы и {min(12, len(faily))} картинок и видео — в порядке.")


def https(host: str) -> None:
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, 443), timeout=15) as s, ctx.wrap_socket(s, server_hostname=host) as t:
            do = datetime.fromtimestamp(ssl.cert_time_to_seconds(t.getpeercert()["notAfter"]), timezone.utc)
    except (ConnectionRefusedError, socket.timeout, OSError) as e:
        if host == "glavprig.ru":
            nuzhno.append("glavprig.ru: защищённое соединение (HTTPS) не включено или не отвечает.")
        else:
            beda.append(f"{host}: защищённое соединение не работает ({type(e).__name__}).")
        return
    dney = (do - SEYCHAS).days
    # Сертификаты продлеваются сами за 30 дней до конца; меньше 14 — продление сломалось
    (beda if dney < 14 else horosho).append(
        f"{host}: замочек в браузере действует до {do.astimezone(MSK):%d.%m.%Y}"
        + (" — САМ НЕ ПРОДЛИЛСЯ." if dney < 14 else "."))


# ── Свежесть ────────────────────────────────────────────────────────────────
def posledniy_raz(zhurnal: Path, metka: str) -> datetime | None:
    if not zhurnal.exists():
        return None
    for s in reversed(zhurnal.read_text(encoding="utf-8", errors="replace").splitlines()):
        if metka in s:
            m = re.match(r"(\d\d\.\d\d\.\d{4} \d\d:\d\d)", s)
            if m:
                return datetime.strptime(m.group(1), "%d.%m.%Y %H:%M").replace(tzinfo=timezone.utc)
    return None


def svezhest() -> None:
    proverki = [
        ("Ночной образ сервера в хранилище Selectel", posledniy_raz(H / "backups/obraz.log", "образ в хранилище Selectel"), 30),
        ("Копия Главпрыга в хранилище Selectel", posledniy_raz(H / "backups/glavpryg/na-disk.log", "копия в Selectel"), 30),
    ]
    kopii = sorted((H / "backups/glavpryg").glob("glavpryg-rezerv-*.tar"), key=lambda p: p.stat().st_mtime)
    proverki.append(("Копия Главпрыга на сервере",
                     datetime.fromtimestamp(kopii[-1].stat().st_mtime, timezone.utc) if kopii else None, 30))
    pogoda = Path("/var/www/glavpryg/public/igra-app/pogoda-dnya.json")
    proverki.append(("Погода в игре", datetime.fromtimestamp(pogoda.stat().st_mtime, timezone.utc) if pogoda.exists() else None, 4))
    for chto, kogda, chasov in proverki:
        if kogda is None:
            beda.append(f"{chto}: ни разу не было.")
        elif SEYCHAS - kogda > timedelta(hours=chasov):
            beda.append(f"{chto}: последний раз {msk(kogda)} — устарело.")
        else:
            horosho.append(f"{chto}: {msk(kogda)}.")

    # Правки, которые ждут выкладки на хостинг (их кладёт ~/tools/beget/obnovit.py по расписанию)
    cron = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
    if "beget && .venv/bin/python obnovit.py" in cron:
        nuzhno.append("На хостинге Beget не хватает последних правок сайта: встанут сами, когда Beget ответит.")

    svobodno = shutil.disk_usage("/").free / 2**30
    (beda if svobodno < 2 else horosho).append(f"Место на диске сервера: свободно {svobodno:.1f} ГБ"
                                               + (" — мало, ночные копии могут не собраться." if svobodno < 2 else "."))


def pochta() -> None:
    """Письма с сервера (сертификаты покупателям, эти отчёты) Gmail принимает только с
    записями SPF и DKIM у домена — см. glavpryg-sayt/pochta.md."""
    def txt(imya: str) -> str:
        return subprocess.run(["dig", "+short", "TXT", imya], capture_output=True, text=True, timeout=30).stdout
    net = [z for z, ok in (("SPF", "v=spf1" in txt("mokeevasky.ru")),
                           ("DKIM", "v=DKIM1" in txt("mail._domainkey.mokeevasky.ru"))) if not ok]
    if net:
        beda.append("Почта с сервера: у mokeevasky.ru нет записей " + " и ".join(net)
                    + " — Gmail и другие почты не принимают письма сайта (сертификаты покупателям, заявки).")
    else:
        horosho.append("Почта с сервера: записи SPF и DKIM на месте.")


# ── Письмо ──────────────────────────────────────────────────────────────────
def otchet() -> str:
    chasti = [f"Проверка {msk(SEYCHAS)}", ""]
    if beda:
        chasti += ["⚠ ЧТО НЕ ТАК", *[f"• {s}" for s in beda], ""]
    if oplaty:
        chasti += ["💳 СКОРО ПЛАТИТЬ", *[f"• {s}" for _, s in sorted(oplaty)], ""]
    if nuzhno:
        chasti += ["✍ НУЖНО ОТ ТЕБЯ", *[f"• {s}" for s in nuzhno], ""]
    chasti += ["✓ В ПОРЯДКЕ", *[f"• {s}" for s in horosho], "",
               "Письмо пришло само с нашего сервера. Если что-то непонятно — спроси Claude в проекте."]
    return "\n".join(chasti)


def otpravit(tekst: str) -> None:
    tema = ("⚠ Сайты: есть проблемы" if beda else
            "💳 Сайты: скоро платить" if oplaty else "✓ Сайты: всё в порядке")
    for kuda in NASTROYKI["kuda"]:
        p = EmailMessage()
        p["From"], p["To"], p["Subject"] = f"Контроль сайтов <{OT_KOGO}>", kuda, tema
        p.set_content(tekst)
        subprocess.run(["/usr/sbin/sendmail", "-i", "-f", OT_KOGO, kuda], input=p.as_bytes(), check=True)
        print("письмо:", kuda, "—", tema)


def main() -> None:
    for f in (domeny, beget, selectel, ruchnye, svezhest):
        try:
            f()
        except Exception as e:
            beda.append(f"Проверка «{f.__name__}» сама сломалась: {type(e).__name__}. Разберусь.")
    for nazv, osnova in SAYTY.items():
        sayt(nazv, osnova)
    k, _, _ = zapros(NASH_SAYT)
    (horosho if 0 < k < 400 else beda).append(
        "mokeevasky.ru (твой сайт с Claude): " + ("открывается." if 0 < k < 400 else f"не открывается (код {k})."))
    for host in ("mokeevasky.ru", "glavprig.ru"):
        https(host)
    pochta()

    tekst = otchet()
    OTCHET.write_text(tekst + "\n", encoding="utf-8")
    print(tekst)
    pora = (beda or any(d in SROKI_PISMA or d <= 0 for d, _ in oplaty)
            or SEYCHAS.astimezone(MSK).weekday() == 0 or "--pismo" in sys.argv)
    if pora and "--bez-pisma" not in sys.argv:
        otpravit(tekst)


if __name__ == "__main__":
    main()
