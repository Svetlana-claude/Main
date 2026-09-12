"""Часовой пояс интерфейса.

Сервер и база живут в UTC, и так должно остаться: время хранится в одном поясе,
а переводится при показе. Поэтому пояс из настроек касается только вывода —
шаблонов, выгрузки диалога в markdown, подписей в браузере — и границы
«сегодня» на дашборде, которая без него наступала бы в 03:00 по Москве.
"""
from datetime import datetime, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import db

DEFAULT_TZ = "Europe/Moscow"

DEFAULT_PATTERN = "%d.%m.%Y %H:%M"

# Пояса России целиком, соседи и несколько мировых. Полный список IANA —
# четыре сотни строк, среди которых нужную не найти.
ZONES: list[tuple[str, str]] = [
    ("Europe/Kaliningrad", "Калининград"),
    ("Europe/Moscow", "Москва"),
    ("Europe/Samara", "Самара"),
    ("Asia/Yekaterinburg", "Екатеринбург"),
    ("Asia/Omsk", "Омск"),
    ("Asia/Novosibirsk", "Новосибирск"),
    ("Asia/Krasnoyarsk", "Красноярск"),
    ("Asia/Irkutsk", "Иркутск"),
    ("Asia/Yakutsk", "Якутск"),
    ("Asia/Vladivostok", "Владивосток"),
    ("Asia/Magadan", "Магадан"),
    ("Asia/Kamchatka", "Камчатка"),
    ("Europe/Minsk", "Минск"),
    ("Asia/Almaty", "Алматы"),
    ("Asia/Tashkent", "Ташкент"),
    ("Asia/Tbilisi", "Тбилиси"),
    ("Asia/Yerevan", "Ереван"),
    ("Asia/Baku", "Баку"),
    ("Europe/Istanbul", "Стамбул"),
    ("Europe/Berlin", "Берлин"),
    ("Europe/London", "Лондон"),
    ("America/New_York", "Нью-Йорк"),
    ("UTC", "UTC"),
]


def _zone_or_none(name: str) -> ZoneInfo | None:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return None


def offset_text(tz: tzinfo, now: datetime | None = None) -> str:
    """Смещение вида «UTC+3» или «UTC+5:30» на текущий момент.

    Считается, а не вписано в список: у Берлина, Лондона и Нью-Йорка есть
    летнее время, и вписанное смещение полгода было бы неверным.
    """
    moment = (now or datetime.now(timezone.utc)).astimezone(tz)
    delta = moment.utcoffset()
    minutes = int(delta.total_seconds() // 60) if delta else 0
    if minutes == 0:
        return "UTC"
    sign = "+" if minutes > 0 else "−"
    hours, rest = divmod(abs(minutes), 60)
    return f"UTC{sign}{hours}" + (f":{rest:02d}" if rest else "")


def zone_choices(now: datetime | None = None) -> list[dict]:
    """Пункты выпадающего списка. Пояса, которых нет в базе tzdata, пропускаются."""
    out = []
    for name, city in ZONES:
        tz = _zone_or_none(name)
        if tz is None:
            continue
        label = city if name == "UTC" else f"{city} ({offset_text(tz, now)})"
        out.append({"value": name, "label": label})
    return out


def valid_zone(name: str) -> bool:
    """Годится ли имя для сохранения: только из списка и только существующее."""
    return any(name == n for n, _ in ZONES) and _zone_or_none(name) is not None


def zone_name(settings: dict | None = None) -> str:
    """Имя пояса из настроек. Испорченное значение не роняет страницы — берётся Москва."""
    values = settings if settings is not None else db.get_settings()
    name = values.get("timezone") or DEFAULT_TZ
    return name if valid_zone(name) else DEFAULT_TZ


def zone(settings: dict | None = None) -> ZoneInfo:
    return ZoneInfo(zone_name(settings))


def to_local(value, tz: tzinfo) -> datetime | None:
    """Момент времени в выбранном поясе.

    Принимает то, что встречается в приложении: datetime из базы (с поясом),
    datetime без пояса, секунды от начала эпохи (время изменения файла) и
    строку ISO (так отдаёт даты обёртка аудита). Время без пояса считается
    UTC — сервер живёт в UTC, и другого смысла у такого времени здесь нет.
    """
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        moment = datetime.fromtimestamp(value, timezone.utc)
    elif isinstance(value, datetime):
        moment = value
    elif isinstance(value, str):
        try:
            moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(tz)


def fmt(value, pattern: str = DEFAULT_PATTERN, tz: tzinfo | None = None) -> str:
    """Время строкой в выбранном поясе.

    Строка, которая не разобралась как дата, возвращается как есть: подпись
    от обёртки лучше показать нетронутой, чем потерять.
    """
    moment = to_local(value, tz or zone())
    if moment is None:
        return value if isinstance(value, str) else ""
    return moment.strftime(pattern)
