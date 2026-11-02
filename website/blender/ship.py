"""Procedural container ship or crude tanker, about 210 m long, bow toward +X, waterline at z = 0, built from code so no model download is needed."""
import math
import random

import bmesh
import bpy

from common import link, math_node, new_material, node, ramp, simple_material

LENGTH_AFT, LENGTH_FWD = -105.0, 105.0
HALF_BEAM = 16.0
KEEL_Z, DECK_Z = -11.0, 8.0
BOW_START = 35.0
STERN_START = -72.0


def x_limits(z):
    """Stem rakes forward with height; the stern run lifts below the waterline toward the propeller."""
    fwd = LENGTH_FWD + 3.5 * max(z, 0) / DECK_Z - 2.0 * min(max(-z / 6, 0), 1) + 2.0 * math.exp(-((z + 7) / 2.2) ** 2)
    aft = LENGTH_AFT + (7.0 * min(max(-z / 4, 0), 1) ** 1.5 if z < 0 else 0.0)
    return aft, fwd


def half_breadth(x, z):
    aft, fwd = x_limits(z)
    zf = min(max(z / DECK_Z, 0), 1)
    zu = min(max(-z / -KEEL_Z, 0), 1)
    hb = HALF_BEAM
    if x > BOW_START:
        s = min((x - BOW_START) / (fwd - BOW_START), 1.0)
        p = 1.8 + 1.4 * zf - 0.5 * zu
        hb *= max(1 - s ** p, 0) ** (0.75 - 0.25 * zf)
    if x < STERN_START:
        s = min((STERN_START - x) / (STERN_START - aft), 1.0)
        keep = 0.86 * zf + (0.25 if z >= -2 else 0.25 * (1 - min((-2 - z) / 6, 1)))
        hb *= 1 - (1 - min(keep, 0.9)) * s ** 2.2
    if z < KEEL_Z + 2.2:
        r = 2.2
        hb = hb - r + math.sqrt(max(r * r - (KEEL_Z + r - z) ** 2, 0))
    return max(hb, 0.02)


def hull_mesh(nu=140, nz=36):
    bm = bmesh.new()
    zs = [KEEL_Z + (DECK_Z - KEEL_Z) * (i / (nz - 1)) ** 0.9 for i in range(nz)]
    rings = []
    for iu in range(nu):
        u = iu / (nu - 1)
        sb, ps = [], []
        for z in zs:
            aft, fwd = x_limits(z)
            x = aft + (fwd - aft) * u
            hb = half_breadth(x, z) if u < 1 else 0.02
            sb.append(bm.verts.new((x, -hb, z)))
            ps.append(bm.verts.new((x, hb, z)))
        rings.append(sb + ps[::-1])
    n = len(rings[0])
    for a, b in zip(rings, rings[1:]):
        for i in range(n):
            j = (i + 1) % n
            bm.faces.new((a[i], b[i], b[j], a[j]))
    bm.faces.new(rings[0][::-1])
    bm.faces.new(rings[-1])
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.03)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new("Hull")
    bm.to_mesh(me)
    bm.free()
    return me


