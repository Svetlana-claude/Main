#!/usr/bin/env python3
"""Улучшение видео нейросетью: чёткость, детали, снятие шума и следов сжатия.

Модель — Real-ESRGAN `realesr-general-x4v3` (компактная, обучена на сжатых
записях: телефон, экшн-камера, мессенджеры). Считается прямо на процессоре
через OpenVINO (запасной путь — PyTorch): видеокарты на сервере нет, а программный Vulkan (llvmpipe), на
котором работает Video2X, на процессоре в десятки раз медленнее.

    /opt/video2x/torch-venv/bin/python tools/uluchshit-video.py <видео>
        [-o итог.mp4] [--masshtab 2] [--shum 0.5]
        [--nachalo 12.5] [--dlitelnost 3] [--crf 17]

* `--masshtab` — во сколько раз увеличить (1–4; по умолчанию 2). Сеть всегда
  увеличивает в 4 раза, затем кадр ужимается до нужного размера — так даже
  при `1` получается тот же размер, но чётче.
* `--shum` — сила шумоподавления 0…1 (0 — шум и зерно сохраняются, 1 — снимаются
  полностью вместе с мелкой текстурой; по умолчанию 0.5).
* `--nachalo`/`--dlitelnost` — обработать кусок: для пробы до полного прогона.
* Звук переносится (перекодируется в AAC 192 кбит/с).

Скорость на этом сервере — секунды на кадр (печатается по ходу работы вместе
с оценкой оставшегося времени), поэтому сперва — проба на 2–3 секунды.
"""
import argparse, json, math, os, subprocess, sys, time

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

MODELI = '/opt/video2x/modeli'


class SrvggNet(nn.Module):
    """Архитектура SRVGGNetCompact из Real-ESRGAN (32 свёртки по 64 канала, ×4)."""

    def __init__(self, kanaly=64, svertki=32, masshtab=4):
        super().__init__()
        self.masshtab = masshtab
        sloi = [nn.Conv2d(3, kanaly, 3, 1, 1), nn.PReLU(num_parameters=kanaly)]
        for _ in range(svertki):
            sloi += [nn.Conv2d(kanaly, kanaly, 3, 1, 1), nn.PReLU(num_parameters=kanaly)]
        sloi.append(nn.Conv2d(kanaly, 3 * masshtab * masshtab, 3, 1, 1))
        self.body = nn.ModuleList(sloi)
        self.upsampler = nn.PixelShuffle(masshtab)

    def forward(self, x):
        y = x
        for sloy in self.body:
            y = sloy(y)
        return self.upsampler(y) + F.interpolate(x, scale_factor=self.masshtab, mode='nearest')


def ZagruzitModel(shum):
    """Сила шумоподавления — смешением весов двух моделей, как в Real-ESRGAN (dni)."""
    vesa = lambda imya: torch.load(os.path.join(MODELI, imya), map_location='cpu', weights_only=True)['params']
    osnovnaya, bez_shumopod = vesa('realesr-general-x4v3.pth'), vesa('realesr-general-wdn-x4v3.pth')
    model = SrvggNet()
    model.load_state_dict({k: shum * osnovnaya[k] + (1 - shum) * bez_shumopod[k] for k in osnovnaya})
    return model.eval()


def Openvino(model):
    """Та же сеть на OpenVINO: на этом Xeon в 1,7 раза быстрее PyTorch (замер — в architect.md)."""
    import openvino as ov
    om = ov.convert_model(model, example_input=torch.rand(1, 3, 64, 64), input=[1, 3, -1, -1])
    sobrano = ov.Core().compile_model(om, 'CPU', {'PERFORMANCE_HINT': 'LATENCY'})
    return lambda x: torch.from_numpy(sobrano(x.numpy())[0])


@torch.inference_mode()
def UluchshitKadr(model, kadr, plitka=512, zapas=40):
    """Кадр HxWx3 uint8 → 4H x 4W x 3; по плиткам с перекрытием — чтобы уложиться в 2 ГБ памяти.
    Перекрытие шире поля зрения сети (33 свёртки 3×3 — 33 пикселя), иначе на стыках видны швы."""
    x = torch.from_numpy(kadr.copy()).permute(2, 0, 1).float().div_(255).unsqueeze(0)
    _, _, h, w = x.shape
    itog = torch.empty(1, 3, h * 4, w * 4)
    for y0 in range(0, h, plitka):
        for x0 in range(0, w, plitka):
            y1, x1 = min(y0 + plitka, h), min(x0 + plitka, w)
            py0, px0 = max(y0 - zapas, 0), max(x0 - zapas, 0)
            py1, px1 = min(y1 + zapas, h), min(x1 + zapas, w)
            kusok = model(x[:, :, py0:py1, px0:px1])
            itog[:, :, y0 * 4:y1 * 4, x0 * 4:x1 * 4] = kusok[:, :, (y0 - py0) * 4:(y0 - py0 + y1 - y0) * 4,
                                                              (x0 - px0) * 4:(x0 - px0 + x1 - x0) * 4]
    return itog.clamp_(0, 1).mul_(255).round_().byte().squeeze(0).permute(1, 2, 0).numpy()


