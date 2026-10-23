#!/usr/bin/env python3
"""Текстура ткани для просмотрщика — по снимку спортивной системы заказчика.

С крупного снимка (img-3794, 22.10.2026) вырезаются два куска: чёрная кордура ранца
и бежевая канва вставки. Из каждого остаётся только рисунок переплетения — яркость
без крупных перепадов света, средняя 0,5 — и он сшивается в бесшовную плитку.
Кордура уходит в красный канал, канва — в зелёный; синий — их среднее для лент.

    /usr/bin/python3 tools/tkan.py <снимок.jpg> [--out prosmotr/src/tkan.webp]

Снимок — в формате, который читает Pillow (heic заранее перевести в jpg).
"""
import argparse
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

RAZMER = 256
# куски в координатах полного кадра 4284 × 5712: (лево, верх, сторона)
KUSKI = {
    "kordura": (2860, 3150, 340),
    "kanva": (1904, 2856, 476),
}


def risunok(kadr, lev, verh, st):
    """Кусок → рисунок переплетения: высокие частоты, средняя 0,5, плитка без шва."""
    k = kadr.crop((lev, verh, lev + st, verh + st)).convert("L").resize((RAZMER, RAZMER), Image.LANCZOS)
    a = np.asarray(k, float)
    fon = np.asarray(k.filter(ImageFilter.GaussianBlur(14)), float)
    v = a - fon
    v /= max(1e-6, np.percentile(np.abs(v), 98))
    v = np.clip(v, -1, 1)
    # бесшовность: смесь с собой же, сдвинутой на половину, весом по расстоянию до края
    t = np.linspace(0, 1, RAZMER)
    w1 = np.minimum(t, 1 - t) * 2
    w = np.minimum(w1[:, None], w1[None, :])
    w = np.clip(w * 2.5, 0, 1)
    sdvig = np.roll(np.roll(v, RAZMER // 2, 0), RAZMER // 2, 1)
    v = v * w + sdvig * (1 - w)
    v /= max(1e-6, np.abs(v).max())
    return np.clip(0.5 + 0.5 * v, 0, 1)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("snimok")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent.parent / "prosmotr/src/tkan.webp"))
    a = ap.parse_args()
    kadr = Image.open(a.snimok)
    r = risunok(kadr, *KUSKI["kordura"])
    g = risunok(kadr, *KUSKI["kanva"])
    b = (r + g) / 2
    im = Image.fromarray((np.stack([r, g, b], -1) * 255).round().astype(np.uint8))
    im.save(a.out, quality=82, method=6)
    print(a.out, Path(a.out).stat().st_size, "Б")


if __name__ == "__main__":
    main()