def hull_material():
    m, t, p = new_material("ShipHull")
    tc = node(t, "ShaderNodeTexCoord", (-1400, 0))
    sep = node(t, "ShaderNodeSeparateXYZ", (-1200, 300))
    link(t, tc.outputs["Object"], sep.inputs[0])
    # Paint bands: red antifouling below, black boot-top, dark navy topsides.
    z = sep.outputs["Z"]
    paint = ramp(t, math_node(t, "ADD", z, 0.5), [
        (0.0, (0.30, 0.035, 0.03, 1)), (0.001, (0.30, 0.035, 0.03, 1)), (0.12, (0.012, 0.012, 0.014, 1)),
        (0.62, (0.012, 0.012, 0.014, 1)), (0.63, (0.020, 0.032, 0.060, 1)), (1.0, (0.020, 0.032, 0.060, 1))])
    paint.color_ramp.interpolation = "CONSTANT"
    # Rust streaks run down from the deck edge: noise stretched vertically.
    mapping = node(t, "ShaderNodeMapping", (-1000, -200))
    mapping.inputs["Scale"].default_value = (0.35, 0.35, 0.03)
    link(t, tc.outputs["Object"], mapping.inputs["Vector"])
    streak = node(t, "ShaderNodeTexNoise", (-800, -200), **{"Scale": 3.0, "Detail": 8.0, "Roughness": 0.7})
    link(t, mapping.outputs["Vector"], streak.inputs["Vector"])
    streak_mask = ramp(t, streak.outputs["Fac"], [(0.58, (0, 0, 0, 1)), (0.72, (1, 1, 1, 1))])
    mix = node(t, "ShaderNodeMix", (-200, 200), data_type="RGBA", blend_type="MIX")
    link(t, streak_mask.outputs["Color"], mix.inputs["Factor"])
    link(t, paint.outputs["Color"], mix.inputs["A"])
    mix.inputs["B"].default_value = (0.16, 0.06, 0.025, 1)
    fac_scale = math_node(t, "MULTIPLY", streak_mask.outputs["Color"], 0.55)
    link(t, fac_scale, mix.inputs["Factor"])
    link(t, mix.outputs["Result"], p.inputs["Base Color"])
    p.inputs["Roughness"].default_value = 0.42
    p.inputs["Coat Weight"].default_value = 0.15
    # Plate seams every 10 m along the hull and 2.5 m vertically.
    seams = node(t, "ShaderNodeTexWave", (-800, -500), wave_type="BANDS", bands_direction="X", wave_profile="SAW",
                 **{"Scale": 2 * math.pi / (20 * 10.0), "Distortion": 0.0, "Detail": 0.0})
    link(t, tc.outputs["Object"], seams.inputs["Vector"])
    seam_line = ramp(t, seams.outputs["Fac"], [(0.0, (1, 1, 1, 1)), (0.015, (0, 0, 0, 1)), (1.0, (0, 0, 0, 1))])
    dents = node(t, "ShaderNodeTexNoise", (-800, -800), **{"Scale": 0.6, "Detail": 4.0})
    link(t, tc.outputs["Object"], dents.inputs["Vector"])
    h = math_node(t, "ADD", seam_line.outputs["Color"], math_node(t, "MULTIPLY", dents.outputs["Fac"], 0.6))
    bump = node(t, "ShaderNodeBump", (0, -500), **{"Strength": 0.25, "Distance": 0.02})
    link(t, h, bump.inputs["Height"])
    link(t, bump.outputs["Normal"], p.inputs["Normal"])
    return m


def superstructure_material():
    """White accommodation block with window bands per 2.8 m deck."""
    m, t, p = new_material("Superstructure")
    tc = node(t, "ShaderNodeTexCoord", (-1400, 0))
    sep = node(t, "ShaderNodeSeparateXYZ", (-1200, 0))
    link(t, tc.outputs["Object"], sep.inputs[0])
    zmod = math_node(t, "FLOORED_MODULO", sep.outputs["Z"], 2.8)
    band = math_node(t, "MULTIPLY", math_node(t, "GREATER_THAN", zmod, 1.05),
                     math_node(t, "LESS_THAN", zmod, 2.05))
    hor = math_node(t, "FLOORED_MODULO", math_node(t, "ADD", sep.outputs["X"], sep.outputs["Y"]), 2.4)
    mull = math_node(t, "GREATER_THAN", hor, 1.0)
    win = math_node(t, "MULTIPLY", band, mull)
    geo = node(t, "ShaderNodeNewGeometry", (-1400, -300))
    nz = node(t, "ShaderNodeSeparateXYZ", (-1200, -300))
    link(t, geo.outputs["Normal"], nz.inputs[0])
    vertical = math_node(t, "LESS_THAN", math_node(t, "ABSOLUTE", nz.outputs["Z"]), 0.5)
    win = math_node(t, "MULTIPLY", win, vertical)
    col = node(t, "ShaderNodeMix", (-200, 200), data_type="RGBA")
    link(t, win, col.inputs["Factor"])
    col.inputs["A"].default_value = (0.78, 0.78, 0.76, 1)
    col.inputs["B"].default_value = (0.01, 0.012, 0.015, 1)
    link(t, col.outputs["Result"], p.inputs["Base Color"])
    rough = node(t, "ShaderNodeMix", (-200, -100), data_type="FLOAT")
    link(t, win, rough.inputs["Factor"])
    rough.inputs["A"].default_value = 0.45
    rough.inputs["B"].default_value = 0.03
    link(t, rough.outputs["Result"], p.inputs["Roughness"])
    grime = node(t, "ShaderNodeTexNoise", (-800, -400), **{"Scale": 0.8, "Detail": 6.0})
    link(t, tc.outputs["Object"], grime.inputs["Vector"])
    bump = node(t, "ShaderNodeBump", (0, -400), **{"Strength": 0.05})
    link(t, grime.outputs["Fac"], bump.inputs["Height"])
    link(t, bump.outputs["Normal"], p.inputs["Normal"])
    return m


