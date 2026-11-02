"""Shared scene setup for the website renders: render settings, sky and sun, ocean, materials and camera rigs.

Each seq_*.py script imports this and is run with Blender in background mode. Environment variables:
  SEAS_ENGINE   cycles (default) or eevee
  SEAS_SAMPLES  Cycles samples (default 128)
  SEAS_RES      width,height (default 1920,1080)
  SEAS_FRAMES   frames to render: "60" or "1,60,120" or "1-180" or "1-180:8" (every 8th); default all
  SEAS_OUT      output folder (default website/blender/out/<seq>)
  SEAS_OCEAN_RES ocean modifier resolution (default 12)
"""
import math
import os
import sys
from pathlib import Path

import bpy
from mathutils import Vector

HERE = Path(__file__).resolve().parent
ASSETS = HERE / "assets"
ENGINE = os.environ.get("SEAS_ENGINE", "cycles")
SAMPLES = int(os.environ.get("SEAS_SAMPLES", "128"))
RES = tuple(int(v) for v in os.environ.get("SEAS_RES", "1920,1080").split(","))
OCEAN_RES = int(os.environ.get("SEAS_OCEAN_RES", "12"))


# ---------- node helpers ----------

def node(tree, kind, location=(0, 0), **inputs):
    n = tree.nodes.new(kind)
    n.location = location
    for key, value in inputs.items():
        if key in n.inputs:
            n.inputs[key].default_value = value
        else:
            setattr(n, key, value)
    return n


def link(tree, out_socket, in_socket):
    tree.links.new(out_socket, in_socket)


def math_node(tree, op, a=None, b=None, clamp=False):
    n = tree.nodes.new("ShaderNodeMath")
    n.operation = op
    n.use_clamp = clamp
    for i, v in enumerate((a, b)):
        if v is None:
            continue
        if isinstance(v, (int, float)):
            n.inputs[i].default_value = v
        else:
            link(tree, v, n.inputs[i])
    return n.outputs[0]


def ramp(tree, fac, stops):
    """stops: list of (position, (r, g, b, a))."""
    n = tree.nodes.new("ShaderNodeValToRGB")
    els = n.color_ramp.elements
    els[0].position, els[0].color = stops[0]
    els[1].position, els[1].color = stops[-1]
    for pos, col in stops[1:-1]:
        e = els.new(pos)
        e.color = col
    link(tree, fac, n.inputs["Fac"])
    return n


def new_material(name):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    return m, m.node_tree, m.node_tree.nodes["Principled BSDF"]


def simple_material(name, colour, metallic=0.0, roughness=0.5, coat=0.0, emission=None):
    m, _, p = new_material(name)
    p.inputs["Base Color"].default_value = (*colour, 1)
    p.inputs["Metallic"].default_value = metallic
    p.inputs["Roughness"].default_value = roughness
    p.inputs["Coat Weight"].default_value = coat
    if emission:
        p.inputs["Emission Color"].default_value = (*emission[0], 1)
        p.inputs["Emission Strength"].default_value = emission[1]
    return m


# ---------- scene ----------

def reset_scene(name):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.name = name
    scene.render.resolution_x, scene.render.resolution_y = RES
    scene.render.resolution_percentage = 100
    scene.render.fps = 24
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.film_transparent = False
    try:
        scene.view_settings.view_transform = "AgX"
        scene.view_settings.look = "AgX - Punchy"
    except TypeError:
        pass
    if ENGINE == "eevee":
        scene.render.engine = "BLENDER_EEVEE"
        e = scene.eevee
        e.taa_render_samples = 64
        for attr, val in (("use_raytracing", True), ("use_shadows", True), ("use_volumetric_shadows", True),
                          ("shadow_ray_count", 2), ("shadow_step_count", 8)):
            if hasattr(e, attr):
                setattr(e, attr, val)
    else:
        scene.render.engine = "CYCLES"
        prefs = bpy.context.preferences.addons["cycles"].preferences
        prefs.compute_device_type = "METAL"
        prefs.get_devices()
        for d in prefs.devices:
            d.use = True
        c = scene.cycles
        c.device = "GPU"
        c.samples = SAMPLES
        c.use_adaptive_sampling = True
        c.adaptive_threshold = 0.02
        c.use_denoising = True
        c.denoiser = "OPENIMAGEDENOISE"
        c.max_bounces = 8
        c.glossy_bounces = 4
        c.transmission_bounces = 8
        c.volume_bounces = 1
        c.caustics_reflective = False
        c.caustics_refractive = False
        c.blur_glossy = 1.0
        c.sample_clamp_indirect = 8.0
    return scene


