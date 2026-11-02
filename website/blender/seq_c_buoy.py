"""Sequence C: Aayush's monitoring buoy riding the swell, with a full orbit that rises to masthead height.

Imports the per-part STLs from cad/buoy/parts (copied to assets/buoy_parts) and upgrades the materials for close-ups.
  blender -b -P website/blender/seq_c_buoy.py
"""
import math
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bpy  # noqa: E402
from mathutils import Vector  # noqa: E402

from common import (ASSETS, animate_ocean_time, camera, far_sea, key_path, link, math_node, new_material, node,  # noqa: E402
                    ocean, ramp, render_frames, reset_scene, save_blend, simple_material, sky_world, sun_lamp)
from ship import build_ship  # noqa: E402

SEQ = "c"
FRAMES = (1, 180)
SUN_EL, SUN_ROT = 13.0, 150.0
HAZE = (0.52, 0.58, 0.66)
WATERLINE = 0.32  # m above the hull underside (WATERLINE_Z in cad/buoy/build_buoy.py)
PARTS = ASSETS / "buoy_parts"


def wet_paint(name, colour, roughness=0.3, coat=0.6, wear=True):
    """Paint that darkens and turns glossy near the waterline, with fouling below it and worn edges above."""
    m, t, p = new_material(name)
    tc = node(t, "ShaderNodeTexCoord", (-1400, 0))
    sep = node(t, "ShaderNodeSeparateXYZ", (-1200, 0))
    link(t, tc.outputs["Object"], sep.inputs[0])
    z = sep.outputs["Z"]
    noise = node(t, "ShaderNodeTexNoise", (-1200, -300), **{"Scale": 9.0, "Detail": 10.0, "Roughness": 0.65})
    link(t, tc.outputs["Object"], noise.inputs["Vector"])
    # Wet band: rises a little with splash noise.
    wet_edge = math_node(t, "ADD", WATERLINE + 0.12, math_node(t, "MULTIPLY", noise.outputs["Fac"], 0.12))
    wet = math_node(t, "LESS_THAN", z, wet_edge)
    fouled = math_node(t, "LESS_THAN", z, WATERLINE - 0.03)
    base = node(t, "ShaderNodeMix", (-400, 300), data_type="RGBA")
    base.inputs["A"].default_value = (*colour, 1)
    base.inputs["B"].default_value = tuple(c * 0.55 for c in colour) + (1,)
    link(t, wet, base.inputs["Factor"])
    foul = node(t, "ShaderNodeMix", (-200, 300), data_type="RGBA")
    foul.inputs["B"].default_value = (0.09, 0.10, 0.04, 1)
    link(t, base.outputs["Result"], foul.inputs["A"])
    link(t, math_node(t, "MULTIPLY", fouled, 0.75), foul.inputs["Factor"])
    out_col = foul.outputs["Result"]
    if wear:
        scratches = node(t, "ShaderNodeTexNoise", (-1200, -600), **{"Scale": 40.0, "Detail": 2.0})
        link(t, tc.outputs["Object"], scratches.inputs["Vector"])
        wm = ramp(t, scratches.outputs["Fac"], [(0.68, (0, 0, 0, 1)), (0.74, (1, 1, 1, 1))])
        worn = node(t, "ShaderNodeMix", (0, 300), data_type="RGBA")
        worn.inputs["B"].default_value = (0.55, 0.52, 0.45, 1)
        link(t, out_col, worn.inputs["A"])
        link(t, math_node(t, "MULTIPLY", wm.outputs["Color"], 0.35), worn.inputs["Factor"])
        out_col = worn.outputs["Result"]
    link(t, out_col, p.inputs["Base Color"])
    r = node(t, "ShaderNodeMix", (-200, 0), data_type="FLOAT")
    r.inputs["A"].default_value = roughness
    r.inputs["B"].default_value = 0.08
    link(t, wet, r.inputs["Factor"])
    link(t, r.outputs["Result"], p.inputs["Roughness"])
    p.inputs["Coat Weight"].default_value = coat
    p.inputs["Coat Roughness"].default_value = 0.08
    bump = node(t, "ShaderNodeBump", (0, -300), **{"Strength": 0.08, "Distance": 0.002})
    link(t, noise.outputs["Fac"], bump.inputs["Height"])
    link(t, bump.outputs["Normal"], p.inputs["Normal"])
    return m


