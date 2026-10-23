"""Выгрузка 3D-моделей систем для доработки у заказчика: файл Blender и STL.

Берётся несжатый GLB из `model/<система>.glb` (его пишет скрипт системы), детали
получают русские имена из списка деталей страницы `prosmotr/src/<система>.html`.
На выходе в каталоге назначения:
  <система>.blend          — детали отдельными объектами, с цветами материалов, и манекен
  <система>.stl            — вся система одним телом, без манекена
  <система>-detali/*.stl   — каждая деталь отдельным файлом
  maneken.stl              — манекен (один на обе системы)
Размеры — в метрах, как в модели (рост манекена ≈ 1,8 м); ось Z — вверх.

    /opt/blender/blender -b --python tools/v-blender.py -- <каталог назначения> [система ...]
"""
import re
import sys
from pathlib import Path

import bpy

ZDES = Path(__file__).resolve().parent.parent
argv = sys.argv[sys.argv.index("--") + 1:]
CEL = Path(argv[0]).resolve()
SISTEMY = argv[1:] or ["sportivnaya-sistema", "lesnik-3"]
MANEKEN = "manekan"


def nazvaniya(s):
    """Ключ детали → название из списка деталей страницы показа."""
    html = (ZDES / "prosmotr/src" / f"{s}.html").read_text(encoding="utf-8")
    # имя объекта в Blender — до 63 байт: берётся название до пояснения после тире
    def korotko(v):
        v = v.split(" — ")[0].strip()
        while len(v.encode()) > 60:
            v = v.rsplit(" ", 1)[0]
        while v.rsplit(" ", 1)[-1] in ("и", "с", "в", "на", "под"):  # не обрывать на предлоге
            v = v.rsplit(" ", 1)[0]
        return v
    return {k: korotko(v) for k, v in
            re.findall(r'data-detal="([^"]+)"><button[^>]*>([^<]+)</button>', html)}


def ochistit():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def eksport_stl(obekty, put):
    bpy.ops.object.select_all(action="DESELECT")
    for o in obekty:
        o.select_set(True)
    bpy.context.view_layer.objects.active = obekty[0]
    put.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.stl_export(filepath=str(put), export_selected_objects=True, ascii_format=False)


CEL.mkdir(parents=True, exist_ok=True)
for s in SISTEMY:
    ochistit()
    bpy.ops.import_scene.gltf(filepath=str(ZDES / "model" / f"{s}.glb"))
    imena = nazvaniya(s)
    imena[MANEKEN] = "Манекен"
    # узлы GLB — детали; объект-меш может лежать под пустышкой с именем детали
    detali = {}
    for o in list(bpy.context.scene.objects):
        if o.type != "MESH":
            continue
        klyuch = o.name.split(".")[0]
        if o.parent is not None and o.parent.type == "EMPTY":
            klyuch = o.parent.name.split(".")[0]
        detali.setdefault(klyuch, []).append(o)
    for klyuch, obekty in detali.items():
        for k, o in enumerate(obekty):
            o.name = imena.get(klyuch, klyuch) + (f" {k + 1}" if len(obekty) > 1 else "")
            o.data.name = o.name
    bpy.ops.wm.save_as_mainfile(filepath=str(CEL / f"{s}.blend"), compress=True)

    sistema = [o for k, ob in detali.items() if k != MANEKEN for o in ob]
    eksport_stl(sistema, CEL / f"{s}.stl")
    for klyuch, obekty in detali.items():
        if klyuch != MANEKEN:
            eksport_stl(obekty, CEL / f"{s}-detali" / f"{klyuch}.stl")
    if MANEKEN in detali and not (CEL / "maneken.stl").exists():
        eksport_stl(detali[MANEKEN], CEL / "maneken.stl")
    print(f"{s}: деталей {len(detali) - (MANEKEN in detali)}, объектов {len(bpy.context.scene.objects)}")