def sky_world(sun_elevation_deg, sun_rotation_deg, strength=0.3, air=1.0, aerosol=1.0, sun_disc=True, sun_size_deg=0.6):
    world = bpy.data.worlds.new("Sky")
    world.use_nodes = True
    t = world.node_tree
    sky = node(t, "ShaderNodeTexSky", (-300, 0))
    sky.sky_type = "MULTIPLE_SCATTERING"
    sky.sun_elevation = math.radians(sun_elevation_deg)
    sky.sun_rotation = math.radians(sun_rotation_deg)
    sky.sun_disc = sun_disc
    sky.sun_size = math.radians(sun_size_deg)
    sky.air_density = air
    sky.aerosol_density = aerosol
    sky.altitude = 20
    bg = t.nodes["Background"]
    bg.inputs["Strength"].default_value = strength
    link(t, sky.outputs["Color"], bg.inputs["Color"])
    bpy.context.scene.world = world
    return world


def sun_lamp(elevation_deg, rotation_deg, energy=4.0, colour=(1.0, 0.86, 0.72), angle_deg=0.55):
    """Sun lamp aligned with the sky texture's sun (same convention as Cycles: rotation 0 puts the sun toward +Y,
    increasing rotation swings it toward -X)."""
    data = bpy.data.lights.new("Sun", "SUN")
    data.energy = energy
    data.color = colour
    data.angle = math.radians(angle_deg)
    sun = bpy.data.objects.new("Sun", data)
    bpy.context.collection.objects.link(sun)
    el, rot = math.radians(elevation_deg), math.radians(rotation_deg)
    to_sun = Vector((-math.sin(rot) * math.cos(el), math.cos(rot) * math.cos(el), math.sin(el)))
    sun.rotation_euler = (-to_sun).to_track_quat("-Z", "Y").to_euler()
    return sun


# ---------- ocean ----------

def ocean(name="Ocean", spatial_size=120, repeat=6, wave_scale=1.0, choppiness=1.15, wind=9.0, alignment=0.35,
          direction_deg=30, foam_coverage=0.35, seed=7, resolution=None, extra_foam=None, haze=(0.62, 0.70, 0.78),
          haze_distance=2200.0, haze_strength=1.0):
    """Animated ocean surface with a physically motivated deep-water shader.

    extra_foam(tree, coords) may return a 0..1 socket to add wake or contact foam.
    """
    bpy.ops.mesh.primitive_plane_add(size=2, location=(0, 0, 0))
    obj = bpy.context.object
    obj.name = name
    mod = obj.modifiers.new("Ocean", "OCEAN")
    mod.geometry_mode = "GENERATE"
    mod.resolution = resolution or OCEAN_RES
    mod.viewport_resolution = 4
    mod.spatial_size = int(spatial_size)
    mod.size = 1.0
    mod.repeat_x = mod.repeat_y = repeat
    mod.spectrum = "JONSWAP"
    mod.fetch_jonswap = 80
    mod.sharpen_peak_jonswap = 0.6
    mod.wave_scale = wave_scale
    mod.wave_scale_min = 0.01
    mod.choppiness = choppiness
    mod.wind_velocity = wind
    mod.wave_alignment = alignment
    mod.wave_direction = math.radians(direction_deg)
    mod.damping = 0.5
    mod.random_seed = seed
    mod.use_normals = True
    mod.use_foam = True
    mod.foam_layer_name = "foam"
    mod.foam_coverage = foam_coverage
    mod.depth = 200
    # The generated grid spans [-size/2, size * repeat - size/2] from the object origin; centre it.
    c = -spatial_size * (repeat - 1) / 2
    obj.location = (c, c, 0)
    smooth = obj.modifiers.new("Smooth", "NODES")
    smooth.node_group = shade_smooth_group()
    obj.data.materials.append(ocean_material(extra_foam, haze, haze_distance, haze_strength))
    return obj, mod


def shade_smooth_group():
    """The generated ocean grid comes out flat shaded; this geometry-nodes group smooths it."""
    ng = bpy.data.node_groups.get("ShadeSmooth")
    if ng:
        return ng
    ng = bpy.data.node_groups.new("ShadeSmooth", "GeometryNodeTree")
    ng.interface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    gi = ng.nodes.new("NodeGroupInput")
    go = ng.nodes.new("NodeGroupOutput")
    ss = ng.nodes.new("GeometryNodeSetShadeSmooth")
    ng.links.new(gi.outputs[0], ss.inputs["Geometry"])
    ng.links.new(ss.outputs[0], go.inputs[0])
    return ng


def animate_ocean_time(mod, frame_start, frame_end, t0=0.0, seconds_per_frame=1 / 24):
    mod.time = t0
    mod.keyframe_insert("time", frame=frame_start)
    mod.time = t0 + (frame_end - frame_start) * seconds_per_frame
    mod.keyframe_insert("time", frame=frame_end)
    linear_fcurves(mod.id_data)


