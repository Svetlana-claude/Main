"""Анимация-страница (kadr(t), DLINA) → ролик mp4 960×720 и обложка jpg.

    exchange/pwenv/bin/python glavpryg-sayt/tools/animaciya-v-video.py \
        glavpryg-sayt/animaciya-otcepka.html /var/www/glavpryg/public/video/otk-otcepka-mob [--mob]

Кадры снимаются playwright'ом по времени, а не записью экрана: ролик ровный при любой скорости машины.
--mob — телефонная версия анимации (?mob в адресе страницы).
"""
import argparse
import pathlib
import subprocess
import tempfile

from playwright.sync_api import sync_playwright

KADROV = 25

ap = argparse.ArgumentParser()
ap.add_argument('html')
ap.add_argument('vyhod', help='путь без расширения: рядом лягут .mp4 и .jpg')
ap.add_argument('--mob', action='store_true')
ap.add_argument('--oblozhka', type=float, default=3.0, help='секунда кадра для обложки')
a = ap.parse_args()

url = pathlib.Path(a.html).resolve().as_uri() + ('?mob' if a.mob else '')
with tempfile.TemporaryDirectory() as papka, sync_playwright() as pw:
    b = pw.chromium.launch()
    s = b.new_page(viewport={'width': 960, 'height': 720})
    s.goto(url, wait_until='networkidle')
    s.evaluate('document.fonts.ready')
    dlina = s.evaluate('DLINA')
    svg = s.locator('#s')
    n = int(dlina * KADROV)
    for i in range(n):
        s.evaluate(f'kadr({i / KADROV})')
        svg.screenshot(path=f'{papka}/{i:05d}.png')
    s.evaluate(f'kadr({a.oblozhka})')
    svg.screenshot(path=f'{papka}/oblozhka.png')
    b.close()
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-framerate', str(KADROV), '-i', f'{papka}/%05d.png',
                    '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '23', '-preset', 'slow',
                    '-movflags', '+faststart', '-an', a.vyhod + '.mp4'], check=True)
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', f'{papka}/oblozhka.png', '-q:v', '3', a.vyhod + '.jpg'], check=True)
print(a.vyhod + '.mp4', f'{n} кадров, {dlina:.1f} с')
