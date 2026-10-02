"""Ответ движка → сообщения Телеграма.

Две задачи, и обе не такие простые, как кажутся.

**Разметка.** Движок отвечает Markdown, Телеграм понимает свой маленький набор
тегов (`b`, `i`, `s`, `code`, `pre`, `a`, `blockquote`) и падает с ошибкой на
незакрытом теге — сообщение тогда не уходит вовсе. Поэтому порядок такой: сперва
экранируются `&` и `<`, потом вырезаются куски кода и таблицы (внутри них
Markdown не разбирается), и только потом по остатку идут жирный, курсив и ссылки.

**Нарезка.** Предел сообщения — 4096 знаков, а ответы бывают на двадцать тысяч.
Резать готовый HTML нельзя: разрыв попадёт внутрь тега. Поэтому режется исходный
Markdown, по границам строк, с закрытием и повторным открытием ограды кода, —
и каждый кусок переводится в HTML отдельно, то есть заведомо целым.

Таблицы Markdown Телеграм не умеет вовсе; они уходят в `pre`, где сохраняется
выравнивание пробелами, — иначе шапка и строки разъезжаются и таблица
становится нечитаемой.
"""
import html
import re
from datetime import timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

FENCE_OPEN = re.compile(r"^\s*```(\S*)")
TABLE_LINE = re.compile(r"^\s*\|.*\|\s*$")

_FENCE = re.compile(r"```([^\n`]*)\n(.*?)```", re.S)
_FENCE_HVOST = re.compile(r"```([^\n`]*)\n(.*)\Z", re.S)     # ограда не закрыта
_CODE = re.compile(r"`([^`\n]+)`")
_BOLD = re.compile(r"\*\*(.+?)\*\*", re.S)
_BOLD_ = re.compile(r"__(.+?)__", re.S)
_ITAL = re.compile(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])")
_ITAL_ = re.compile(r"(?<![\w_])_([^_\n]+)_(?![\w_])")
_STRIKE = re.compile(r"~~(.+?)~~", re.S)
_LINK = re.compile(r"\[([^\]\n]*)\]\(([^)\s]+)\)")
_HEAD = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$", re.M)
_LIST = re.compile(r"^(\s*)[-*+][ \t]+", re.M)
_HR = re.compile(r"^\s*([-*_])(?:\s*\1){2,}\s*$", re.M)

# Метка подставленного куска. \x00 в тексте от движка не встречается, а если бы
# встретился — он уйдёт в экранирование раньше, чем появятся метки.
_METKA = "\x00{}\x00"
_METKA_RE = re.compile(r"\x00(\d+)\x00")


def narezat(text: str, limit: int) -> list[str]:
    """Режет Markdown на куски не длиннее `limit`, не разрывая ограду кода."""
    text = (text or "").strip()
    if not text:
        return []

    kuski: list[str] = []
    tekushchiy: list[str] = []
    dlina = 0
    ograda: str | None = None       # язык открытой ограды, None — ограды нет

    def sbrosit(zakryt: bool) -> None:
        nonlocal tekushchiy, dlina
        if not tekushchiy:
            return
        kusok = "\n".join(tekushchiy)
        if zakryt:
            kusok += "\n```"        # ограда закрывается в своём куске
        kuski.append(kusok)
        tekushchiy = []
        dlina = 0

    for stroka in text.split("\n"):
        # Строка длиннее предела целиком — рубим по пределу, иначе она не уйдёт никогда
        chasti = [stroka] if len(stroka) <= limit else [
            stroka[i:i + limit] for i in range(0, len(stroka), limit)
        ]
        for chast in chasti:
            if dlina + len(chast) + 1 > limit and tekushchiy:
                sbrosit(zakryt=ograda is not None)
                if ograda is not None:
                    tekushchiy.append(f"```{ograda}")
                    dlina = len(ograda) + 4
            tekushchiy.append(chast)
            dlina += len(chast) + 1

            otkrytie = FENCE_OPEN.match(chast)
            if otkrytie:
                ograda = None if ograda is not None else (otkrytie.group(1) or "")

    sbrosit(zakryt=False)
    return [k for k in kuski if k.strip()]


