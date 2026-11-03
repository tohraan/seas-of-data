"""Export the team's procedural Blender ships (website/blender/ship.py) to small GLB files for the tracker map."""
import sys
from pathlib import Path
import bpy

# The ship builder lives with the site and film renders; run from the repo root:
#   blender -b --factory-startup -P dashboard/pipeline/export_ship_models.py
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "website" / "blender"))
from ship import build_ship  # noqa: E402
from common import simple_material  # noqa: E402

OUT = str(Path(__file__).resolve().parent.parent / "static")


def flatten_materials():
    """glTF keeps only plain colours, so procedural node materials become their main paint colour."""
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        for slot in obj.material_slots:
            m = slot.material
            if m is None:
                continue
            if m.name.startswith("ShipHull"):
                slot.material = simple_material("HullPaint", (0.05, 0.07, 0.10), roughness=0.55)
            elif m.name.startswith("Superstructure") or m.name.startswith("Accommodation") or "White" in m.name and m.node_tree and len(m.node_tree.nodes) > 4:
                slot.material = simple_material("White", (0.80, 0.80, 0.78), roughness=0.45)
            elif m.name.startswith("Containers"):
                c = bpy.data.materials.new("ContainerPaint")
                c.use_nodes = True
                t = c.node_tree
                p = t.nodes.get("Principled BSDF")
                attr = t.nodes.new("ShaderNodeVertexColor")
                attr.layer_name = "ccol"
                t.links.new(attr.outputs["Color"], p.inputs["Base Color"])
                p.inputs["Roughness"].default_value = 0.6
                slot.material = c


for kind in ("container", "tanker"):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    root = build_ship(name=kind, kind=kind)
    flatten_materials()
    for obj in bpy.data.objects:
        if obj.type == "MESH":
            bpy.context.view_layer.objects.active = obj
            for mod in list(obj.modifiers):
                bpy.ops.object.modifier_apply(modifier=mod.name)
    bpy.ops.export_scene.gltf(filepath=f"{OUT}/ship_{kind}.glb", export_format="GLB", export_apply=True, export_yup=False,
                              export_draco_mesh_compression_enable=False, export_materials="EXPORT")
    print("EXPORTED", kind)
