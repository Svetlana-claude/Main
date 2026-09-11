"""Проверка: окна тарифного плана считаются скользящими, а не по календарю.

Смысл проверки. Окно плана начинается с первого запроса и живёт пять часов
(или неделю), а не обнуляется в круглый час и не начинается «пять часов назад».
Ошибиться тут легко и незаметно: страница всё равно покажет какое-то число,
и понять, что оно не то, будет нечем. Поэтому проверяются именно те два числа,
которые из этого следуют, — когда окно обнулится и сколько до этого ждать.

База не нужна: запросы подменяются, проверяется арифметика окна.

Запуск:  .venv/bin/python tests/check_usage_windows.py
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services import usage  # noqa: E402

FAILED = []


def check(name: str, got, expected):
    ok = got == expected
    print(f"  {'ok  ' if ok else 'ПЛОХО'} {name}: {got}" + ("" if ok else f" (ждали {expected})"))
    if not ok:
        FAILED.append(name)


def data(started, tokens_in, tokens_out, requests=1):
    """Готовые данные окна — то, что отдаёт источник (стенограммы или база)."""
    return {
        "started": started,
        "input_tokens": tokens_in,
        "output_tokens": tokens_out,
        "cache_read": 0,
        "cache_write": 0,
        "requests": requests,
    }


def main():
    now = datetime.now(timezone.utc)
    # Запас в полминуты: остаток усекается вниз, и ровно «4 часа назад» дало бы
    # «59 мин» — из-за микросекунд между этой строкой и вызовом. Это свойство
    # стенда, а не ошибка счёта, поэтому лечится здесь, а не в продукте.
    edge = timedelta(seconds=30)

    print("Окно, начатое 4 часа назад: обнуление через час, а не через пять")
    w = usage._window(data(now - timedelta(hours=4) + edge, 30_000, 10_000, 5), usage.WINDOW_5H, 100_000)
    check("токенов в окне", w["tokens"], 40_000)
    check("осталось до предела", w["left"], 60_000)
    check("доля предела, %", w["share"], 40.0)
    check("ждать до обнуления", w["resets_in"], "1 ч 0 мин")
    check("окно не исчерпано", w["over"], False)

    print("\nПредел не задан: мера остатка не выдумывается")
    w = usage._window(data(now - timedelta(hours=1), 30_000, 10_000, 5), usage.WINDOW_5H, 0)
    check("доля", w["share"], 0.0)
    check("остаток", w["left"], 0)
    check("не помечено как исчерпанное", w["over"], False)

    print("\nЗапросов не было: окна нет, и оно не притворяется начатым")
    w = usage._window(data(None, 0, 0, 0), usage.WINDOW_5H, 100_000)
    check("признак простоя", w["idle"], True)
    check("время обнуления", w["resets_at"], None)

    print("\nПредел набран: показывается исчерпание, а остаток не уходит в минус")
    w = usage._window(data(now - timedelta(hours=1), 90_000, 30_000, 9), usage.WINDOW_5H, 100_000)
    check("исчерпано", w["over"], True)
    check("остаток не отрицательный", w["left"], 0)
    check("доля больше 100", w["share"] > 100, True)

    print("\nНедельное окно: те же правила, длина семь суток")
    w = usage._window(data(now - timedelta(days=6) + edge, 500_000, 100_000, 40), usage.WINDOW_WEEK, 2_000_000)
    check("ждать до обнуления", w["resets_in"], "1 дн 0 ч")

    print("\nПредел из настроек: мусор и пусто означают «не задан»")
    check("число", usage._int_setting({"limit_5h_tokens": "120000"}, "limit_5h_tokens"), 120_000)
    check("пусто", usage._int_setting({"limit_5h_tokens": ""}, "limit_5h_tokens"), 0)
    check("мусор", usage._int_setting({"limit_5h_tokens": "много"}, "limit_5h_tokens"), 0)
    check("отрицательное", usage._int_setting({"limit_5h_tokens": "-5"}, "limit_5h_tokens"), 0)

    print()
    if FAILED:
        print(f"НЕ ПРОШЛО: {len(FAILED)} — {', '.join(FAILED)}")
        return 1
    print("Все проверки прошли")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
