"""Render the buoy to cad/renders/ with Blender. Build the model first with buoy/build_buoy.py.

Run from the repo root:
  flatpak run org.blender.Blender -b -P "$PWD/cad/render_buoy.py"

Imports the per-part STLs from buoy/parts/, the same geometry as buoy/buoy.stl, so each part gets its own material.
"""
import math
import os
import re
from pathlib import Path

import bpy
from mathutils import Vector

CAD_DIR = Path(__file__).resolve().parent
PARTS_DIR = CAD_DIR / "buoy" / "parts"
OUTPUT_DIR = CAD_DIR / "renders"
SAMPLES = int(os.environ.get("SEAS_RENDER_SAMPLES", "64"))
RESOLUTION = (1400, 875)
MM_TO_M = 0.001

# name: (base colour, metallic, roughness, transmission)
MATERIALS = {
    "Hull": ((0.95, 0.62, 0.02), 0.0, 0.35, 0.0),
    "Fender": ((0.02, 0.02, 0.025), 0.0, 0.7, 0.0),
    "ElectronicsBay": ((0.72, 0.74, 0.75), 0.0, 0.4, 0.0),
    "Hatch": ((0.22, 0.24, 0.26), 0.6, 0.4, 0.0),
    "SolarPanels": ((0.01, 0.03, 0.12), 0.3, 0.12, 0.0),
    "PanelPosts": ((0.5, 0.52, 0.54), 1.0, 0.35, 0.0),
    "Mast": ((0.62, 0.64, 0.66), 1.0, 0.3, 0.0),
    "RadarReflector": ((0.16, 0.18, 0.2), 0.5, 0.4, 0.0),
    "CameraMount": ((0.8, 0.8, 0.8), 0.0, 0.4, 0.0),
    "CameraDome": ((0.02, 0.02, 0.03), 0.0, 0.06, 0.0),
    "AISAntenna": ((0.03, 0.03, 0.03), 0.0, 0.45, 0.0),
    "OilSheenSensor": ((0.85, 0.2, 0.03), 0.0, 0.4, 0.0),
    "SensorWindow": ((0.15, 0.75, 0.9), 0.0, 0.05, 0.0),
    "MooringEye": ((0.45, 0.47, 0.48), 1.0, 0.45, 0.0),
}

# name: (location, look-at target, lens in mm or None, orthographic scale or None, show water)
SHOTS = {
    "hero": ((6.2, -6.6, 2.0), (0.0, 0.0, 1.9), 42, None, True),
    "side": ((12.0, 0.0, 1.84), (0.0, 0.0, 1.84), None, 7.8, False),
    "top": ((1.2, -1.6, 9.0), (0.0, 0.0, 0.9), 45, None, True),
    "closeup": ((2.5, -2.3, 1.75), (0.1, 0.0, 1.05), 45, None, True),
    "deck_hero": ((7.5, -5.0, 3.0), (0.0, 0.0, 1.84), 40, None, False),
    "deck_masthead": ((2.6, -2.2, 3.4), (0.12, 0.0, 3.05), 65, None, False),
}
DECK_RESOLUTION = (1920, 1200)
SELECTED_SHOTS = os.environ.get("SEAS_RENDER_SHOTS", ",".join(SHOTS)).split(",")


def waterline_m():
    source = (CAD_DIR / "buoy" / "build_buoy.py").read_text()
    return float(re.search(r"^WATERLINE_Z = (\d+)", source, re.MULTILINE).group(1)) * MM_TO_M


def make_material(name, colour, metallic, roughness, transmission):
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    shader = material.node_tree.nodes["Principled BSDF"]
    shader.inputs["Base Color"].default_value = (*colour, 1)
    shader.inputs["Metallic"].default_value = metallic
    shader.inputs["Roughness"].default_value = roughness
    shader.inputs["Transmission Weight"].default_value = transmission
    return material


