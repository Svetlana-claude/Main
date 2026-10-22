"""Список объектов .blend: имя, тип, число вершин, модификаторы, размеры.

    blender -b --factory-startup --disable-autoexec <файл.blend> --python 3d/spisok-blend.py
"""
import bpy

for ob in bpy.data.objects:
    mods = ",".join(f"{m.type}" for m in ob.modifiers)
    verts = len(ob.data.vertices) if ob.type == "MESH" else ""
    dims = tuple(round(d, 3) for d in ob.dimensions)
    coll = ",".join(c.name for c in ob.users_collection)
    print(f"ОБЪЕКТ {ob.name!r} {ob.type} верш={verts} мод=[{mods}] размер={dims} колл=[{coll}] родитель={ob.parent.name if ob.parent else ''}")
