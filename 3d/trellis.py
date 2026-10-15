#!/usr/bin/env python3
"""Картинка → 3D-модель (.glb) через облачную копию TRELLIS.2 на Hugging Face.

Своей видеокарты не нужно: считает Space microsoft/TRELLIS.2, здесь только клиент.

    3d/.venv/bin/python 3d/trellis.py <картинка> [-o модель.glb]
        [--res 512|1024|1536] [--seed N] [--polygons 300000] [--texture 2048]

Нужен токен Hugging Face (чтение): без него суточной квоты видеокарты
не хватает даже на одну модель. Берётся из переменной HF_TOKEN, иначе из
3d/.env (строка HF_TOKEN=…, вне версий), иначе из ~/.cache/huggingface/token.
"""
import argparse
import os
import shutil
import sys
import time
from pathlib import Path

from gradio_client import Client, handle_file
from gradio_client.exceptions import AppError

SPACE = "microsoft/TRELLIS.2"
HERE = Path(__file__).resolve().parent


def ReadToken():
    """Токен Hugging Face: переменная, затем 3d/.env, затем кеш huggingface."""
    if os.environ.get("HF_TOKEN"):
        return os.environ["HF_TOKEN"].strip()
    env = HERE / ".env"
    if env.is_file():
        for line in env.read_text().splitlines():
            if line.startswith("HF_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"\'')
    cache = Path.home() / ".cache/huggingface/token"
    if cache.is_file():
        return cache.read_text().strip()
    return None


def main():
    p = argparse.ArgumentParser(description="Картинка → .glb через TRELLIS.2")
    p.add_argument("image", type=Path, help="исходная картинка (png, jpg, webp)")
    p.add_argument("-o", "--out", type=Path, help="куда положить .glb (по умолчанию рядом с картинкой)")
    p.add_argument("--res", choices=["512", "1024", "1536"], default="1024", help="разрешение сетки")
    p.add_argument("--seed", type=int, default=0, help="зерно случайности")
    p.add_argument("--polygons", type=int, default=300000, help="сколько треугольников оставить")
    p.add_argument("--texture", type=int, default=2048, help="размер текстуры, px")
    a = p.parse_args()

    if not a.image.is_file():
        sys.exit(f"Нет файла: {a.image}")
    out = a.out or a.image.with_suffix(".glb")

    t0 = time.time()
    token = ReadToken()
    if not token:
        print("Внимание: нет токена Hugging Face — анонимной квоты обычно не хватает.", file=sys.stderr)
    client = Client(SPACE, token=token, verbose=False)
    try:
        # Space хранит промежуточный результат в сессии — шаги идут одним клиентом
        client.predict(api_name="/start_session")
        print("Подготовка картинки (снятие фона)…", flush=True)
        prepared = client.predict(handle_file(str(a.image)), api_name="/preprocess_image")
        print("Построение 3D…", flush=True)
        client.predict(handle_file(prepared), a.seed, a.res, api_name="/image_to_3d")
        print("Сборка .glb…", flush=True)
        glb, _ = client.predict(a.polygons, a.texture, api_name="/extract_glb")
    except AppError as e:
        if "quota" in str(e).lower():
            sys.exit(f"Кончилась квота видеокарты Hugging Face: {e}")
        raise

    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(glb, out)
    print(f"Готово за {time.time() - t0:.0f} с: {out} ({out.stat().st_size / 1e6:.1f} МБ)")


if __name__ == "__main__":
    main()