def solar_material():
    m, t, p = new_material("SolarCells")
    tc = node(t, "ShaderNodeTexCoord", (-1400, 0))
    brick = node(t, "ShaderNodeTexBrick", (-1000, 0), offset=0.0, squash=1.0,
                 **{"Scale": 6.4, "Mortar Size": 0.012, "Mortar Smooth": 0.0, "Bias": 0.0, "Brick Width": 1.0,
                    "Row Height": 1.0, "Color1": (0.012, 0.022, 0.06, 1), "Color2": (0.015, 0.028, 0.075, 1),
                    "Mortar": (0.5, 0.52, 0.55, 1)})
    link(t, tc.outputs["Object"], brick.inputs["Vector"])
    link(t, brick.outputs["Color"], p.inputs["Base Color"])
    p.inputs["Roughness"].default_value = 0.18
    p.inputs["Metallic"].default_value = 0.2
    p.inputs["Coat Weight"].default_value = 1.0
    p.inputs["Coat Roughness"].default_value = 0.02
    p.inputs["Thin Film Thickness"].default_value = 120.0
    return m


def buoy_materials():
    hull = wet_paint("BuoyHull", (0.95, 0.60, 0.02), roughness=0.32, coat=0.7)
    return {
        "Hull": hull,
        "Fender": wet_paint("Fender", (0.025, 0.025, 0.028), roughness=0.7, coat=0.0, wear=False),
        "ElectronicsBay": simple_material("Bay", (0.70, 0.72, 0.73), roughness=0.38, coat=0.3),
        "Hatch": simple_material("Hatch", (0.20, 0.22, 0.24), metallic=0.7, roughness=0.38),
        "SolarPanels": solar_material(),
        "PanelPosts": simple_material("Posts", (0.62, 0.63, 0.65), metallic=1.0, roughness=0.32),
        "Mast": simple_material("Mast", (0.80, 0.81, 0.83), metallic=1.0, roughness=0.22),
        "RadarReflector": simple_material("Reflector", (0.70, 0.72, 0.74), metallic=1.0, roughness=0.28),
        "CameraMount": simple_material("CamMount", (0.86, 0.86, 0.85), roughness=0.4, coat=0.4),
        "CameraDome": simple_material("Dome", (0.01, 0.01, 0.012), roughness=0.02, coat=1.0),
        "AISAntenna": simple_material("AIS", (0.03, 0.03, 0.035), roughness=0.45),
        "OilSheenSensor": wet_paint("Sensor", (0.85, 0.20, 0.03), roughness=0.35, coat=0.5, wear=False),
        "SensorWindow": simple_material("SensorGlass", (0.15, 0.7, 0.85), roughness=0.05, coat=1.0),
        "MooringEye": simple_material("Galv", (0.55, 0.56, 0.57), metallic=1.0, roughness=0.5),
    }


def import_buoy():
    root = bpy.data.objects.new("Buoy", None)
    bpy.context.collection.objects.link(root)
    mats = buoy_materials()
    for name, mat in mats.items():
        bpy.ops.wm.stl_import(filepath=str(PARTS / f"{name}.stl"), global_scale=0.001, forward_axis="Y", up_axis="Z")
        part = bpy.context.selected_objects[0]
        part.name = name
        part.data.materials.append(mat)
        bpy.context.view_layer.objects.active = part
        bpy.ops.object.shade_auto_smooth(angle=math.radians(35))
        part.location.z -= WATERLINE
        part.parent = root
    return root


