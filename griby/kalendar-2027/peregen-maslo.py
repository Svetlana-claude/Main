"""Варианты картинки с маслом по образцу — нейросетью SD-Turbo (img2img) на процессоре.

    PYTHONPATH=/home/mokeeva/main/exchange/sdlib /opt/video2x/torch-venv/bin/python \
        peregen-maslo.py образец.png папка [--sila 0.55] [--varianty 1,2,3]

Видеокарты нет, памяти 3 ГБ, bfloat16 процессор не умеет. Поэтому работа идёт
этапами, каждый — отдельным процессом, чтобы память отдавалась целиком:
  tekst  — кодировщик текста (PyTorch) → подсказки в .npy;
  kod    — VAE (OpenVINO) → латент образца;
  unet   — UNet OpenVINO без torch: веса fp32 разворачиваются в 2,4 ГБ, больше
           ничего в процесс не грузится; шаги Euler ancestral посчитаны вручную;
  dekod  — VAE → картинка, затем ×4 Real-ESRGAN (tools/uluchshit-video.py).
UNet — `rupeshs/sd-turbo-openvino`, пересохранённый с весами fp16
(exchange/aevit/fon/unet-fp16; читается с диска через mmap).
Каждый вариант — своя подсказка и своё зерно; сила — насколько уходить от образца.
"""
import argparse, glob, os, subprocess, sys, time
import numpy as np

MODEL = 'stabilityai/sd-turbo'
OV = glob.glob(os.path.expanduser('~/.cache/huggingface/hub/models--rupeshs--sd-turbo-openvino/snapshots/*'))
UNET = '/home/mokeeva/main/exchange/aevit/fon/unet-fp16/openvino_model.xml'
OBSHCHEE = ('macro photograph of golden amber motor oil, viscous glossy liquid, '
            'dark background, studio lighting, bokeh, high detail, sharp focus')
VARIANTY = [
    ('1-vsplesk', 'thick golden oil stream pouring into dark oil, crown splash, flying droplets, cold blue rim light', 11),
    ('2-lenta', 'wide smooth ribbon of golden oil folding over a rippled oil surface, warm amber bokeh, liquid gold', 23),
    ('3-vihr', 'golden oil swirling in a spiral flow, silky waves, small droplets in the air, silver grey reflections', 37),
]
SHIRINA, VYSOTA = 512, 384   # стороны кратны 64 (требование UNet); больше — не хватает памяти
SHAGOV = 4                   # расписание из 4 шагов, при силе 0,55 считаются 2 последних
MASSHTAB_VAE = 0.18215


def Tekst(a, varianty):
    import torch
    from transformers import CLIPTextModel, CLIPTokenizer
    torch.set_num_threads(os.cpu_count() or 4)
    tok = CLIPTokenizer.from_pretrained(MODEL, subfolder='tokenizer')
    te = CLIPTextModel.from_pretrained(MODEL, subfolder='text_encoder', variant='fp16', dtype=torch.float32)
    with torch.inference_mode():
        for imya, tekst, _ in varianty:
            ids = tok(f'{tekst}, {OBSHCHEE}', padding='max_length', max_length=tok.model_max_length,
                      truncation=True, return_tensors='pt').input_ids
            np.save(os.path.join(a.papka, f'tekst-{imya}.npy'), te(ids)[0].numpy())


