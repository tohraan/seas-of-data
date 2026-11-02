"""Sequence B: Sentinel-1 at 693 km over the Gulf at dawn, then the camera drops toward Jebel Ali.

Units are kilometres. The satellite sits at the origin (for float precision) and the Earth is placed below it with
(55.06 E, 25.01 N) straight down. NASA Blue Marble, Black Marble and cloud textures in assets/ (public domain).
  blender -b -P website/blender/seq_b_orbit.py
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bpy  # noqa: E402
from mathutils import Matrix, Vector  # noqa: E402

from common import (ASSETS, camera, key_path, link, math_node, new_material, node, ramp, render_frames,  # noqa: E402
                    reset_scene, save_blend, simple_material)

SEQ = "b"
FRAMES = (1, 150)
R_EARTH = 6371.0
ALT = 693.0
LON0, LAT0 = 55.06, 25.01
SUN_ELEVATION, SUN_AZIMUTH = 30.0, 140.0  # morning light from the south-east over Jebel Ali
GULF = (44.0, 64.0, 14.0, 34.0)  # lon0, lon1, lat0, lat1 of the high-resolution crop
S2_Z10 = (52.5, 57.5, 23.0, 27.0)  # Sentinel-2 cloudless land layers from fetch_s2.py
S2_Z11 = (54.0, 56.4, 24.2, 26.2)
GROUND_SPEED = 7.0  # km/s


def local_frame(lon_deg, lat_deg):
    lon, lat = math.radians(lon_deg), math.radians(lat_deg)
    up = Vector((math.cos(lat) * math.cos(lon), math.cos(lat) * math.sin(lon), math.sin(lat)))
    east = Vector((-math.sin(lon), math.cos(lon), 0))
    north = up.cross(east)
    return east, north, up


def image(t, path, location, colorspace="sRGB", extension="REPEAT"):
    n = node(t, "ShaderNodeTexImage", location)
    n.image = bpy.data.images.load(str(path))
    n.image.colorspace_settings.name = colorspace
    n.extension = extension
    n.interpolation = "Cubic"
    return n


def lonlat_uv(t, tc_socket):
    """Equirectangular UV from Earth-fixed object coordinates."""
    norm = node(t, "ShaderNodeVectorMath", (-1600, 0), operation="NORMALIZE")
    link(t, tc_socket, norm.inputs[0])
    sep = node(t, "ShaderNodeSeparateXYZ", (-1400, 0))
    link(t, norm.outputs["Vector"], sep.inputs[0])
    lon = math_node(t, "ARCTAN2", sep.outputs["Y"], sep.outputs["X"])
    lat = math_node(t, "ARCSINE", sep.outputs["Z"])
    u = math_node(t, "ADD", math_node(t, "DIVIDE", lon, 2 * math.pi), 0.5)
    v = math_node(t, "ADD", math_node(t, "DIVIDE", lat, math.pi), 0.5)
    comb = node(t, "ShaderNodeCombineXYZ", (-800, 0))
    link(t, u, comb.inputs["X"])
    link(t, v, comb.inputs["Y"])
    return comb.outputs["Vector"], lon, lat, norm.outputs["Vector"]


def inside(t, c, feather=12.0):
    """1 well inside [0, 1], ramping to 0 over the outer 1/feather at each edge."""
    return math_node(t, "MINIMUM", math_node(t, "MULTIPLY", c, feather),
                     math_node(t, "MULTIPLY", math_node(t, "SUBTRACT", 1.0, c), feather))


def earth_material(sun_dir_obj):
    m, t, p = new_material("Earth")
    tc = node(t, "ShaderNodeTexCoord", (-1800, 0))
    uv, lon, lat, nrm = lonlat_uv(t, tc.outputs["Object"])
    day = image(t, ASSETS / "world.200412.3x5400x2700.jpg", (-500, 400))
    link(t, uv, day.inputs["Vector"])
    # Sharper layers blended in where they exist: the Blue Marble Gulf crop, then Sentinel-2 land over the UAE.
    colour = day.outputs["Color"]
    layers = [("gulf_44E64E_14N34N.jpg", GULF, False), ("s2_z10.png", S2_Z10, True), ("s2_z11.png", S2_Z11, True)]
    for i, (fname, (b_lon0, b_lon1, b_lat0, b_lat1), masked) in enumerate(layers):
        lon0, lon1, lat0, lat1 = (math.radians(v) for v in (b_lon0, b_lon1, b_lat0, b_lat1))
        gu = math_node(t, "DIVIDE", math_node(t, "SUBTRACT", lon, lon0), lon1 - lon0)
        gv = math_node(t, "DIVIDE", math_node(t, "SUBTRACT", lat, lat0), lat1 - lat0)
        gcomb = node(t, "ShaderNodeCombineXYZ", (-800, 700 + 300 * i))
        link(t, gu, gcomb.inputs["X"])
        link(t, gv, gcomb.inputs["Y"])
        img = image(t, ASSETS / fname, (-500, 800 + 300 * i), extension="EXTEND")
        link(t, gcomb.outputs["Vector"], img.inputs["Vector"])
        w = math_node(t, "MINIMUM", inside(t, gu), inside(t, gv))
        w = math_node(t, "MINIMUM", math_node(t, "MAXIMUM", w, 0.0), 1.0)
        if masked:
            w = math_node(t, "MULTIPLY", w, img.outputs["Alpha"])
        albedo = node(t, "ShaderNodeMix", (-200, 500 + 300 * i), data_type="RGBA")
        link(t, w, albedo.inputs["Factor"])
        link(t, colour, albedo.inputs["A"])
        link(t, img.outputs["Color"], albedo.inputs["B"])
        colour = albedo.outputs["Result"]
    link(t, colour, p.inputs["Base Color"])
    # Ocean mask from colour: blue and dark means water, which gets a sun glint.
    sep = node(t, "ShaderNodeSeparateColor", (0, 200))
    link(t, colour, sep.inputs[0])
    water = math_node(t, "GREATER_THAN", sep.outputs["Blue"], math_node(t, "MULTIPLY", sep.outputs["Red"], 1.6))
    water = math_node(t, "MULTIPLY", water, math_node(t, "LESS_THAN", sep.outputs["Green"], 0.22))
    rough = node(t, "ShaderNodeMix", (200, 0), data_type="FLOAT")
    rough.inputs["A"].default_value = 0.85
    rough.inputs["B"].default_value = 0.4
    link(t, water, rough.inputs["Factor"])
    link(t, rough.outputs["Result"], p.inputs["Roughness"])
    p.inputs["Specular IOR Level"].default_value = 0.35
    # City lights on the night side, faded through the terminator.
    night = image(t, ASSETS / "dnb_land_ocean_ice.2012.3600x1800.jpg", (-500, -300))
    link(t, uv, night.inputs["Vector"])
    sun = node(t, "ShaderNodeCombineXYZ", (-800, -600))
    sun.inputs["X"].default_value, sun.inputs["Y"].default_value, sun.inputs["Z"].default_value = sun_dir_obj
    dot = node(t, "ShaderNodeVectorMath", (-500, -600), operation="DOT_PRODUCT")
    link(t, nrm, dot.inputs[0])
    link(t, sun.outputs["Vector"], dot.inputs[1])
    dark = math_node(t, "SUBTRACT", 1.0, math_node(t, "MULTIPLY", math_node(t, "ADD", dot.outputs["Value"], 0.02), 14.0), clamp=True)
    bw = node(t, "ShaderNodeRGBToBW", (-200, -300))
    link(t, night.outputs["Color"], bw.inputs[0])
    lights = ramp(t, bw.outputs[0], [(0.25, (0, 0, 0, 1)), (0.8, (1.0, 0.62, 0.3, 1))])
    em = math_node(t, "MULTIPLY", dark, 0.8)
    link(t, lights.outputs["Color"], p.inputs["Emission Color"])
    link(t, em, p.inputs["Emission Strength"])
    return m


def cloud_material():
    m, t, p = new_material("Clouds")
    tc = node(t, "ShaderNodeTexCoord", (-1800, 0))
    uv, *_ = lonlat_uv(t, tc.outputs["Object"])
    cl = image(t, ASSETS / "clouds_8k.jpg", (-500, 200), colorspace="Non-Color")
    link(t, uv, cl.inputs["Vector"])
    detail = node(t, "ShaderNodeTexNoise", (-500, -100), **{"Scale": 900.0, "Detail": 10.0, "Roughness": 0.6})
    link(t, tc.outputs["Object"], detail.inputs["Vector"])
    a = math_node(t, "MULTIPLY", cl.outputs["Color"], math_node(t, "ADD", 0.6, math_node(t, "MULTIPLY", detail.outputs["Fac"], 0.8)))
    alpha = ramp(t, a, [(0.28, (0, 0, 0, 1)), (0.85, (1, 1, 1, 1))])
    p.inputs["Base Color"].default_value = (0.92, 0.93, 0.95, 1)
    p.inputs["Roughness"].default_value = 0.9
    link(t, alpha.outputs["Color"], p.inputs["Alpha"])
    return m


def atmosphere_material(density, colour):
    m = bpy.data.materials.new("Atmosphere")
    m.use_nodes = True
    t = m.node_tree
    t.nodes.remove(t.nodes["Principled BSDF"])
    vol = node(t, "ShaderNodeVolumeScatter", (0, 0), **{"Color": (*colour, 1), "Density": density, "Anisotropy": 0.0})
    link(t, vol.outputs[0], t.nodes["Material Output"].inputs["Volume"])
    return m


def sphere(name, radius, mat, subdiv=7):
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=subdiv, radius=radius, location=(0, 0, 0))
    o = bpy.context.object
    o.name = name
    bpy.ops.object.shade_smooth()
    o.data.materials.append(mat)
    return o


# ---------- Sentinel-1 (built in metres under a 0.001 scale parent) ----------

def mli_gold():
    m, t, p = new_material("MLIGold")
    p.inputs["Base Color"].default_value = (1.0, 0.70, 0.28, 1)
    p.inputs["Metallic"].default_value = 1.0
    p.inputs["Roughness"].default_value = 0.32
    p.inputs["Anisotropic"].default_value = 0.4
    tc = node(t, "ShaderNodeTexCoord", (-900, -200))
    vor = node(t, "ShaderNodeTexVoronoi", (-700, -200), **{"Scale": 9.0, "Randomness": 1.0})
    noise = node(t, "ShaderNodeTexNoise", (-700, -450), **{"Scale": 3.0, "Detail": 6.0})
    link(t, tc.outputs["Object"], vor.inputs["Vector"])
    link(t, tc.outputs["Object"], noise.inputs["Vector"])
    h = math_node(t, "ADD", vor.outputs["Distance"], noise.outputs["Fac"])
    bump = node(t, "ShaderNodeBump", (-300, -300), **{"Strength": 0.25, "Distance": 0.02})
    link(t, h, bump.inputs["Height"])
    link(t, bump.outputs["Normal"], p.inputs["Normal"])
    return m


def tiled(name, scale, col1, col2, mortar, roughness=0.3, metallic=0.2):
    m, t, p = new_material(name)
    tc = node(t, "ShaderNodeTexCoord", (-900, 0))
    br = node(t, "ShaderNodeTexBrick", (-600, 0), offset=0.0,
              **{"Scale": scale, "Mortar Size": 0.03, "Bias": 0.0, "Brick Width": 1.0, "Row Height": 1.0,
                 "Color1": (*col1, 1), "Color2": (*col2, 1), "Mortar": (*mortar, 1)})
    link(t, tc.outputs["Object"], br.inputs["Vector"])
    link(t, br.outputs["Color"], p.inputs["Base Color"])
    p.inputs["Roughness"].default_value = roughness
    p.inputs["Metallic"].default_value = metallic
    return m


def mbox(parent, name, centre, size, mat, rot=(0, 0, 0)):
    bpy.ops.mesh.primitive_cube_add(size=1, location=centre, rotation=rot)
    o = bpy.context.object
    o.name = name
    o.scale = size
    o.data.materials.append(mat)
    o.parent = parent
    bev = o.modifiers.new("Bevel", "BEVEL")
    bev.width = 0.015
    bev.segments = 2
    return o


def mcyl(parent, name, centre, r, depth, mat, rot=(0, 0, 0)):
    bpy.ops.mesh.primitive_cylinder_add(vertices=24, radius=r, depth=depth, location=centre, rotation=rot)
    o = bpy.context.object
    o.name = name
    o.data.materials.append(mat)
    bpy.ops.object.shade_smooth()
    o.parent = parent
    return o


def sentinel1(sun_world):
    root = bpy.data.objects.new("Sentinel1", None)
    bpy.context.collection.objects.link(root)
    root.scale = (0.001, 0.001, 0.001)
    gold, white = mli_gold(), simple_material("WhitePaint", (0.8, 0.8, 0.78), roughness=0.5)
    silver = simple_material("SilverMLI", (0.9, 0.9, 0.92), metallic=1.0, roughness=0.15)
    dark = simple_material("Black", (0.02, 0.02, 0.022), roughness=0.4)
    sar = tiled("SARPanel", 4.0, (0.55, 0.56, 0.58), (0.5, 0.51, 0.53), (0.08, 0.08, 0.09), roughness=0.45)
    cells = tiled("SolarCells", 10.0, (0.02, 0.035, 0.11), (0.025, 0.04, 0.12), (0.6, 0.6, 0.62), roughness=0.12, metallic=0.3)
    back = simple_material("PanelBack", (0.75, 0.75, 0.73), roughness=0.6)

    mbox(root, "Bus", (0, 0, 0), (2.8, 3.9, 2.5), gold)
    mbox(root, "BusTop", (0, 0, 1.28), (2.7, 3.8, 0.06), white)
    mbox(root, "BusBottom", (0, 0, -1.28), (2.7, 3.8, 0.06), silver)
    # SAR antenna on the -X side, 12.3 m along track, tilted to look down and to the right of the ground track.
    # Box local X is the panel normal; rotate it to point down and outboard (-X), 30 degrees off nadir.
    sar_rot = (0, math.radians(120), 0)
    mbox(root, "SAR", (-1.75, 0, -0.6), (0.22, 12.3, 0.84), sar, rot=sar_rot)
    for i in range(5):
        mbox(root, f"SARRib{i}", (-1.62, -4.9 + i * 2.45, -0.55), (0.06, 0.08, 0.8), dark, rot=sar_rot)
    mbox(root, "SARYoke", (-1.45, 0, -0.3), (0.3, 0.6, 0.6), silver)
    # Solar wing on +X: yoke plus two panels, rotated to face the sun.
    wing = bpy.data.objects.new("Wing", None)
    bpy.context.collection.objects.link(wing)
    wing.parent = root
    wing.location = (1.5, 0, 0.2)
    mcyl(wing, "Yoke", (1.2, 0, 0), 0.05, 2.4, silver, rot=(0, math.pi / 2, 0))
    for i in range(2):
        cx = 3.2 + i * 4.6
        mbox(wing, f"Panel{i}", (cx, 0, 0), (4.4, 2.6, 0.04), cells)
        mbox(wing, f"PanelBack{i}", (cx, 0, -0.03), (4.4, 2.6, 0.01), back)
    # Small kit: X-band antenna, GPS, star trackers, laser terminal.
    mcyl(root, "XBand", (0.6, 1.4, -1.6), 0.25, 0.5, white)
    mcyl(root, "GPS", (0.4, -1.0, 1.4), 0.12, 0.08, white)
    mbox(root, "StarTracker1", (1.1, -1.6, 1.4), (0.25, 0.25, 0.35), dark)
    mbox(root, "StarTracker2", (1.1, -1.1, 1.4), (0.25, 0.25, 0.35), dark)
    mcyl(root, "LCT", (-0.6, 1.5, 1.45), 0.2, 0.3, silver)
    # Face the panel cells toward the sun around the wing axis (X).
    s = Vector(sun_world)
    wing.rotation_euler.x = math.atan2(-s.y, s.z)
    return root


def main():
    scene = reset_scene("SeqB")
    world = bpy.data.worlds.new("Space")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (0, 0, 0, 1)
    scene.world = world

    east, north, up = local_frame(LON0, LAT0)
    rot = Matrix((east, north, up))  # rows: Earth-fixed -> local (east = +X, north = +Y, up = +Z)
    el, az = math.radians(SUN_ELEVATION), math.radians(SUN_AZIMUTH)
    sun_world = Vector((math.cos(el) * math.sin(az), math.cos(el) * math.cos(az), math.sin(el)))
    sun_obj = rot.transposed() @ sun_world  # in Earth-fixed coordinates for the night-lights mask

    centre = Vector((0, 0, -(R_EARTH + ALT)))
    earth = sphere("Earth", R_EARTH, earth_material(tuple(sun_obj)), subdiv=8)
    earth.matrix_world = Matrix.Translation(centre) @ rot.to_4x4()
    clouds = sphere("Clouds", R_EARTH + 6, cloud_material(), subdiv=7)
    clouds.matrix_world = earth.matrix_world.copy()
    for i, (dr, dens) in enumerate(((12, 0.004), (35, 0.0015), (80, 0.0004))):
        a = sphere(f"Atmo{i}", R_EARTH + dr, atmosphere_material(dens, (0.35, 0.55, 1.0)), subdiv=6)
        a.location = centre

    sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
    sun.data.energy = 6.0
    sun.data.angle = math.radians(0.53)
    sun.data.color = (1.0, 0.93, 0.85)
    bpy.context.collection.objects.link(sun)
    sun.rotation_euler = (-sun_world).to_track_quat("-Z", "Y").to_euler()

    sat = sentinel1(sun_world)
    # Descending pass: flying south (-Y). Ground drifts north under it by ~7 km/s.
    sat.rotation_euler.z = 0.0
    spin = bpy.data.objects.new("EarthSpin", None)
    bpy.context.collection.objects.link(spin)
    spin.location = centre
    bpy.context.view_layer.update()
    for o in (earth, clouds):
        mw = o.matrix_world.copy()
        o.parent = spin
        o.matrix_parent_inverse = spin.matrix_world.inverted()
        o.matrix_world = mw
    drift = GROUND_SPEED * (FRAMES[1] - FRAMES[0]) / 24 / R_EARTH
    key_path(spin, [(FRAMES[0], (0, 0, 0)), (FRAMES[1], (-drift, 0, 0))], attr="rotation_euler", interpolation="LINEAR")

    cam, target = camera(lens=30, clip_end=20000)
    cam.data.clip_start = 0.0005
    # The push-in follows Jebel Ali as it drifts north, from slightly south so north stays up (matching the SAR image).
    def ground(f):
        return GROUND_SPEED * (f - FRAMES[0]) / 24
    key_path(cam, [
        (1, (0.009, 0.018, 0.0015)),
        (40, (0.020, -0.004, 0.0045)),
        (80, (0.004, 0.030, 0.024)),
        (110, (0.0, ground(110) - 2.0, -250.0)),
        (130, (0.0, ground(130) - 0.6, -470.0)),
        (150, (0.0, ground(150) - 0.1, -583.0)),
    ])
    key_path(target, [
        (1, (0.0, -0.001, -0.0040)),
        (40, (0.0, 0.0, -0.0010)),
        (80, (0.0, -0.006, -0.025)),
        (110, (0.0, ground(110), -ALT)),
        (130, (0.0, ground(130), -ALT)),
        (150, (0.0, ground(150), -ALT)),
    ])
    for f, v in ((1, 30), (80, 28), (110, 35), (150, 40)):
        cam.data.lens = v
        cam.data.keyframe_insert("lens", frame=f)

    save_blend(SEQ)
    render_frames(SEQ, *FRAMES)


main()
