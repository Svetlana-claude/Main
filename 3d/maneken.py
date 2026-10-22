"""Мужской манекен для Blender из официального набора Human Base Meshes.

Берёт из набора две мужские фигуры, кладёт рядом в новый файл и снимает превью:
  слева — цельная реалистичная фигура (сетка из четырёхугольников, лепка через Multires);
  справа — манекен из отдельных частей, связанных в цепочку: поворот части
  тянет за собой всё, что ниже по цепочке, — так ставится поза.

    blender -b --factory-startup --disable-autoexec --python 3d/maneken.py -- \
        <human_base_meshes_bundle.blend> <выход.blend> [превью.png]
"""
import math
import sys

import bpy

args = sys.argv[sys.argv.index("--") + 1:]
nabor, vyhod = args[0], args[1]
prevyu = args[2] if len(args) > 2 else None

# Что берём и куда ставим по X, м
FIGURY = [
    ("Body Male - Realistic", "Манекен — цельный", -0.5),
    ("Body Male - Primitve (Realistic)", "Манекен — из частей", 0.5),
]

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene

with bpy.data.libraries.load(nabor, link=False) as (src, dst):
    dst.collections = [imya for imya, _, _ in FIGURY]

for (imya, novoe, _), coll in zip(FIGURY, dst.collections):
    if coll is None:
        sys.exit(f"В наборе нет коллекции {imya!r}")
    coll.name = novoe
    if coll.asset_data:
        coll.asset_clear()
    scene.collection.children.link(coll)

# Набор кладёт фигуры каждую в своё место — выравниваем: ступни на полу, центр по X.
# Сдвигаем только корневые объекты — дети едут вместе с ними
for _, novoe, x in FIGURY:
    coll = bpy.data.collections[novoe]
    bpy.context.view_layer.update()
    pts = [ob.matrix_world @ v.co for ob in coll.all_objects if ob.type == "MESH" for v in ob.data.vertices]
    minx, maxx = min(p.x for p in pts), max(p.x for p in pts)
    miny, maxy = min(p.y for p in pts), max(p.y for p in pts)
    minz = min(p.z for p in pts)
    dx, dy, dz = x - (minx + maxx) / 2, -(miny + maxy) / 2, -minz
    for ob in coll.all_objects:
        if ob.parent is None:
            ob.location.x += dx
            ob.location.y += dy
            ob.location.z += dz
    vys = max(p.z for p in pts) - minz
    print(f"ФИГУРА {novoe}: рост {vys:.3f} м, объектов {len(coll.all_objects)}")

bpy.ops.file.make_paths_relative()
bpy.ops.wm.save_as_mainfile(filepath=vyhod, compress=True)
print(f"СОХРАНЕНО {vyhod}")

if prevyu:
    # Камера и простой рендер Workbench — видеокарта не нужна
    cam = bpy.data.objects.new("Камера", bpy.data.cameras.new("Камера"))
    scene.collection.objects.link(cam)
    cam.location = (0, -5.2, 1.1)
    cam.rotation_euler = (math.radians(88), 0, 0)
    cam.data.lens = 50
    scene.camera = cam
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "SINGLE"
    scene.display.shading.single_color = (0.85, 0.82, 0.78)
    scene.display.shading.show_cavity = True
    scene.render.resolution_x, scene.render.resolution_y = 1000, 1100
    scene.render.film_transparent = False
    scene.render.filepath = prevyu
    bpy.ops.render.render(write_still=True)
    print(f"ПРЕВЬЮ {prevyu}")