def v_html(md: str) -> str:
    """Markdown → разметка Телеграма. Возвращает заведомо целый HTML."""
    text = html.escape(md or "", quote=False)
    zapas: list[str] = []

    def otlozhit(gotovyy_html: str) -> str:
        zapas.append(gotovyy_html)
        return _METKA.format(len(zapas) - 1)

    # 1. Куски кода. Сперва закрытые ограды, потом незакрытая в хвосте: движок
    #    обрывается на середине листинга регулярно, и без этого хвост уехал бы
    #    в обычный текст вместе со всеми звёздочками.
    def ograda(m: re.Match) -> str:
        yazyk = (m.group(1) or "").strip()
        klass = f' class="language-{yazyk}"' if yazyk.isalnum() else ""
        return otlozhit(f"<pre><code{klass}>{m.group(2)}</code></pre>")

    text = _FENCE.sub(ograda, text)
    text = _FENCE_HVOST.sub(ograda, text)

    # 2. Таблицы: подряд идущие строки с вертикальными чертами — одним `pre`
    text = _tablicy(text, otlozhit)

    # 3. Код в строке
    text = _CODE.sub(lambda m: otlozhit(f"<code>{m.group(1)}</code>"), text)

    # 4. Блочное: заголовки жирным (своих у Телеграма нет), список точками,
    #    разделительная черта — длинным тире
    text = _HEAD.sub(lambda m: f"<b>{m.group(2)}</b>", text)
    text = _HR.sub("—" * 10, text)
    text = _LIST.sub(lambda m: f"{m.group(1)}• ", text)

    # 5. Строчное
    text = _LINK.sub(
        lambda m: f'<a href="{m.group(2).replace(chr(34), "%22")}">{m.group(1) or m.group(2)}</a>',
        text,
    )
    text = _BOLD.sub(lambda m: f"<b>{m.group(1)}</b>", text)
    text = _BOLD_.sub(lambda m: f"<b>{m.group(1)}</b>", text)
    text = _STRIKE.sub(lambda m: f"<s>{m.group(1)}</s>", text)
    text = _ITAL.sub(lambda m: f"<i>{m.group(1)}</i>", text)
    text = _ITAL_.sub(lambda m: f"<i>{m.group(1)}</i>", text)

    # 6. Возвращаем отложенное на место
    text = _METKA_RE.sub(lambda m: zapas[int(m.group(1))], text)

    # Пустых строк подряд больше двух не нужно: в Телеграме они съедают экран
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _tablicy(text: str, otlozhit) -> str:
    """Подряд идущие строки таблицы Markdown — в `pre` с выравниванием пробелами."""
    stroki = text.split("\n")
    out: list[str] = []
    bufer: list[str] = []

    def vylozhit() -> None:
        if not bufer:
            return
        # Строка-разделитель шапки (|---|---|) в обычном тексте бессмысленна
        telo = [s for s in bufer if not re.fullmatch(r"\s*\|[\s|:-]+\|\s*", s)]
        if len(telo) >= 1:
            out.append(otlozhit("<pre>" + "\n".join(_vyrovnyat(telo)) + "</pre>"))
        bufer.clear()

    for stroka in stroki:
        if TABLE_LINE.match(stroka):
            bufer.append(stroka)
        else:
            vylozhit()
            out.append(stroka)
    vylozhit()
    return "\n".join(out)


def _vyrovnyat(stroki: list[str]) -> list[str]:
    """Колонки таблицы по одной ширине: в `pre` шрифт равноширинный, сойдётся."""
    tablica = [[c.strip() for c in s.strip().strip("|").split("|")] for s in stroki]
    kolonok = max(len(r) for r in tablica)
    shirina = [0] * kolonok
    for row in tablica:
        for i, cell in enumerate(row):
            shirina[i] = max(shirina[i], len(cell))
    # Общая ширина в `pre` ограничена шириной экрана телефона; шире 60 знаков
    # Телеграм всё равно даст горизонтальную прокрутку, но ужимать нечем
    return [
        " │ ".join(cell.ljust(shirina[i]) for i, cell in enumerate(row)).rstrip()
        for row in tablica
    ]


def prostoy(md: str, limit: int) -> str:
    """Хвост ответа без разметки — для живого «Хода работы».

    Правится оно часто, и разбирать недописанный Markdown на каждой правке незачем:
    на полуслове любая разметка окажется незакрытой, и сообщение не уйдёт.
    """
    text = (md or "").replace("\x00", "")
    if len(text) > limit:
        text = "…" + text[-limit:]
    return text


def soobshchit_oshibku(text: str) -> str:
    """Ошибка движка словами. Хвост длинного вывода — без разметки."""
    text = (text or "неизвестная ошибка").strip()
    if len(text) > 1500:
        text = text[:1500] + "…"
    return "⚠️ " + text


def svodka(itog: dict) -> str:
    """Служебная строка под ответом: чем отвечено и во что обошлось."""
    chasti = []
    if itog.get("model"):
        chasti.append(_model(str(itog["model"])))
    tokenov = (itog.get("input_tokens") or 0) + (itog.get("output_tokens") or 0)
    if tokenov:
        chasti.append(f"{tokenov:,}".replace(",", " ") + " ток.")
    if itog.get("context_tokens"):
        chasti.append("контекст " + _kratko(itog["context_tokens"]))
    if itog.get("duration_ms"):
        chasti.append(_vremya(itog["duration_ms"]))
    if itog.get("tools_used"):
        poryadok = list(dict.fromkeys(itog["tools_used"]))[:4]
        chasti.append(", ".join(poryadok))
    return " · ".join(chasti)


def kogda(value, poyas: str = "Europe/Moscow", shablon: str = "%d.%m %H:%M") -> str:
    """Время для человека.

    В базе всё в UTC — так заведено в `webui`, и расходиться с ним нельзя.
    Показывается в поясе из общих настроек: без перевода задача, поставленная
    вечером, выглядела бы поставленной ночью.
    """
    if value is None:
        return "—"
    try:
        zona = ZoneInfo(poyas)
    except (ZoneInfoNotFoundError, ValueError):
        zona = timezone.utc
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(zona).strftime(shablon)


def _model(name: str) -> str:
    """Короткое имя модели: из `claude-opus-5` нужен `opus`, а не `claude`."""
    chasti = name.split("-")
    if len(chasti) > 1 and chasti[0] == "claude":
        return chasti[1]
    return chasti[0] or name


def _kratko(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f} млн".replace(".", ",")
    if n >= 1_000:
        return f"{n // 1000} тыс."
    return str(n)


def _vremya(ms: int) -> str:
    sek = ms / 1000
    if sek < 60:
        return f"{sek:.0f} с"
    return f"{int(sek // 60)} мин {int(sek % 60)} с"