def container_material():
    m, t, p = new_material("Containers")
    attr = node(t, "ShaderNodeAttribute", (-1200, 300), attribute_name="ccol", attribute_type="GEOMETRY")
    tc = node(t, "ShaderNodeTexCoord", (-1400, 0))
    grime = node(t, "ShaderNodeTexNoise", (-1000, 0), **{"Scale": 0.7, "Detail": 8.0, "Roughness": 0.6})
    link(t, tc.outputs["Object"], grime.inputs["Vector"])
    gm = ramp(t, grime.outputs["Fac"], [(0.4, (1, 1, 1, 1)), (0.75, (0.55, 0.45, 0.38, 1))])
    mul = node(t, "ShaderNodeMix", (-400, 200), data_type="RGBA", blend_type="MULTIPLY")
    mul.inputs["Factor"].default_value = 0.8
    link(t, attr.outputs["Color"], mul.inputs["A"])
    link(t, gm.outputs["Color"], mul.inputs["B"])
    # Steel corner posts and rails: a dark band around each face, from the per-face UV.
    uvn = node(t, "ShaderNodeUVMap", (-1400, -200), uv_map="cuv")
    usep = node(t, "ShaderNodeSeparateXYZ", (-1200, -200))
    link(t, uvn.outputs["UV"], usep.inputs[0])
    def edge(c, w):
        a = math_node(t, "LESS_THAN", c, w)
        b = math_node(t, "GREATER_THAN", c, 1 - w)
        return math_node(t, "MAXIMUM", a, b)
    frame = math_node(t, "MAXIMUM", edge(usep.outputs["X"], 0.014), edge(usep.outputs["Y"], 0.05))
    framed = node(t, "ShaderNodeMix", (-200, 300), data_type="RGBA", blend_type="MULTIPLY")
    link(t, frame, framed.inputs["Factor"])
    link(t, mul.outputs["Result"], framed.inputs["A"])
    framed.inputs["B"].default_value = (0.35, 0.33, 0.32, 1)
    link(t, framed.outputs["Result"], p.inputs["Base Color"])
    p.inputs["Roughness"].default_value = 0.55
    p.inputs["Metallic"].default_value = 0.15
    # Corrugation: vertical ridges every 0.28 m on the long sides.
    wave = node(t, "ShaderNodeTexWave", (-1000, -400), wave_type="BANDS", bands_direction="X", wave_profile="SIN",
                **{"Scale": 2 * math.pi / (20 * 0.28), "Distortion": 0.0, "Detail": 0.0})
    link(t, tc.outputs["Object"], wave.inputs["Vector"])
    wave2 = node(t, "ShaderNodeTexWave", (-1000, -700), wave_type="BANDS", bands_direction="Y", wave_profile="SIN",
                 **{"Scale": 2 * math.pi / (20 * 0.28), "Distortion": 0.0, "Detail": 0.0})
    link(t, tc.outputs["Object"], wave2.inputs["Vector"])
    h = math_node(t, "ADD", math_node(t, "ADD", wave.outputs["Fac"], wave2.outputs["Fac"]), math_node(t, "MULTIPLY", frame, 2.0))
    bump = node(t, "ShaderNodeBump", (-200, -500), **{"Strength": 0.35, "Distance": 0.03})
    link(t, h, bump.inputs["Height"])
    link(t, bump.outputs["Normal"], p.inputs["Normal"])
    return m