def import_parts():
    for name, settings in MATERIALS.items():
        bpy.ops.wm.stl_import(filepath=str(PARTS_DIR / f"{name}.stl"), global_scale=MM_TO_M, forward_axis="Y", up_axis="Z")
        part = bpy.context.selected_objects[0]
        part.name = name
        part.data.materials.append(make_material(name, *settings))
        bpy.context.view_layer.objects.active = part
        bpy.ops.object.shade_auto_smooth(angle=math.radians(35))


def make_water(height):
    bpy.ops.mesh.primitive_plane_add(size=600, location=(0, 0, height))
    water = bpy.context.object
    water.name = "Water"
    material = make_material("Water", (0.004, 0.05, 0.075), 0.0, 0.1, 0.0)
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    coordinates = nodes.new("ShaderNodeTexCoord")
    fine = nodes.new("ShaderNodeTexNoise")
    fine.inputs["Scale"].default_value = 2.2
    fine.inputs["Detail"].default_value = 8.0
    bump = nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.35
    bump.inputs["Distance"].default_value = 0.25
    links.new(coordinates.outputs["Object"], fine.inputs["Vector"])
    links.new(fine.outputs["Fac"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], nodes["Principled BSDF"].inputs["Normal"])
    water.data.materials.append(material)
    return water


def make_sky_world():
    world = bpy.data.worlds.new("Sky")
    world.use_nodes = True
    nodes = world.node_tree.nodes
    sky = nodes.new("ShaderNodeTexSky")
    sky.sun_disc = False
    sky.sun_elevation = math.radians(32)
    sky.sun_rotation = math.radians(200)
    background = nodes["Background"]
    background.inputs["Strength"].default_value = 0.09
    world.node_tree.links.new(sky.outputs["Color"], background.inputs["Color"])
    return world


def make_studio_world():
    world = bpy.data.worlds.new("Studio")
    world.use_nodes = True
    background = world.node_tree.nodes["Background"]
    background.inputs["Color"].default_value = (0.78, 0.82, 0.86, 1)
    background.inputs["Strength"].default_value = 0.9
    return world


def make_sun():
    data = bpy.data.lights.new("Sun", "SUN")
    data.energy = 2.2
    data.angle = math.radians(3)
    sun = bpy.data.objects.new("Sun", data)
    bpy.context.collection.objects.link(sun)
    sun.rotation_euler = (math.radians(52), 0, math.radians(35))


def set_camera(camera, location, target, lens, ortho_scale):
    camera.location = location
    direction = Vector(target) - Vector(location)
    camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    if ortho_scale:
        camera.data.type = "ORTHO"
        camera.data.ortho_scale = ortho_scale
    else:
        camera.data.type = "PERSP"
        camera.data.lens = lens


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = SAMPLES
    scene.cycles.use_denoising = True
    scene.render.image_settings.file_format = "PNG"
    scene.view_settings.view_transform = "Standard"

    OUTPUT_DIR.mkdir(exist_ok=True)
    import_parts()
    water = make_water(waterline_m())
    make_sun()
    sky_world = make_sky_world()
    studio_world = make_studio_world()

    camera = bpy.data.objects.new("Camera", bpy.data.cameras.new("Camera"))
    camera.data.clip_end = 2000
    bpy.context.collection.objects.link(camera)
    scene.camera = camera

    for name in SELECTED_SHOTS:
        location, target, lens, ortho_scale, show_water = SHOTS[name]
        scene.render.resolution_x, scene.render.resolution_y = DECK_RESOLUTION if name.startswith("deck_") else RESOLUTION
        set_camera(camera, location, target, lens, ortho_scale)
        water.hide_render = not show_water
        scene.world = sky_world if show_water else studio_world
        scene.render.filepath = str(OUTPUT_DIR / f"{name}.png")
        bpy.ops.render.render(write_still=True)
        print(f"RENDERED {name}", flush=True)


main()