def Svedeniya(put):
    o = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                                            'stream=width,height,r_frame_rate,nb_frames:format=duration',
                                            '-of', 'json', put]))
    p = o['streams'][0]
    a, b = p['r_frame_rate'].split('/')
    return int(p['width']), int(p['height']), p['r_frame_rate'], float(a) / float(b), float(o['format']['duration'])


def main():
    ap = argparse.ArgumentParser(description='Улучшение видео нейросетью Real-ESRGAN на процессоре')
    ap.add_argument('vhod')
    ap.add_argument('-o', '--vyhod')
    ap.add_argument('--masshtab', type=float, default=2)
    ap.add_argument('--shum', type=float, default=0.5)
    ap.add_argument('--nachalo', type=float, default=0)
    ap.add_argument('--dlitelnost', type=float)
    ap.add_argument('--crf', type=int, default=17)
    ap.add_argument("--plitka", type=int, default=512)
    a = ap.parse_args()
    if not 1 <= a.masshtab <= 4 or not 0 <= a.shum <= 1:
        sys.exit('--masshtab — от 1 до 4, --shum — от 0 до 1')

    w, h, fps_tekst, fps, dlit = Svedeniya(a.vhod)
    vyhod = a.vyhod or os.path.splitext(a.vhod)[0] + f'-uluchsheno-x{a.masshtab:g}.mp4'
    vw, vh = int(round(w * a.masshtab / 2)) * 2, int(round(h * a.masshtab / 2)) * 2
    kusok = (a.dlitelnost if a.dlitelnost else dlit - a.nachalo)
    vsego = max(1, math.floor(kusok * fps + 0.5))
    print(f'{a.vhod}: {w}×{h}, {fps:g} к/с → {vyhod}: {vw}×{vh}; кадров ≈ {vsego}, шумоподавление {a.shum:g}', flush=True)

    torch.set_num_threads(os.cpu_count() or 4)
    model = ZagruzitModel(a.shum)
    try:
        model = Openvino(model)
    except Exception as e:  # без OpenVINO — та же сеть на PyTorch, только медленнее
        print(f'OpenVINO недоступен ({e}); считается на PyTorch', flush=True)

    srez = ['-ss', str(a.nachalo)] + (['-t', str(a.dlitelnost)] if a.dlitelnost else [])
    chtenie = subprocess.Popen(['ffmpeg', '-v', 'error'] + srez + ['-i', a.vhod, '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'],
                               stdout=subprocess.PIPE)
    # звук берётся из того же отрезка исходника и перекодируется в AAC
    zapis = subprocess.Popen(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{w * 4}x{h * 4}',
                              '-r', fps_tekst, '-i', '-'] + srez + ['-i', a.vhod,
                              '-map', '0:v', '-map', '1:a?', '-vf', f'scale={vw}:{vh}:flags=lanczos',
                              '-c:v', 'libx264', '-preset', 'slow', '-crf', str(a.crf), '-pix_fmt', 'yuv420p',
                              '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', '-shortest', vyhod],
                             stdin=subprocess.PIPE)
    razmer = w * h * 3
    nachato, n = time.time(), 0
    while True:
        bufer = chtenie.stdout.read(razmer)
        if len(bufer) < razmer:
            break
        zapis.stdin.write(UluchshitKadr(model, np.frombuffer(bufer, np.uint8).reshape(h, w, 3), a.plitka).tobytes())
        n += 1
        proshlo = time.time() - nachato
        if n == 1 or n % 10 == 0:
            ostalos = proshlo / n * max(vsego - n, 0)
            print(f'  кадр {n}/{vsego}: {proshlo / n:.1f} с на кадр, осталось ≈ {ostalos / 60:.0f} мин', flush=True)
    zapis.stdin.close()
    kod = zapis.wait() or chtenie.wait()
    if kod or not n:
        sys.exit(f'Не получилось: ffmpeg вернул {kod}, кадров обработано {n}')
    print(f'Готово: {vyhod} — {n} кадров за {(time.time() - nachato) / 60:.1f} мин', flush=True)


if __name__ == '__main__':
    main()