PALETTE = [
    ((0.02, 0.10, 0.28), 6), ((0.45, 0.06, 0.04), 5), ((0.62, 0.62, 0.60), 4), ((0.05, 0.22, 0.12), 3),
    ((0.75, 0.30, 0.04), 3), ((0.30, 0.31, 0.33), 4), ((0.12, 0.30, 0.45), 3), ((0.55, 0.45, 0.08), 1),
    ((0.25, 0.10, 0.06), 3), ((0.82, 0.82, 0.80), 2)]


CORNERS = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))


def add_box(bm, layer, cx, cy, z0, lx, ly, lz, colour, uv=None):
    verts = bmesh.ops.create_cube(bm, size=1.0)["verts"]
    for v in verts:
        v.co.x = cx + v.co.x * lx
        v.co.y = cy + v.co.y * ly
        v.co.z = z0 + (v.co.z + 0.5) * lz
    faces = {f for v in verts for f in v.link_faces}
    for f in faces:
        for i, loop in enumerate(f.loops):
            loop[layer] = (*colour, 1.0)
            if uv:
                loop[uv].uv = CORNERS[i % 4]


def containers(seed=3):
    rnd = random.Random(seed)
    colours = [c for c, w in PALETTE for _ in range(w)]
    bm = bmesh.new()
    layer = bm.loops.layers.float_color.new("ccol")
    uv = bm.loops.layers.uv.new("cuv")
    hatch = bmesh.new()
    hlayer = hatch.loops.layers.float_color.new("ccol")
    bay_len, gap, row_w, tier_h = 12.19, 1.3, 2.44, 2.59
    base_z = DECK_Z + 1.4
    x = -70.0
    bay = 0
    while x + bay_len < 93:
        cx = x + bay_len / 2
        hb = min(half_breadth(x, DECK_Z), half_breadth(x + bay_len, DECK_Z)) - 0.9
        rows = max(int(2 * hb / (row_w + 0.05)), 0)
        add_box(hatch, hlayer, cx, 0, DECK_Z, bay_len + 0.6, rows * (row_w + 0.05) + 0.4, 1.4, (0.16, 0.20, 0.17))
        fwd = max(0.0, (x - 40) / 50)
        max_tier = 7 - int(round(fwd * 3))
        for r in range(rows):
            cy = (r - (rows - 1) / 2) * (row_w + 0.05)
            edge = abs(r - (rows - 1) / 2) / max(rows / 2, 1)
            tiers = max_tier - (1 if edge > 0.8 and rnd.random() < 0.5 else 0) - (1 if rnd.random() < 0.18 else 0)
            if rnd.random() < 0.06:
                tiers = rnd.randint(2, tiers)
            for k in range(tiers):
                c = rnd.choice(colours)
                jitter = 0.85 + 0.3 * rnd.random()
                colour = tuple(min(ch * jitter, 1) for ch in c)
                hc = tier_h if rnd.random() < 0.6 else 2.896
                add_box(bm, layer, cx + rnd.uniform(-0.03, 0.03), cy, base_z + k * 2.9, bay_len, row_w, hc - 0.02, colour, uv)
        x += bay_len + gap
        bay += 1
    me = bpy.data.meshes.new("Containers")
    bm.to_mesh(me)
    bm.free()
    hm = bpy.data.meshes.new("HatchCovers")
    hatch.to_mesh(hm)
    hatch.free()
    return me, hm


def box_obj(name, centre, size, material, parent):
    bpy.ops.mesh.primitive_cube_add(size=1, location=centre)
    o = bpy.context.object
    o.name = name
    o.scale = size
    bpy.ops.object.transform_apply(scale=True)
    o.data.materials.append(material)
    o.parent = parent
    return o