def Kod(a, varianty):
    import openvino as ov
    from PIL import Image
    im = Image.open(a.obrazec).convert('RGB')
    # образец 1,4 : 1, кадр 4 : 3 — срезаются поровну края слева и справа
    w = round(im.height * SHIRINA / VYSOTA)
    im = im.crop(((im.width - w) // 2, 0, (im.width + w) // 2, im.height)).resize((SHIRINA, VYSOTA), Image.LANCZOS)
    x = (np.asarray(im, np.float32) / 127.5 - 1).transpose(2, 0, 1)[None]
    vae = ov.Core().compile_model(os.path.join(OV[0], 'vae_encoder', 'openvino_model.xml'), 'CPU')
    np.save(os.path.join(a.papka, 'latent-obrazec.npy'), vae(x)[0][:, :4] * MASSHTAB_VAE)


def Unet(a, varianty):
    import openvino as ov
    unet = ov.Core().compile_model(UNET, 'CPU', {'PERFORMANCE_HINT': 'LATENCY'})
    # расписание SD-Turbo: scaled_linear 0.00085…0.012, шаги «trailing»
    bety = np.linspace(0.00085 ** .5, 0.012 ** .5, 1000) ** 2
    alfy = np.cumprod(1 - bety)
    momenty = np.round(np.arange(1000, 0, -1000 / SHAGOV)).astype(int) - 1     # 999 749 499 249
    momenty = momenty[SHAGOV - max(1, int(SHAGOV * a.sila)):]
    sigmy = list(np.sqrt((1 - alfy[momenty]) / alfy[momenty])) + [0.0]
    x0 = np.load(os.path.join(a.papka, 'latent-obrazec.npy'))
    for imya, _, zerno in varianty:
        t0 = time.time()
        rng = np.random.default_rng(zerno)
        tekst = np.load(os.path.join(a.papka, f'tekst-{imya}.npy'))
        lat = x0 + rng.standard_normal(x0.shape, dtype=np.float32) * sigmy[0]
        for i, t in enumerate(momenty):
            s, s2 = sigmy[i], sigmy[i + 1]
            eps = unet([(lat / np.sqrt(s * s + 1)).astype(np.float32), np.array([t], np.int64), tekst])[0]
            chisto = lat - s * eps
            vverh = np.sqrt(s2 * s2 * (s * s - s2 * s2) / (s * s))
            vniz = np.sqrt(s2 * s2 - vverh * vverh)
            lat = chisto + (lat - chisto) / s * vniz + rng.standard_normal(lat.shape, dtype=np.float32) * vverh
        np.save(os.path.join(a.papka, f'latent-{imya}.npy'), lat.astype(np.float32))
        print(f'  {imya}: {time.time() - t0:.0f} с', flush=True)


def Dekod(a, varianty):
    import importlib.util, openvino as ov
    from PIL import Image
    vae = ov.Core().compile_model(os.path.join(OV[0], 'vae_decoder', 'openvino_model.xml'), 'CPU')
    for imya, _, _ in varianty:
        k = vae(np.load(os.path.join(a.papka, f'latent-{imya}.npy')) / MASSHTAB_VAE)[0][0]
        Image.fromarray(((k.transpose(1, 2, 0) + 1) * 127.5).clip(0, 255).astype(np.uint8)).save(
            os.path.join(a.papka, f'maslo-{imya}-malaya.png'))
    del vae
    # увеличение ×4 той же сетью, что у фото мотора
    spec = importlib.util.spec_from_file_location('uv', '/home/mokeeva/main/tools/uluchshit-video.py')
    uv = importlib.util.module_from_spec(spec); spec.loader.exec_module(uv)
    model = uv.ZagruzitModel(0.5)
    for imya, _, _ in varianty:
        malo = np.array(Image.open(os.path.join(a.papka, f'maslo-{imya}-malaya.png')))
        bolshe = Image.fromarray(uv.UluchshitKadr(model, malo, 256))
        bolshe.save(os.path.join(a.papka, f'maslo-{imya}.jpg'), quality=93)
        print(f'  {imya}: {bolshe.size[0]}×{bolshe.size[1]}', flush=True)


ETAPY = {'tekst': Tekst, 'kod': Kod, 'unet': Unet, 'dekod': Dekod}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('obrazec'); ap.add_argument('papka')
    ap.add_argument('--sila', type=float, default=0.55)
    ap.add_argument('--varianty', default='')
    ap.add_argument('--etap', choices=ETAPY)
    a = ap.parse_args()
    nomera = a.varianty.split(',') if a.varianty else None
    varianty = [v for v in VARIANTY if not nomera or v[0].split('-')[0] in nomera]
    os.makedirs(a.papka, exist_ok=True)
    if a.etap:
        return ETAPY[a.etap](a, varianty)
    for etap in ETAPY:
        print(etap, flush=True)
        kod = subprocess.call([sys.executable, '-u', __file__] + sys.argv[1:] + ['--etap', etap])
        if kod:
            sys.exit(f'этап {etap} упал: код {kod}')


if __name__ == '__main__':
    main()
