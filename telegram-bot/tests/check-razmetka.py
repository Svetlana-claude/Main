#!/usr/bin/env python3
"""Проверка нарезки и разметки ответа.

Эта часть бота проверяется без сервера и без Телеграма: на входе текст, на выходе
текст, и именно здесь живут отказы, которые в бою выглядят как «бот промолчал».
Телеграм разбирает теги сам и на непонятном отказывается отправлять сообщение
целиком — то есть длинный ответ с незакрытым `<b>` пропадает весь.

Правило 12 CLAUDE.md: проверка сперва прогоняется на дефекте, который обязана
ловить. Для этого есть ключи, подменяющие проверяемое на прежнее, наивное
поведение, — на них проверка обязана краснеть:

    python3 tests/check-razmetka.py                 # на готовом коде — зелено
    python3 tests/check-razmetka.py --slomat razmetku   # без экранирования
    python3 tests/check-razmetka.py --slomat narezku    # нарезка по пределу
    python3 tests/check-razmetka.py --slomat tablicy    # таблицы как обычный текст

Запускается любым python 3.11+, зависимостей нет.
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot import razmetka                                    # noqa: E402

PARNYE = ("b", "i", "s", "u", "code", "pre", "a", "blockquote")
TEG = re.compile(r"<(/?)([a-z]+)(?:\s[^>]*)?>")

PRIMER = """# Сводка по проекту

Сделано **три** вещи, и одна из них важнее остальных:

1. Поправлен `service-hero.blade.php` — шапка услуг.
2. Контраст померен, а не оценён на глаз: 4,9 : 1 при норме 4,5 : 1.
3. Патчи пересобраны.

| Страница | Было | Стало |
|---|---|---|
| Главная | 7,4 : 1 | 7,4 : 1 |
| Услуги | 2,9 : 1 | 4,9 : 1 |

Код правки:

```php
@section('sharedOff', '1')
$a = 1 < 2 && 3 > 2;
```