def cyl_obj(name, centre, radius, depth, material, parent, rotation=(0, 0, 0), verts=32):
    bpy.ops.mesh.primitive_cylinder_add(vertices=verts, radius=radius, depth=depth, location=centre, rotation=rotation)
    o = bpy.context.object
    o.name = name
    o.data.materials.append(material)
    bpy.ops.object.shade_smooth()
    o.parent = parent
    return o


def deck_plate(z, inset=0.6, n=80):
    """Flat deck following the sheer line, slightly inside the hull edge."""
    aft, fwd = x_limits(z)
    bm = bmesh.new()
    xs = [aft + 0.5 + (fwd - aft - 1.5) * i / (n - 1) for i in range(n)]
    sb = [bm.verts.new((x, -max(half_breadth(x, z) - inset, 0.05), z)) for x in xs]
    ps = [bm.verts.new((x, max(half_breadth(x, z) - inset, 0.05), z)) for x in xs]
    for i in range(n - 1):
        bm.faces.new((sb[i], sb[i + 1], ps[i + 1], ps[i]))
    me = bpy.data.meshes.new("Deck")
    bm.to_mesh(me)
    bm.free()
    return me


def tanker_deck(root, steel, white):
    """Crude tanker deck: red deck plate, centre-line pipe rack and catwalk, tank hatches, midship manifold
    and two hose cranes."""
    deck = bpy.data.objects.new("TankerDeck", deck_plate(DECK_Z + 0.05))
    bpy.context.collection.objects.link(deck)
    deck.data.materials.append(simple_material("DeckRed", (0.20, 0.035, 0.025), roughness=0.75))
    deck.parent = root
    pipe = simple_material("PipeGrey", (0.42, 0.44, 0.42), metallic=0.3, roughness=0.5)
    green = simple_material("ManifoldGreen", (0.10, 0.25, 0.14), roughness=0.5)
    x0, x1 = -72.0, 88.0
    for i, (y, r) in enumerate(((-2.2, 0.35), (-1.3, 0.45), (-0.3, 0.3), (0.6, 0.45), (1.6, 0.3), (2.4, 0.25))):
        cyl_obj(f"Pipe{i}", ((x0 + x1) / 2, y, DECK_Z + 1.1 + 0.2 * (i % 2)), r, x1 - x0, pipe, root,
                rotation=(0, math.pi / 2, 0), verts=12)
    for k, x in enumerate(range(int(x0), int(x1), 8)):
        box_obj(f"PipeRack{k}", (x, 0, DECK_Z + 0.55), (0.4, 6.0, 1.0), steel, root)
        box_obj(f"Catwalk{k}", (x, 4.2, DECK_Z + 1.3), (0.3, 0.3, 2.6), steel, root)
    box_obj("CatwalkDeck", ((x0 + x1) / 2, 4.2, DECK_Z + 2.65), (x1 - x0, 1.4, 0.12), steel, root)
    for side in (-1, 1):
        box_obj(f"CatwalkRail{side}", ((x0 + x1) / 2, 4.2 + side * 0.7, DECK_Z + 3.2), (x1 - x0, 0.06, 0.06),
                white, root)
    # Tank hatches and vent posts in pairs along each side.
    for k, x in enumerate(range(-60, 85, 18)):
        for side in (-1, 1):
            cyl_obj(f"Hatch{k}{side}", (x, side * 8.5, DECK_Z + 0.45), 0.9, 0.8, green, root, verts=16)
            cyl_obj(f"Vent{k}{side}", (x + 4, side * 11.0, DECK_Z + 1.8), 0.25, 3.6, white, root, verts=10)
    # Midship manifold: transverse pipes with risers, and the hose cranes either side.
    for i in range(4):
        cyl_obj(f"Manifold{i}", (-6 + i * 2.2, 0, DECK_Z + 1.4), 0.4, 26, green, root, rotation=(math.pi / 2, 0, 0),
                verts=12)
        for side in (-1, 1):
            cyl_obj(f"Riser{i}{side}", (-6 + i * 2.2, side * 13.2, DECK_Z + 0.8), 0.4, 1.4, green, root, verts=12)
    box_obj("ManifoldPlatform", (-2.7, 0, DECK_Z + 0.25), (11, 28, 0.3), steel, root)
    for side in (-1, 1):
        post = cyl_obj(f"CranePost{side}", (-14, side * 11, DECK_Z + 4), 0.6, 8, white, root, verts=16)
        jib = box_obj(f"CraneJib{side}", (-9, side * 11, DECK_Z + 9.5), (12, 0.5, 0.6), white, root)
        jib.rotation_euler.y = math.radians(-22)
    return deck


