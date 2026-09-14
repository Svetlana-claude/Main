"""Часовой пояс интерфейса.

Сервер и база живут в UTC, и так должно остаться: время хранится в одном поясе,
а переводится при показе. Поэтому пояс из настроек касается только вывода —
шаблонов, выгрузки диалога в markdown, подписей в браузере — и границы
«сегодня» на дашборде, которая без него наступала бы в 03:00 по Москве.
"""
from datetime import datetime, timedelta, timezone, tzinfo
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


# ── Время сброса лимита в сообщениях Claude Code ─────────────────────────
# Claude Code сообщает об исчерпанном лимите строкой вида
#     You've hit your session limit · resets 9:50am (UTC)
#     You've hit your weekly limit · resets Sep 16, 9am (UTC)
# Время в ней — в поясе процесса, то есть сервера (UTC), и без даты: «9:50am»
# означает ближайшие 9:50 после того, как сообщение пришло. Сама строка
# хранится в базе нетронутой, переводится только при показе.
import re  # noqa: E402

_LIMIT_RE = re.compile(
    r"resets\s+"
    r"(?:(?P<mon>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(?P<day>\d{1,2}),?\s+(?:at\s+)?)?"
    r"(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<ampm>am|pm)"
    r"\s*\((?P<zone>[^)]+)\)",
    re.IGNORECASE,
)
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_HEADS = [
    (re.compile(r"you'?ve hit your session limit", re.I), "Исчерпан лимит сессии"),
    (re.compile(r"you'?ve hit your weekly limit", re.I), "Исчерпан недельный лимит"),
    (re.compile(r"you'?ve hit your (?:usage )?limit", re.I), "Исчерпан лимит"),
]


def zone_label(tz: tzinfo) -> str:
    """Подпись пояса: русское имя из списка или смещение для прочих."""
    key = getattr(tz, "key", None)
    for name, title in ZONES:
        if name == key:
            return title
    return offset_text(tz)


def limit_reset(text: str, said_at, tz: tzinfo) -> datetime | None:
    """Момент сброса лимита из строки Claude Code, или None, если строка не та.

    `said_at` — когда сообщение пришло: без него «9:50am» не превратить в
    момент. Время в строке трактуется в поясе, указанном в скобках; пояс,
    которого не знает zoneinfo, — повод не угадывать, а вернуть None.
    """
    m = _LIMIT_RE.search(text or "")
    if not m:
        return None
    source = _zone_or_none(m.group("zone").strip())
    base = to_local(said_at, source) if source else None
    if base is None:
        return None
    raw_hour = int(m.group("hour"))
    minute = int(m.group("minute") or 0)
    # На циферблате am/pm часы — от 1 до 12. Проверка до пересчёта: `% 12`
    # молча превратил бы «25:00am» в 01:00 и выдал выдумку за перевод.
    if not 1 <= raw_hour <= 12 or minute > 59:
        return None
    hour = raw_hour % 12 + (12 if m.group("ampm").lower() == "pm" else 0)
    try:
        if m.group("mon"):
            month = _MONTHS[m.group("mon")[:3].lower()]
            moment = base.replace(month=month, day=int(m.group("day")), hour=hour,
                                  minute=minute, second=0, microsecond=0)
            # Дата без года: «Jan 2», пришедшее в декабре, — это уже следующий год.
            if moment < base - timedelta(days=1):
                moment = moment.replace(year=moment.year + 1)
        else:
            moment = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if moment <= base:
                moment += timedelta(days=1)
    except ValueError:
        return None
    return moment.astimezone(tz)


def localize_limit(text: str, said_at, tz: tzinfo | None = None) -> str:
    """Строка об исчерпанном лимите — по-русски и со временем в поясе из настроек.

    Всё, что не узнано, возвращается как есть: исходное сообщение лучше
    переведённого наугад. Дата добавляется, только если сброс приходится не
    на тот же местный день, что само сообщение, — иначе «в 03:10» читалось бы
    как «сегодня», а это уже завтра.
    """
    tz = tz or zone()
    moment = limit_reset(text, said_at, tz)
    if moment is None:
        return text
    said_local = to_local(said_at, tz)
    when = moment.strftime("%H:%M")
    if said_local is None or moment.date() != said_local.date():
        when = moment.strftime("%d.%m в %H:%M")
    else:
        when = "в " + when
    head = None
    for pattern, title in _HEADS:
        if pattern.search(text):
            head = title
            break
    tail = f"обнулится {when} ({zone_label(tz)})"
    if head:
        return f"{head} · {tail}"
    return _LIMIT_RE.sub(tail, text, count=1)