Осталось: <не трогать> файл `.env` — там ключи. Подробнее — [записка](https://example.org/a?b=1&c=2).
"""


class Sboy(Exception):
    pass


proverok = 0
provalov = 0


def proverit(uslovie: bool, chto: str) -> None:
    global proverok, provalov
    proverok += 1
    if uslovie:
        print(f"  ok   {chto}")
    else:
        provalov += 1
        print(f"  ПРОВАЛ {chto}")


def tegi_sbalansirovany(html: str) -> bool:
    """Все парные теги закрыты и закрыты в правильном порядке."""
    stek: list[str] = []
    for zakryvayushchiy, imya in TEG.findall(html):
        if imya not in PARNYE:
            continue
        if zakryvayushchiy:
            if not stek or stek.pop() != imya:
                return False
        else:
            stek.append(imya)
    return not stek


# ---------------------------------------------------------------------------


def proverki_narezki(limit: int = 300) -> None:
    print("Нарезка:")
    dlinnyy = PRIMER * 6
    kuski = razmetka.narezat(dlinnyy, limit)

    proverit(bool(kuski), "длинный текст нарезан хотя бы на один кусок")
    proverit(all(len(k) <= limit + 4 for k in kuski),
             f"ни один кусок не длиннее предела ({max(map(len, kuski))} ≤ {limit + 4})")
    proverit(all(k.count("```") % 2 == 0 for k in kuski),
             "ограда кода в каждом куске закрыта")

    # Ничего не потеряно: содержательные строки сохранились все
    svoi = [s for s in dlinnyy.split("\n") if s.strip() and s.strip() != "```"]
    sobrano = "\n".join(kuski)
    proverit(all(s.strip() in sobrano for s in svoi[:40]),
             "строки исходного текста не потерялись")

    # Строка длиннее предела целиком не должна вешать нарезку
    odna = "я" * (limit * 3)
    kuski_odnoy = razmetka.narezat(odna, limit)
    proverit(kuski_odnoy and all(len(k) <= limit + 4 for k in kuski_odnoy),
             "строка длиннее предела разрублена, а не отброшена")
    proverit(razmetka.narezat("   ", limit) == [], "пустой текст даёт пустой список")


def proverki_razmetki() -> None:
    print("Разметка:")
    html = razmetka.v_html(PRIMER)

    proverit(tegi_sbalansirovany(html), "теги закрыты и вложены верно")
    proverit("<script" not in razmetka.v_html("смотри <script>alert(1)</script>"),
             "чужой тег обезврежен, а не вставлен как тег")
    proverit("&lt;не трогать&gt;" in html, "угловые скобки в тексте экранированы")
    proverit("<b>Сводка по проекту</b>" in html, "заголовок стал жирным")
    proverit("<b>три</b>" in html, "**жирный** переведён")
    proverit("<code>service-hero.blade.php</code>" in html, "`код` в строке переведён")
    proverit("<pre>" in html, "таблица ушла в pre")
    proverit("│" in html, "колонки таблицы выровнены")
    proverit('<a href="https://example.org/a?b=1&amp;c=2">записка</a>' in html,
             "ссылка собрана, амперсанд в адресе экранирован")

    # Внутри кода разметка не разбирается: `$a = 1 < 2 && 3 > 2` не должен
    # превратиться в теги, а звёздочки в листинге — в жирный
    proverit("$a = 1 &lt; 2 &amp;&amp; 3 &gt; 2;" in html,
             "содержимое листинга экранировано и не разобрано как разметка")

    # Незакрытая ограда — обычное дело, когда ответ обрывается на середине
    oborvannyy = "Вот начало:\n\n```python\nprint(1)\nprint(2)"
    html_oborvannogo = razmetka.v_html(oborvannyy)
    proverit("<pre>" in html_oborvannogo and tegi_sbalansirovany(html_oborvannogo),
             "незакрытая ограда кода всё равно даёт целый pre")

    # Главное свойство: каждый кусок длинного ответа уходит целым
    kuski = razmetka.narezat(PRIMER * 6, 900)
    proverit(all(tegi_sbalansirovany(razmetka.v_html(k)) for k in kuski),
             "у каждого куска длинного ответа теги целы")


def proverki_svodki() -> None:
    print("Служебная строка:")
    stroka = razmetka.svodka({
        "model": "claude-opus-5", "input_tokens": 1200, "output_tokens": 800,
        "context_tokens": 240_000, "duration_ms": 95_000,
        "tools_used": ["Read", "Edit", "Read"],
    })
    proverit("opus" in stroka, "модель названа коротко, без приставки claude-")
    proverit("2 000 ток." in stroka, "токены сложены и разделены пробелом")
    proverit("240 тыс." in stroka, "контекст показан кратко")
    proverit("1 мин 35 с" in stroka, "время показано минутами")
    proverit(stroka.count("Read") == 1, "повторный инструмент не дублируется")
    proverit(razmetka.svodka({}) == "", "пустой итог даёт пустую строку")


# ---------------------------------------------------------------------------
# Подмена проверяемого на прежнее, наивное поведение — правило 12


def slomat(chto: str) -> None:
    if chto in ("razmetku", "разметку"):
        # Было: текст уходил как есть, без экранирования
        razmetka.v_html = lambda md: (md or "").strip()
    elif chto in ("narezku", "нарезку"):
        # Было: нарезка по пределу, без оглядки на ограду кода
        razmetka.narezat = lambda text, limit: [
            text[i:i + limit] for i in range(0, len(text or ""), limit)
        ]
    elif chto in ("tablicy", "таблицы"):
        razmetka._tablicy = lambda text, otlozhit: text
    else:
        raise SystemExit(f"нечего ломать: {chto}")
    print(f"⚠️ проверяемое подменено прежним поведением: {chto}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Проверка нарезки и разметки")
    parser.add_argument("--slomat", help="подменить проверяемое прежним поведением")
    args = parser.parse_args()

    if args.slomat:
        slomat(args.slomat)

    proverki_narezki()
    proverki_razmetki()
    proverki_svodki()

    print(f"\nПроверок {proverok}, провалов {provalov}")
    if args.slomat:
        if provalov:
            print("Так и должно быть: на прежнем поведении проверка краснеет.")
            return 0
        print("ПЛОХО: на сломанном коде проверка прошла — она ничего не доказывает.")
        return 1
    return 1 if provalov else 0


if __name__ == "__main__":
    sys.exit(main())