def build_ship(name="Ship", seed=3, kind="container"):
    root = bpy.data.objects.new(name, None)
    bpy.context.collection.objects.link(root)

    hull = bpy.data.objects.new("Hull", hull_mesh())
    bpy.context.collection.objects.link(hull)
    hull.data.materials.append(hull_material())
    hull.parent = root
    for poly in hull.data.polygons:
        poly.use_smooth = True
    ws = hull.modifiers.new("WN", "WEIGHTED_NORMAL")
    ws.keep_sharp = True

    white = superstructure_material()
    plain = simple_material("PlainWhite", (0.74, 0.74, 0.72), roughness=0.45)
    steel = simple_material("SteelGrey", (0.35, 0.36, 0.37), metallic=0.6, roughness=0.45)
    if kind == "tanker":
        tanker_deck(root, steel, plain)
    else:
        cme, hme = containers(seed)
        cont = bpy.data.objects.new("Containers", cme)
        bpy.context.collection.objects.link(cont)
        cont.data.materials.append(container_material())
        cont.parent = root
        hatch = bpy.data.objects.new("HatchCovers", hme)
        bpy.context.collection.objects.link(hatch)
        hatch.data.materials.append(simple_material("HatchPaint", (0.10, 0.14, 0.11), roughness=0.6))
        hatch.parent = root

    dark = simple_material("FunnelBlack", (0.015, 0.015, 0.017), roughness=0.5)
    orange = simple_material("Lifeboat", (0.9, 0.28, 0.02), roughness=0.4, coat=0.5)
    red = simple_material("FunnelBand", (0.35, 0.03, 0.02), roughness=0.4)

    # Accommodation block, bridge deck with wings, funnel, mast and radar.
    box_obj("Accommodation", (-82, 0, DECK_Z + 12.5), (12, 26, 25), white, root)
    box_obj("BridgeDeck", (-80.5, 0, DECK_Z + 26.3), (9, 33.5, 2.6), white, root)
    box_obj("BridgeRoof", (-80.5, 0, DECK_Z + 27.8), (9.6, 34, 0.4), steel, root)
    box_obj("Funnel", (-94.5, 0, DECK_Z + 15), (8, 7, 30), plain, root)
    box_obj("FunnelBand", (-94.5, 0, DECK_Z + 27), (8.05, 7.05, 3.0), red, root)
    box_obj("FunnelTop", (-94.5, 0, DECK_Z + 30.3), (8.1, 7.1, 1.0), dark, root)
    box_obj("Poop", (-97, 0, DECK_Z + 1.5), (16, 30, 3), plain, root)
    cyl_obj("Mast", (-80, 0, DECK_Z + 33), 0.25, 9, steel, root)
    box_obj("RadarA", (-80, 0, DECK_Z + 34.5), (0.4, 6, 0.3), steel, root)
    box_obj("RadarB", (-79, 0, DECK_Z + 31), (0.35, 4.5, 0.25), steel, root)
    for side in (-1, 1):
        cyl_obj(f"Lifeboat{side}", (-88, side * 15.2, DECK_Z + 6), 1.6, 8.5, orange, root, rotation=(0, math.pi / 2, 0))
    # Forecastle: raised bow deck and foremast.
    box_obj("Forecastle", (98, 0, DECK_Z + 1.2), (14, 9, 2.4), steel, root)
    cyl_obj("Foremast", (96, 0, DECK_Z + 8), 0.22, 12, steel, root)
    return root
