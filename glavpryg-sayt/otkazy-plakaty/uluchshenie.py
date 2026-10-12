# Обработка «как у фотографа»: шум и фактура бумаги, баланс белого, локальный контраст,
# сочность цвета, резкость. Запуск: python uluchshenie.py <из папки> <в папку>
import cv2, numpy as np, sys, glob, os
IZ, V = sys.argv[1], sys.argv[2]

def balans(im):
    # растяжка каналов по перцентилям: убирает серую вуаль и цветной сдвиг бумаги
    out = np.empty_like(im, dtype=np.float32)
    for c in range(3):
        lo, hi = np.percentile(im[..., c], (0.5, 99.6))
        out[..., c] = (im[..., c].astype(np.float32) - lo) * 255.0 / max(hi - lo, 1)
    # возвращаем часть исходного цвета, чтобы не пересветить и не перекрасить
    return np.clip(0.75 * out + 0.25 * im, 0, 255).astype(np.uint8)

def sochnost(im, sila=0.28):
    # «вибранс»: тусклые цвета поднимаем сильнее, насыщенные почти не трогаем.
    # Считаем в дробных числах: в 8-битном HSV оттенок идёт шагом 2°, и на небе выходят полосы.
    hsv = cv2.cvtColor(im.astype(np.float32) / 255, cv2.COLOR_BGR2HSV)
    s = hsv[..., 1]
    hsv[..., 1] = np.clip(s + sila * (1 - s) * s * 2.2, 0, 1)
    return np.clip(cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR) * 255 + 0.5, 0, 255).astype(np.uint8)

def kontrast(im):
    # общая S-кривая по яркости: глубина и объём без местного усиления — CLAHE вытягивал складки бумаги
    lab = cv2.cvtColor(im, cv2.COLOR_BGR2LAB)
    x = np.arange(256, dtype=np.float32) / 255
    krivaya = x - 0.35 * np.sin(2 * np.pi * x) / (2 * np.pi)
    lab[..., 0] = cv2.LUT(lab[..., 0], np.clip(krivaya * 255, 0, 255).astype(np.uint8))
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)

def shum(im, myagko=False):
    # Плакат снят на столе: по небу идут складки бумаги (плавные пятна яркости) и зерно печати.
    # Разделяем частоты: тонкие детали (стропы, кромки) берём из снимка, а плавную часть
    # на небе заменяем гладкой — складки уходят, стропы остаются.
    f = im.astype(np.float32)
    d = cv2.fastNlMeansDenoisingColored(im, None, 3 if myagko else 4, 4, 7, 21).astype(np.float32)
    nizk = cv2.GaussianBlur(d, (0, 0), 2.5)
    vys = d - nizk                                     # стропы, кромки, зерно
    lab = cv2.cvtColor(nizk.astype(np.uint8), cv2.COLOR_BGR2LAB).astype(np.float32)
    fonLab = cv2.GaussianBlur(lab, (0, 0), 45)
    # складки меняют в основном яркость, предмет отличается цветом или сильно яркостью
    raz = np.sqrt(((lab[..., 0] - fonLab[..., 0]) * 0.3) ** 2 + ((lab[..., 1] - fonLab[..., 1]) * 2.0) ** 2 + ((lab[..., 2] - fonLab[..., 2]) * 2.0) ** 2)
    nebo = np.clip((20 - raz) / 10, 0, 1)                                  # мягкая маска: 1 — небо
    nebo = cv2.erode(nebo, np.ones((5, 5), np.uint8))                      # край предмета не трогаем
    m = cv2.GaussianBlur(nebo, (0, 0), 3)[..., None]
    # гладкое небо: размытие с весами неба (нормированная свёртка)
    w = cv2.GaussianBlur(nebo, (0, 0), 28)[..., None]
    gladkoe = cv2.GaussianBlur(nizk * nebo[..., None], (0, 0), 28) / np.maximum(w, 1e-3)
    gladkoe = np.where(w > 0.05, gladkoe, nizk)
    # складки гасим почти целиком (88 %), а не до плоской заливки — небо остаётся живым
    nizkNebo = (0.35 if myagko else 0.12) * nizk + (0.65 if myagko else 0.88) * gladkoe
    # на небе зерно глушим, заметные тонкие линии (стропы) оставляем
    # стропы на небе тоньше и слабее шумодава — берём их из исходного снимка:
    # тёмные/светлые тонкие линии через морфологию (чёрная и белая «шляпа»), зерно отсекаем порогом
    gr = cv2.GaussianBlur(cv2.cvtColor(im, cv2.COLOR_BGR2GRAY), (0, 0), 0.8).astype(np.float32)
    ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    temn = cv2.morphologyEx(gr, cv2.MORPH_BLACKHAT, ker)
    svet = cv2.morphologyEx(gr, cv2.MORPH_TOPHAT, ker)
    linii = (np.clip((temn - 12) / 8, 0, 1) * temn - np.clip((svet - 12) / 8, 0, 1) * svet)[..., None]
    a = np.abs(vys).max(axis=2, keepdims=True)
    vysNebo = vys * np.clip((a - 4) / 6, 0, 1) * 0.35 - linii * 0.9
    if myagko:
        vysNebo = vys   # серое небо: стропы светлее фона почти не отличаются от зерна — детали не трогаем
    out = m * (nizkNebo + vysNebo) + (1 - m) * (nizk + vys)
    return np.clip(out, 0, 255).astype(np.uint8), m

def rezkost(im, nebo):
    # резкость — только на предмете, небо не трогаем (иначе проступают ступеньки)
    bl = cv2.GaussianBlur(im, (0, 0), 1.4)
    r = cv2.addWeighted(im, 1.4, bl, -0.4, 0).astype(np.float32)
    return (nebo * im + (1 - nebo) * r)

def zerno(im, nebo):
    # лёгкое зерно, как у матрицы: гладкое небо без полос и «пластика»
    rng = np.random.default_rng(7)
    z = cv2.GaussianBlur(rng.normal(0, 1.6, im.shape[:2]).astype(np.float32), (0, 0), 0.6)[..., None]
    return np.clip(im + z * (0.6 + 0.4 * nebo), 0, 255).astype(np.uint8)

# серое небо и тонкие стропы: складки гасим слабее, детали не трогаем
MYAGKO = {'38-53.jpg', '39-01.jpg'}
os.makedirs(V, exist_ok=True)
for f in sorted(glob.glob(IZ + '/*.jpg')):
    im = cv2.imread(f)
    im, nebo = shum(im, os.path.basename(f) in MYAGKO)
    im = balans(im)
    im = kontrast(im)
    im = sochnost(im)
    im = zerno(rezkost(im, nebo), nebo)
    cv2.imwrite(os.path.join(V, os.path.basename(f)), im, [cv2.IMWRITE_JPEG_QUALITY, 92])
    print(os.path.basename(f))