def contact_foam(buoy):
    """Foam ring where the swell slaps the hull."""
    def build(t, tc, water_noise):
        btc = node(t, "ShaderNodeTexCoord", (-2000, -1200))
        btc.object = buoy
        sep = node(t, "ShaderNodeSeparateXYZ", (-1800, -1200))
        link(t, btc.outputs["Object"], sep.inputs[0])
        r = math_node(t, "SQRT", math_node(t, "ADD", math_node(t, "MULTIPLY", sep.outputs["X"], sep.outputs["X"]),
                                           math_node(t, "MULTIPLY", sep.outputs["Y"], sep.outputs["Y"])))
        ring = math_node(t, "SUBTRACT", 1.0, math_node(t, "DIVIDE", math_node(t, "SUBTRACT", r, 0.92), 0.4), clamp=True)
        ring = math_node(t, "POWER", ring, 2.0)
        grain = math_node(t, "POWER", math_node(t, "MULTIPLY", water_noise, 1.8), 2.5)
        return math_node(t, "MULTIPLY", math_node(t, "MULTIPLY", ring, grain), 1.0)
    return build


def bake_bobbing(buoy, sea, mod):
    """Key the buoy's heave, pitch and roll from the ocean surface under it (damped, as a 1.8 m hull averages waves)."""
    scene = bpy.context.scene
    keep = mod.viewport_resolution
    mod.viewport_resolution = mod.resolution
    probes = [Vector((0, 0)), Vector((0.8, 0)), Vector((-0.8, 0)), Vector((0, 0.8)), Vector((0, -0.8))]
    idx = None
    for f in range(FRAMES[0], FRAMES[1] + 1, 3):
        scene.frame_set(f)
        ev = sea.evaluated_get(bpy.context.evaluated_depsgraph_get())
        mw = ev.matrix_world
        if idx is None:
            pts = [(mw @ v.co) for v in ev.data.vertices]
            idx = [min(range(len(pts)), key=lambda i: (pts[i].x - p.x) ** 2 + (pts[i].y - p.y) ** 2) for p in probes]
        h = [(mw @ ev.data.vertices[i].co).z for i in idx]
        buoy.location.z = 0.85 * h[0] + 0.15 * sum(h[1:]) / 4
        buoy.rotation_euler.y = math.atan2(h[2] - h[1], 1.6) * 0.7
        buoy.rotation_euler.x = math.atan2(h[3] - h[4], 1.6) * 0.7
        buoy.keyframe_insert("location", frame=f)
        buoy.keyframe_insert("rotation_euler", frame=f)
    mod.viewport_resolution = keep


def main():
    scene = reset_scene("SeqC")
    sky_world(SUN_EL, SUN_ROT, strength=0.14, aerosol=1.5)
    sun_lamp(SUN_EL, SUN_ROT, energy=2.6, colour=(1.0, 0.76, 0.55))

    buoy = import_buoy()
    sea, mod = ocean(spatial_size=40, repeat=8, wave_scale=0.22, choppiness=0.85, wind=6.0, alignment=0.45,
                     direction_deg=40, foam_coverage=0.25, extra_foam=contact_foam(buoy), haze=HAZE,
                     haze_distance=3500, haze_strength=0.6)
    far_sea(haze=HAZE, haze_distance=3500, haze_strength=0.6)
    animate_ocean_time(mod, *FRAMES, t0=4.0)
    bake_bobbing(buoy, sea, mod)

    # A ship passing on the horizon: what the buoy is there to watch.
    passing = build_ship("PassingShip", seed=11)
    passing.location = (-700, 1900, 0)
    passing.rotation_euler.z = math.radians(-12)
    key_path(passing, [(FRAMES[0], (-700, 1900, 0)), (FRAMES[1], (-650, 1890, 0))], interpolation="LINEAR")

    cam, target = camera(lens=32, clip_end=60000)
    keys, tkeys = [], []
    for i, f in enumerate(range(FRAMES[0], FRAMES[1] + 1, 15)):
        u = (f - FRAMES[0]) / (FRAMES[1] - FRAMES[0])
        ang = math.radians(-115 + 360 * u)
        radius = 8.6 - 1.4 * math.sin(u * math.pi)
        height = 0.8 + 4.2 * u ** 1.5
        keys.append((f, (radius * math.cos(ang), radius * math.sin(ang), height)))
        tkeys.append((f, (0, 0, 1.4 + 0.5 * u)))
    key_path(cam, keys)
    key_path(target, tkeys)
    cam.data.dof.use_dof = True
    cam.data.dof.aperture_fstop = 5.6
    cam.data.dof.focus_object = target

    save_blend(SEQ)
    render_frames(SEQ, *FRAMES)


main()
