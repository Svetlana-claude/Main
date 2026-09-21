"""Генератор фоновых текстур макета: вид сверху (поля, Ока, аэродром),
топографические горизонтали и QR-код.

Запуск (нужен segno): python gen.py  — перезаписывает файлы в img/.
Случайность с фиксированным зерном: картинки при перезапуске не меняются.
"""
import math
import os
import random

HERE = os.path.dirname(os.path.abspath(__file__))
IMG = os.path.join(HERE, "img")


def SmoothClosed(points):
    """Замкнутая кривая Catmull-Rom → кубические Безье."""
    n = len(points)
    d = f"M{points[0][0]:.1f} {points[0][1]:.1f}"
    for i in range(n):
        p0, p1, p2, p3 = points[i - 1], points[i], points[(i + 1) % n], points[(i + 2) % n]
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
        d += f"C{c1[0]:.1f} {c1[1]:.1f} {c2[0]:.1f} {c2[1]:.1f} {p2[0]:.1f} {p2[1]:.1f}"
    return d + "Z"


def SmoothOpen(points):
    d = f"M{points[0][0]:.1f} {points[0][1]:.1f}"
    for i in range(len(points) - 1):
        p0 = points[max(i - 1, 0)]
        p1, p2 = points[i], points[i + 1]
        p3 = points[min(i + 2, len(points) - 1)]
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
        d += f"C{c1[0]:.1f} {c1[1]:.1f} {c2[0]:.1f} {c2[1]:.1f} {p2[0]:.1f} {p2[1]:.1f}"
    return d


def Contours(stroke, opacity, fileName):
    """Горизонтали: несколько «вершин» с концентрическими волнистыми кольцами."""
    rnd = random.Random(4000)
    w, h = 600, 400
    paths = []
    for cx, cy, rings in ((140, 150, 9), (470, 290, 11), (520, 40, 6)):
        ph = [rnd.uniform(0, 6.28) for _ in range(3)]
        for k in range(rings):
            r = 14 + k * 17
            pts = []
            for j in range(28):
                t = j / 28 * 2 * math.pi
                rr = r * (1 + 0.16 * math.sin(3 * t + ph[0] + k * 0.15)
                          + 0.08 * math.sin(5 * t + ph[1])
                          + 0.05 * math.sin(2 * t + ph[2] - k * 0.1))
                pts.append((cx + rr * math.cos(t) * 1.25, cy + rr * math.sin(t)))
            sw = 1.4 if k % 5 == 4 else 0.7
            paths.append(f'<path d="{SmoothClosed(pts)}" stroke-width="{sw}"/>')
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
           f'preserveAspectRatio="xMidYMid slice"><g fill="none" stroke="{stroke}" '
           f'stroke-opacity="{opacity}">' + "".join(paths) + "</g></svg>")
    open(os.path.join(IMG, fileName), "w").write(svg)


