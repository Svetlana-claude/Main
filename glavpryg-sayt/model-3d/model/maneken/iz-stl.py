"""STL манекена заказчика → облегчённый GLB для сайта (запускать Blender'ом).

    /opt/blender/blender -b --python iz-stl.py -- <манекен.stl> [треугольников, по умолчанию 10000]

Пропорции и высоты не трогаются (в STL — метры от пола): только поворот в оси моделей
(y вверх, лицом в +z, правая рука в −x), сдвиг на середину по x и z — и прореживание сетки.
Исходник — `maneken-opty.stl` заказчика (торс: шея, руки выше локтя, бёдра до середины).
Пишет maneken.glb рядом со скриптом; его читает osnova.py.
"""
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

argv = sys.argv[sys.argv.index("--") + 1:]
src = argv[0]
cel = int(argv[1]) if len(argv) > 1 else 10000
vyhod = Path(__file__).resolve().parent / "maneken.glb"

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.wm.stl_import(filepath=src)
ob = [o for o in bpy.context.scene.objects if o.type == "MESH"][0]
bpy.context.view_layer.objects.active = ob
ob.select_set(True)
me = ob.data
# STL: z вверх, лицо в −y. Оси моделей сайта: y вверх, лицо в +z.
# Blender при выгрузке glTF сам переводит z-вверх в y-вверх (y_gltf = z, z_gltf = −y),
# поэтому здесь — только сдвиг на середину по x и по глубине; высота остаётся как в STL.
xs = [v.co.x for v in me.vertices]
ys = [v.co.y for v in me.vertices]
sdvig = Vector((-(min(xs) + max(xs)) / 2, -(min(ys) + max(ys)) / 2, 0))
me.transform(Matrix.Translation(sdvig))
# прореживание: схлопывание рёбер с сохранением формы
mod = ob.modifiers.new("prorezh", "DECIMATE")
mod.ratio = min(1.0, cel / len(me.polygons))
bpy.ops.object.modifier_apply(modifier=mod.name)
bpy.ops.object.shade_smooth()
print(f"треугольников после прореживания: {len(ob.data.polygons)}")
bpy.ops.export_scene.gltf(filepath=str(vyhod), export_format="GLB", use_selection=True,
                          export_apply=True, export_normals=True, export_texcoords=False,
                          export_materials="NONE", export_yup=True)
print(f"записано: {vyhod} ({vyhod.stat().st_size // 1024} КБ)")
