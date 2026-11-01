#!/usr/bin/env python3
"""Подставляет пароли и ключи из этой папки вместо меток ⟦К-0001⟧.
Копия с настоящими значениями ложится рядом, в папку «со-ключами»."""
import os
import re
from pathlib import Path

KEYS = Path(__file__).resolve().parent
ROOT = KEYS.parent
OUT = ROOT / "со-ключами"

values = {}
for path in KEYS.glob("*.md"):
    for tag, val in re.findall(r"^## (⟦К-\d{4}⟧)\n.*?^~~~~\n(.*?)\n~~~~$", path.read_text(encoding="utf-8"), re.S | re.M):
        values[tag] = val

OUT.mkdir(exist_ok=True)
os.chmod(OUT, 0o700)
done = 0
for src in [*ROOT.glob("*.md"), *(ROOT / "проекты").glob("*.md")]:
    text = re.sub(r"⟦К-\d{4}⟧", lambda m: values.get(m.group(0), m.group(0)), src.read_text(encoding="utf-8"))
    dst = OUT / src.relative_to(ROOT)
    dst.parent.mkdir(exist_ok=True)
    dst.write_text(text, encoding="utf-8")
    os.chmod(dst, 0o600)
    done += 1
print(f"Готово: {done} файлов, {len(values)} ключей, папка {OUT}")