def Landscape(fills, field_stroke, river, river_core, forest, fileName):
    """Вид с высоты: лоскуты полей, лесные пятна, излучина реки, полоса аэродрома."""
    rnd = random.Random(1956)
    w, h = 600, 300
    cols, rows = 11, 6
    cw, rh = w / cols, h / rows
    grid = [[(c * cw + (rnd.uniform(-9, 9) if 0 < c < cols else 0),
              r * rh + (rnd.uniform(-7, 7) if 0 < r < rows else 0))
             for c in range(cols + 1)] for r in range(rows + 1)]
    parts = []
    for r in range(rows):
        for c in range(cols):
            a, b = grid[r][c], grid[r][c + 1]
            cc, d = grid[r + 1][c + 1], grid[r + 1][c]
            fill = rnd.choice(fills)
            parts.append(f'<path d="M{a[0]:.1f} {a[1]:.1f}L{b[0]:.1f} {b[1]:.1f}'
                         f'L{cc[0]:.1f} {cc[1]:.1f}L{d[0]:.1f} {d[1]:.1f}Z" fill="{fill}"/>')
            # борозды пашни на части полей
            if rnd.random() < 0.35:
                for s in range(1, 6):
                    t = s / 6
                    p = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
                    q = (d[0] + (cc[0] - d[0]) * t, d[1] + (cc[1] - d[1]) * t)
                    parts.append(f'<path d="M{p[0]:.1f} {p[1]:.1f}L{q[0]:.1f} {q[1]:.1f}" '
                                 f'stroke="{field_stroke}" stroke-opacity=".45" stroke-width=".8"/>')
    parts.append(f'<g fill="none" stroke="{field_stroke}" stroke-width="2.2">' + "".join(
        f'<path d="M{grid[r][0][0]:.1f} {grid[r][0][1]:.1f}' +
        "".join(f'L{x:.1f} {y:.1f}' for x, y in grid[r][1:]) + '"/>' for r in range(1, rows)) +
        "".join(f'<path d="M{grid[0][c][0]:.1f} {grid[0][c][1]:.1f}' +
                "".join(f'L{grid[r][c][0]:.1f} {grid[r][c][1]:.1f}' for r in range(1, rows + 1)) +
                '"/>' for c in range(1, cols)) + '</g>')
    # лес: пятна из кружков
    for fx, fy, n in ((90, 60, 26), (430, 240, 30), (560, 90, 18)):
        for _ in range(n):
            parts.append(f'<circle cx="{fx + rnd.gauss(0, 22):.1f}" cy="{fy + rnd.gauss(0, 14):.1f}" '
                         f'r="{rnd.uniform(4, 8):.1f}" fill="{forest}"/>')
    # Ока: излучина через весь кадр
    rv = [(-20, 250), (80, 215), (170, 245), (250, 190), (300, 120), (380, 95),
          (450, 135), (520, 110), (620, 40)]
    d = SmoothOpen(rv)
    parts.append(f'<path d="{d}" fill="none" stroke="{river}" stroke-width="16" stroke-linecap="round"/>')
    parts.append(f'<path d="{d}" fill="none" stroke="{river_core}" stroke-width="5" '
                 f'stroke-linecap="round" stroke-opacity=".7"/>')
    # аэродром: взлётная полоса с осевой разметкой
    parts.append('<g transform="translate(170 110) rotate(-18)">'
                 '<rect x="-70" y="-7" width="140" height="14" fill="#9AA7B2"/>'
                 '<path d="M-62 0H62" stroke="#fff" stroke-width="1.6" stroke-dasharray="7 6"/>'
                 '<rect x="-70" y="-7" width="5" height="14" fill="#fff" fill-opacity=".8"/>'
                 '<rect x="65" y="-7" width="5" height="14" fill="#fff" fill-opacity=".8"/></g>')
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
           f'preserveAspectRatio="xMidYMid slice">' + "".join(parts) + "</svg>")
    open(os.path.join(IMG, fileName), "w").write(svg)


def Qr(fileName, color):
    import segno
    q = segno.make("https://skycenter.su/", error="m")
    q.save(os.path.join(IMG, fileName), border=0, xmldecl=False, svgns=True,
           nl=False, omitsize=True, dark=color)


if __name__ == "__main__":
    os.makedirs(IMG, exist_ok=True)
    Contours("#C9D3DC", ".22", "contours-silver.svg")
    Contours("#30CFFA", ".35", "contours-cyan.svg")
    # вариант A — светлая «карта»: небесные тинты
    Landscape(["#E4F7FE", "#CFF1FD", "#F4FBFE", "#BDEBFB", "#DDF3F9"],
              "#FFFFFF", "#30CFFA", "#FFFFFF", "#A9E3F5", "oka-light.svg")
    # вариант C — живая земля: насыщенные поля
    Landscape(["#C9D98A", "#A9C46A", "#E2D59A", "#8FB35A", "#D6C77E", "#B8CF7A"],
              "#F3F0DC", "#0075FF", "#7FD8FF", "#5E8F3E", "oka-color.svg")
    Qr("qr-navy.svg", "#0B1B2B")
    Qr("qr-silver.svg", "#C9D3DC")
    Qr("qr-white.svg", "#FFFFFF")
    print("ok")
