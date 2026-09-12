"""Проверка: время выводится в поясе из настроек, «сегодня» начинается в его полночь.

Где это ломается незаметно:

* перевод в пояс не делается — время идёт по UTC, и в 00:30 по Москве лента
  показывает вчерашнюю дату 21:30;
* время без пояса или секунды от начала эпохи (время изменения файла)
  переводятся не от UTC — сдвиг на всю разницу поясов;
* «сегодня» на дашборде считается с полуночи UTC — в Москве сутки
  «начинаются» в 03:00, во Владивостоке — в 10:00;
* пояс из настроек не проверяется — произвольная строка роняет перевод
  на всех страницах.

Стенд заводит свой диалог, на время прогона ставит пояс Владивостока (UTC+10:
на нём граница суток дальше всего от UTC) и возвращает всё как было.

Запуск:  .venv/bin/python tests/check_timezone.py
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db, timefmt                             # noqa: E402
from app.services import usage                         # noqa: E402

problems: list[str] = []


def check(ok: bool, what: str) -> None:
    print(("  ок   " if ok else "  ПРОВАЛ ") + what)
    if not ok:
        problems.append(what)


def check_formatting() -> None:
    print("Перевод в пояс")
    msk = ZoneInfo("Europe/Moscow")
    # 21:30 UTC — уже следующие сутки по Москве: ловит и сдвиг часов, и даты
    moment = datetime(2026, 9, 12, 21, 30, tzinfo=timezone.utc)
    want = "13.09.2026 00:30"
    check(timefmt.fmt(moment, tz=msk) == want, f"время из базы: {timefmt.fmt(moment, tz=msk)} == {want}")
    check(timefmt.fmt(moment.replace(tzinfo=None), tz=msk) == want, "время без пояса считается UTC")
    check(timefmt.fmt(moment.timestamp(), tz=msk) == want, "секунды от начала эпохи")
    check(timefmt.fmt("2026-09-12T21:30:00+00:00", tz=msk) == want, "строка ISO от обёртки")
    check(timefmt.fmt("2026-09-12T21:30:00Z", tz=msk) == want, "строка ISO с Z")
    check(timefmt.fmt("вчера", tz=msk) == "вчера", "не дата — возвращается как есть")
    check(timefmt.fmt(None, tz=msk) == "", "пусто — пустая строка")
    check(timefmt.fmt(moment, "%d.%m %H:%M", msk) == "13.09 00:30", "свой образец")


def check_zones() -> None:
    print("Пояса")
    check(timefmt.valid_zone("Europe/Moscow"), "Москва годится")
    check(not timefmt.valid_zone("Europe/Paris"), "пояс не из списка отклонён")
    check(not timefmt.valid_zone("Mars/Olympus"), "несуществующий пояс отклонён")
    check(not timefmt.valid_zone("'; DROP TABLE settings; --"), "мусор из формы отклонён")
    check(timefmt.zone_name({"timezone": "Mars/Olympus"}) == "Europe/Moscow",
          "испорченная настройка — Москва, а не падение")
    check(timefmt.zone_name({}) == "Europe/Moscow", "по умолчанию Москва")

    msk = ZoneInfo("Europe/Moscow")
    check(timefmt.offset_text(msk) == "UTC+3", f"смещение Москвы: {timefmt.offset_text(msk)}")
    berlin = ZoneInfo("Europe/Berlin")
    winter = timefmt.offset_text(berlin, datetime(2026, 1, 15, tzinfo=timezone.utc))
    summer = timefmt.offset_text(berlin, datetime(2026, 7, 15, tzinfo=timezone.utc))
    check((winter, summer) == ("UTC+1", "UTC+2"), f"летнее время считается: {winter} / {summer}")

    labels = {z["value"]: z["label"] for z in timefmt.zone_choices()}
    check(labels.get("Europe/Moscow") == "Москва (UTC+3)", f"пункт списка: {labels.get('Europe/Moscow')}")
    check(len(labels) == len(timefmt.ZONES), f"все пояса списка есть в tzdata ({len(labels)})")


def check_today_boundary() -> None:
    print("«Сегодня» на дашборде")
    zone_name = "Asia/Vladivostok"
    tz = ZoneInfo(zone_name)
    before = db.query_one("SELECT value FROM settings WHERE key = 'timezone'")
    conv = db.query_one(
        "INSERT INTO conversations (kind, title) VALUES ('chat', 'стенд пояса') RETURNING id"
    )
    try:
        db.set_setting("timezone", zone_name)
        base = usage.summary()["today"]["input_tokens"]

        midnight = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
        inside, outside = 700_001, 90_000_000
        for when, tokens in ((midnight + timedelta(minutes=30), inside),
                             (midnight - timedelta(minutes=30), outside)):
            db.execute(
                "INSERT INTO messages (conversation_id, role, content, input_tokens, created_at) "
                "VALUES (%s, 'assistant', 'стенд', %s, %s)",
                (conv["id"], tokens, when),
            )

        delta = usage.summary()["today"]["input_tokens"] - base
        check(delta == inside,
              f"полчаса после полуночи — сегодня, полчаса до — вчера (учтено {delta}, ждали {inside})")
    finally:
        db.execute("DELETE FROM conversations WHERE id = %s", (conv["id"],))
        if before is None:
            db.execute("DELETE FROM settings WHERE key = 'timezone'")
        else:
            db.set_setting("timezone", before["value"])

    after = db.query_one("SELECT value FROM settings WHERE key = 'timezone'")
    check((after and after["value"]) == (before and before["value"]), "настройка пояса возвращена")


def main() -> int:
    db.init_pool()
    check_formatting()
    check_zones()
    check_today_boundary()
    print("ИТОГ:", "ПРОВАЛ" if problems else "OK")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