def linear_fcurves(idblock):
    ad = idblock.animation_data
    if not ad or not ad.action:
        return
    for fc in all_fcurves(ad.action):
        for kp in fc.keyframe_points:
            kp.interpolation = "LINEAR"


def all_fcurves(action):
    """Blender 5 layered actions keep fcurves in channelbags; older ones expose action.fcurves."""
    if hasattr(action, "fcurves"):
        return list(action.fcurves)
    out = []
    for layer in action.layers:
        for strip in layer.strips:
            for bag in strip.channelbags:
                out.extend(bag.fcurves)
    return out


def ocean_material(extra_foam=None, haze=(0.62, 0.70, 0.78), haze_distance=2200.0, haze_strength=1.0):
    m, t, p = new_material("OceanWater")
    out = t.nodes["Material Output"]
    p.location = (400, 300)
    out.location = (1400, 300)
    tc = node(t, "ShaderNodeTexCoord", (-1600, 0))

    # Fake light-through-crest: lift the body colour where the surface is high.
    sep = node(t, "ShaderNodeSeparateXYZ", (-1400, 400))
    link(t, tc.outputs["Object"], sep.inputs[0])
    crest = math_node(t, "MULTIPLY", sep.outputs["Z"], 0.45)
    crest_ramp = ramp(t, crest, [(0.15, (0.0015, 0.010, 0.014, 1)), (0.9, (0.006, 0.055, 0.055, 1))])
    link(t, crest_ramp.outputs["Color"], p.inputs["Base Color"])
    p.inputs["IOR"].default_value = 1.333
    p.inputs["Specular IOR Level"].default_value = 0.5
    p.inputs["Subsurface Weight"].default_value = 0.0

    # Roughness varies slightly, like wind slicks.
    slick = node(t, "ShaderNodeTexNoise", (-1100, -200), **{"Scale": 0.004, "Detail": 3.0})
    link(t, tc.outputs["Object"], slick.inputs["Vector"])
    rough = ramp(t, slick.outputs["Fac"], [(0.35, (0.025, 0.025, 0.025, 1)), (0.7, (0.075, 0.075, 0.075, 1))])
    link(t, rough.outputs["Color"], p.inputs["Roughness"])

    # Capillary ripples as two bump layers.
    n1 = node(t, "ShaderNodeTexNoise", (-1100, -500), **{"Scale": 0.9, "Detail": 6.0, "Roughness": 0.55})
    n2 = node(t, "ShaderNodeTexNoise", (-1100, -750), **{"Scale": 7.0, "Detail": 4.0})
    link(t, tc.outputs["Object"], n1.inputs["Vector"])
    link(t, tc.outputs["Object"], n2.inputs["Vector"])
    b1 = node(t, "ShaderNodeBump", (-700, -500), **{"Strength": 0.12, "Distance": 0.2})
    b2 = node(t, "ShaderNodeBump", (-500, -600), **{"Strength": 0.06, "Distance": 0.05})
    link(t, n1.outputs["Fac"], b1.inputs["Height"])
    link(t, n2.outputs["Fac"], b2.inputs["Height"])
    link(t, b1.outputs["Normal"], b2.inputs["Normal"])
    link(t, b2.outputs["Normal"], p.inputs["Normal"])

    # Foam: ocean modifier foam layer broken up by noise, plus any extra (wake, contact) foam.
    attr = node(t, "ShaderNodeAttribute", (-1400, 900), attribute_name="foam")
    fnoise = node(t, "ShaderNodeTexNoise", (-1400, 700), **{"Scale": 1.6, "Detail": 10.0, "Roughness": 0.65})
    link(t, tc.outputs["Object"], fnoise.inputs["Vector"])
    foam = math_node(t, "MULTIPLY", attr.outputs["Fac"], fnoise.outputs["Fac"])
    foam = math_node(t, "MULTIPLY", foam, 1.6)
    if extra_foam:
        extra = extra_foam(t, tc, fnoise.outputs["Fac"])
        foam = math_node(t, "MAXIMUM", foam, extra)
    foam_mask = ramp(t, foam, [(0.32, (0, 0, 0, 1)), (0.62, (1, 1, 1, 1))])
    foam_bsdf = node(t, "ShaderNodeBsdfPrincipled", (400, -300), **{
        "Base Color": (0.82, 0.86, 0.86, 1), "Roughness": 0.55, "Subsurface Weight": 0.25,
        "Subsurface Radius": (0.4, 0.6, 0.7)})
    mix = node(t, "ShaderNodeMixShader", (800, 300))
    link(t, foam_mask.outputs["Color"], mix.inputs[0])
    link(t, p.outputs[0], mix.inputs[1])
    link(t, foam_bsdf.outputs[0], mix.inputs[2])

    # Aerial perspective: blend toward the horizon colour with distance, which hides tile repeats.
    cam = node(t, "ShaderNodeCameraData", (600, 700))
    d = math_node(t, "DIVIDE", cam.outputs["View Distance"], haze_distance)
    d = math_node(t, "MULTIPLY", d, -1.0)
    d = math_node(t, "EXPONENT", d)
    fog = math_node(t, "SUBTRACT", 1.0, d, clamp=True)
    haze_em = node(t, "ShaderNodeEmission", (800, 0), **{"Color": (*haze, 1), "Strength": haze_strength})
    mix2 = node(t, "ShaderNodeMixShader", (1100, 300))
    link(t, fog, mix2.inputs[0])
    link(t, mix.outputs[0], mix2.inputs[1])
    link(t, haze_em.outputs[0], mix2.inputs[2])
    link(t, mix2.outputs[0], out.inputs["Surface"])
    return m


