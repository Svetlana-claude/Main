"""Подставная обёртка перезапуска: записывает команду, ничего не перезапускает.
Есть файл <лог>.fail — отвечает ошибкой."""
import os
import sys

log = os.environ["FAKE_POWER_LOG"]
if os.path.exists(log + ".fail"):
    print("нет прав")
    sys.exit(1)
with open(log, "a", encoding="utf-8") as fh:
    fh.write(" ".join(sys.argv[1:]) + "\n")