def far_sea(z=0.0, size=60000, haze=(0.62, 0.70, 0.78), haze_distance=2200.0, haze_strength=1.0, hole=None):
    """Flat sea out to the horizon beyond the displaced ocean tiles; same shader minus the displacement."""
    bpy.ops.mesh.primitive_plane_add(size=size, location=(0, 0, z - 0.6))
    obj = bpy.context.object
    obj.name = "FarSea"
    obj.data.materials.append(ocean_material(None, haze, haze_distance, haze_strength))
    return obj


# ---------- camera ----------

def camera(lens=35, clip_end=50000, sensor=36):
    cam = bpy.data.objects.new("Camera", bpy.data.cameras.new("Camera"))
    cam.data.lens = lens
    cam.data.sensor_width = sensor
    cam.data.clip_start = 0.1
    cam.data.clip_end = clip_end
    bpy.context.collection.objects.link(cam)
    bpy.context.scene.camera = cam
    target = bpy.data.objects.new("CamTarget", None)
    bpy.context.collection.objects.link(target)
    c = cam.constraints.new("TRACK_TO")
    c.target = target
    c.track_axis = "TRACK_NEGATIVE_Z"
    c.up_axis = "UP_Y"
    return cam, target


def key_path(obj, keys, attr="location", interpolation="BEZIER"):
    """keys: list of (frame, value)."""
    for frame, value in keys:
        setattr(obj, attr, value)
        obj.keyframe_insert(attr, frame=frame)
    ad = obj.animation_data
    if ad and ad.action:
        for fc in all_fcurves(ad.action):
            for kp in fc.keyframe_points:
                kp.interpolation = interpolation
                kp.handle_left_type = kp.handle_right_type = "AUTO_CLAMPED"


def depth_of_field(cam, focus_obj=None, fstop=4.0, distance=None):
    cam.data.dof.use_dof = True
    cam.data.dof.aperture_fstop = fstop
    if focus_obj:
        cam.data.dof.focus_object = focus_obj
    elif distance:
        cam.data.dof.focus_distance = distance


# ---------- render ----------

def parse_frames(default_start, default_end):
    spec = os.environ.get("SEAS_FRAMES", f"{default_start}-{default_end}")
    frames = []
    for part in spec.split(","):
        step = 1
        if ":" in part:
            part, step = part.split(":")
            step = int(step)
        if "-" in part:
            a, b = (int(v) for v in part.split("-"))
            frames.extend(range(a, b + 1, step))
            if frames[-1] != b and step > 1:
                frames.append(b)
        else:
            frames.append(int(part))
    return sorted(set(frames))


def render_frames(seq, default_start, default_end, before_frame=None):
    scene = bpy.context.scene
    out = Path(os.environ.get("SEAS_OUT", HERE / "out" / seq))
    out.mkdir(parents=True, exist_ok=True)
    scene.frame_start, scene.frame_end = default_start, default_end
    for prefix in filter(None, os.environ.get("SEAS_HIDE", "").split(",")):
        for o in scene.objects:
            if o.name.startswith(prefix):
                o.hide_render = True
    for f in parse_frames(default_start, default_end):
        path = out / f"{seq}_{f:04d}.png"
        if path.exists() and not os.environ.get("SEAS_OVERWRITE"):
            print(f"SKIP {path.name}", flush=True)
            continue
        scene.frame_set(f)
        if before_frame:
            before_frame(f)
        scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        print(f"RENDERED {path.name}", flush=True)


def save_blend(seq):
    if os.environ.get("SEAS_SAVE_BLEND"):
        bpy.ops.wm.save_as_mainfile(filepath=str(HERE / "out" / f"{seq}.blend"))


sys.path.insert(0, str(HERE))
