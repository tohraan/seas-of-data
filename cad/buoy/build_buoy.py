"""Build the Seas of Data monitoring buoy and export FCStd, STEP and STL.

Run from the repo root:
  flatpak run --command=FreeCADCmd org.freecad.FreeCAD cad/buoy/build_buoy.py

All dimensions are in millimetres. z = 0 is the flat underside of the hull.
"""
import math
import os
from pathlib import Path

import FreeCAD
import Import
import Mesh
import MeshPart
import Part
from FreeCAD import Vector

# Hull
HULL_DIAMETER = 1800
HULL_HEIGHT = 700
HULL_FLAT_RATIO = 0.55  # flat underside radius as a fraction of the hull radius
WATERLINE_Z = 320
FENDER_Z = 470
FENDER_TUBE_RADIUS = 60

# Electronics bay
BAY_RADIUS = 340
BAY_HEIGHT = 420
HATCH_RADIUS = 365
HATCH_THICKNESS = 30
HATCH_BOLTS = 8
HATCH_BOLT_RADIUS = 14

# Solar panels
PANEL_COUNT = 4
PANEL_LENGTH = 560
PANEL_WIDTH = 700
PANEL_THICKNESS = 35
PANEL_TILT_DEG = 25
PANEL_CENTRE_RADIUS = 640
PANEL_CENTRE_HEIGHT = 260  # above the deck
PANEL_POST_RADIUS = 30

# Mast
MAST_RADIUS = 45
MAST_HEIGHT = 1900
STRUT_RADIUS = 18
STRUT_DECK_RADIUS = 650
STRUT_MAST_HEIGHT = 700  # above the hatch

# Radar reflector
REFLECTOR_RADIUS = 230
REFLECTOR_THICKNESS = 8
REFLECTOR_HEIGHT = 1100  # above the hatch

# Camera
CAMERA_PLATE_RADIUS = 130
CAMERA_PLATE_THICKNESS = 20
CAMERA_DOME_RADIUS = 95
CAMERA_PEDESTAL_HEIGHT = 60

# AIS antenna
AIS_ARM_LENGTH = 300
AIS_ARM_RADIUS = 20
AIS_ARM_DROP = 150  # below the mast top
AIS_BASE_RADIUS = 40
AIS_BASE_HEIGHT = 90
AIS_WHIP_RADIUS = 12
AIS_WHIP_HEIGHT = 1100

# Oil-sheen sensor, offset so it stays clear of the mooring chain
SENSOR_OFFSET = 300
SENSOR_RADIUS = 120
SENSOR_HEIGHT = 110
SENSOR_WINDOW_RADIUS = 85
SENSOR_WINDOW_THICKNESS = 12
SENSOR_GUARD_OUTER_RADIUS = 135
SENSOR_GUARD_INNER_RADIUS = 125
SENSOR_GUARD_HEIGHT = 150

# Mooring eye
MOORING_STEM_RADIUS = 45
MOORING_STEM_LENGTH = 220
MOORING_EYE_RADIUS = 90
MOORING_EYE_TUBE_RADIUS = 24

OVERLAP = 5  # parts sink into each other by this much so they fuse into one solid
MESH_LINEAR_DEFLECTION = 1.0
MESH_ANGULAR_DEFLECTION = 0.2

hull_radius = HULL_DIAMETER / 2
deck_z = HULL_HEIGHT
hatch_top_z = deck_z + BAY_HEIGHT + HATCH_THICKNESS
mast_top_z = hatch_top_z + MAST_HEIGHT


def cylinder(radius, height, x=0, y=0, z=0, direction=(0, 0, 1)):
    return Part.makeCylinder(radius, height, Vector(x, y, z), Vector(*direction))


def tube_between(start, end, radius):
    axis = end.sub(start)
    return Part.makeCylinder(radius, axis.Length, start, axis)


def make_hull():
    profile = [
        Vector(0, 0, 0),
        Vector(hull_radius * HULL_FLAT_RATIO, 0, 0),
        Vector(hull_radius, 0, HULL_HEIGHT * 0.45),
        Vector(hull_radius, 0, HULL_HEIGHT * 0.75),
        Vector(hull_radius * 0.9, 0, HULL_HEIGHT),
        Vector(0, 0, HULL_HEIGHT),
        Vector(0, 0, 0),
    ]
    face = Part.Face(Part.makePolygon(profile))
    return face.revolve(Vector(0, 0, 0), Vector(0, 0, 1), 360)


def make_fender():
    return Part.makeTorus(hull_radius, FENDER_TUBE_RADIUS, Vector(0, 0, FENDER_Z))


def make_bay():
    return cylinder(BAY_RADIUS, BAY_HEIGHT + OVERLAP, z=deck_z - OVERLAP)


def make_hatch():
    hatch = cylinder(HATCH_RADIUS, HATCH_THICKNESS, z=deck_z + BAY_HEIGHT)
    for index in range(HATCH_BOLTS):
        angle = 2 * math.pi * index / HATCH_BOLTS
        bolt = cylinder(
            HATCH_BOLT_RADIUS,
            12 + OVERLAP,
            x=(HATCH_RADIUS - 30) * math.cos(angle),
            y=(HATCH_RADIUS - 30) * math.sin(angle),
            z=hatch_top_z - OVERLAP,
        )
        hatch = hatch.fuse(bolt)
    return hatch.removeSplitter()


def make_solar_panels():
    panels = []
    for index in range(PANEL_COUNT):
        angle = 360 * index / PANEL_COUNT
        panel = Part.makeBox(
            PANEL_LENGTH, PANEL_WIDTH, PANEL_THICKNESS,
            Vector(-PANEL_LENGTH / 2, -PANEL_WIDTH / 2, -PANEL_THICKNESS / 2),
        )
        # A positive turn about y lowers the outer edge, so the panels shed water and spray.
        panel.rotate(Vector(0, 0, 0), Vector(0, 1, 0), PANEL_TILT_DEG)
        panel.translate(Vector(PANEL_CENTRE_RADIUS, 0, deck_z + PANEL_CENTRE_HEIGHT))
        panel.rotate(Vector(0, 0, 0), Vector(0, 0, 1), angle)
        panels.append(panel)
    return Part.makeCompound(panels)


def make_panel_posts():
    posts = None
    for index in range(PANEL_COUNT):
        angle = 2 * math.pi * index / PANEL_COUNT
        post = cylinder(
            PANEL_POST_RADIUS,
            PANEL_CENTRE_HEIGHT + OVERLAP,
            x=PANEL_CENTRE_RADIUS * math.cos(angle),
            y=PANEL_CENTRE_RADIUS * math.sin(angle),
            z=deck_z - OVERLAP,
        )
        posts = post if posts is None else posts.fuse(post)
    return posts


def make_mast():
    mast = cylinder(MAST_RADIUS, MAST_HEIGHT + OVERLAP, z=hatch_top_z - OVERLAP)
    for index in range(PANEL_COUNT):
        angle = 2 * math.pi * (index + 0.5) / PANEL_COUNT  # between the panels
        strut = tube_between(
            Vector(STRUT_DECK_RADIUS * math.cos(angle), STRUT_DECK_RADIUS * math.sin(angle), deck_z - OVERLAP),
            Vector(0, 0, hatch_top_z + STRUT_MAST_HEIGHT),
            STRUT_RADIUS,
        )
        mast = mast.fuse(strut)
    arm_z = mast_top_z - AIS_ARM_DROP
    return mast.fuse(cylinder(AIS_ARM_RADIUS, AIS_ARM_LENGTH, z=arm_z, direction=(1, 0, 0))).removeSplitter()


def make_radar_reflector():
    # Three crossed discs form eight corner reflectors, so it returns radar from any bearing.
    centre_z = hatch_top_z + REFLECTOR_HEIGHT
    half = REFLECTOR_THICKNESS / 2
    discs = [
        cylinder(REFLECTOR_RADIUS, REFLECTOR_THICKNESS, z=centre_z - half),
        cylinder(REFLECTOR_RADIUS, REFLECTOR_THICKNESS, x=-half, z=centre_z, direction=(1, 0, 0)),
        cylinder(REFLECTOR_RADIUS, REFLECTOR_THICKNESS, y=-half, z=centre_z, direction=(0, 1, 0)),
    ]
    return discs[0].fuse(discs[1]).fuse(discs[2]).removeSplitter()


def make_camera():
    base = cylinder(CAMERA_PLATE_RADIUS, CAMERA_PLATE_THICKNESS + OVERLAP, z=mast_top_z - OVERLAP)
    pedestal_z = mast_top_z + CAMERA_PLATE_THICKNESS
    pedestal = cylinder(CAMERA_DOME_RADIUS, CAMERA_PEDESTAL_HEIGHT + OVERLAP, z=pedestal_z - OVERLAP)
    return base.fuse(pedestal).removeSplitter()


def make_camera_dome():
    centre_z = mast_top_z + CAMERA_PLATE_THICKNESS + CAMERA_PEDESTAL_HEIGHT
    return Part.makeSphere(CAMERA_DOME_RADIUS, Vector(0, 0, centre_z))


def make_ais_antenna():
    arm_z = mast_top_z - AIS_ARM_DROP
    base = Part.makeCone(AIS_BASE_RADIUS, AIS_WHIP_RADIUS, AIS_BASE_HEIGHT, Vector(AIS_ARM_LENGTH - 25, 0, arm_z))
    whip = cylinder(AIS_WHIP_RADIUS, AIS_WHIP_HEIGHT, x=AIS_ARM_LENGTH - 25, z=arm_z + AIS_BASE_HEIGHT - OVERLAP)
    return base.fuse(whip).removeSplitter()


def make_sensor_housing():
    housing = cylinder(SENSOR_RADIUS, SENSOR_HEIGHT + OVERLAP, x=SENSOR_OFFSET, z=-SENSOR_HEIGHT)
    guard_outer = cylinder(SENSOR_GUARD_OUTER_RADIUS, SENSOR_GUARD_HEIGHT + OVERLAP, x=SENSOR_OFFSET, z=-SENSOR_GUARD_HEIGHT)
    guard_inner = cylinder(SENSOR_GUARD_INNER_RADIUS, SENSOR_GUARD_HEIGHT + OVERLAP, x=SENSOR_OFFSET, z=-SENSOR_GUARD_HEIGHT)
    return housing.fuse(guard_outer.cut(guard_inner))


def make_sensor_window():
    return cylinder(
        SENSOR_WINDOW_RADIUS,
        SENSOR_WINDOW_THICKNESS + OVERLAP,
        x=SENSOR_OFFSET,
        z=-SENSOR_HEIGHT - SENSOR_WINDOW_THICKNESS,
    )


def make_mooring_eye():
    stem = cylinder(MOORING_STEM_RADIUS, MOORING_STEM_LENGTH + OVERLAP, z=-MOORING_STEM_LENGTH)
    eye_z = -MOORING_STEM_LENGTH - MOORING_EYE_RADIUS + MOORING_EYE_TUBE_RADIUS / 2
    eye = Part.makeTorus(MOORING_EYE_RADIUS, MOORING_EYE_TUBE_RADIUS, Vector(0, 0, eye_z), Vector(0, 1, 0))
    return stem.fuse(eye).removeSplitter()


PARTS = {
    "Hull": make_hull,
    "Fender": make_fender,
    "ElectronicsBay": make_bay,
    "Hatch": make_hatch,
    "SolarPanels": make_solar_panels,
    "PanelPosts": make_panel_posts,
    "Mast": make_mast,
    "RadarReflector": make_radar_reflector,
    "CameraMount": make_camera,
    "CameraDome": make_camera_dome,
    "AISAntenna": make_ais_antenna,
    "OilSheenSensor": make_sensor_housing,
    "SensorWindow": make_sensor_window,
    "MooringEye": make_mooring_eye,
}


def script_dir():
    try:
        return Path(__file__).resolve().parent
    except NameError:
        return Path(os.getcwd()) / "cad" / "buoy"


def export_stl(shape, path):
    mesh = MeshPart.meshFromShape(
        Shape=shape,
        LinearDeflection=MESH_LINEAR_DEFLECTION,
        AngularDeflection=MESH_ANGULAR_DEFLECTION,
        Relative=False,
    )
    mesh.write(str(path))
    return mesh


output_dir = script_dir()
parts_dir = output_dir / "parts"
parts_dir.mkdir(exist_ok=True)

doc = FreeCAD.newDocument("Buoy")
features = []
shapes = {}
for name, build in PARTS.items():
    shape = build()
    if not shape.isValid():
        raise RuntimeError(f"{name} is not a valid shape")
    feature = doc.addObject("Part::Feature", name)
    feature.Shape = shape
    features.append(feature)
    shapes[name] = shape
doc.recompute()

first, *rest = [solid for shape in shapes.values() for solid in shape.Solids]
fused = first.multiFuse(rest).removeSplitter()
if not fused.isValid():
    raise RuntimeError("fused buoy is not a valid shape")
if len(fused.Solids) != 1:
    raise RuntimeError(f"expected one connected solid, got {len(fused.Solids)}: a part is floating free")

doc.saveAs(str(output_dir / "buoy.FCStd"))
Import.export(features, str(output_dir / "buoy.step"))
mesh = export_stl(fused, output_dir / "buoy.stl")
if not mesh.isSolid() or mesh.hasNonManifolds():
    raise RuntimeError("buoy.stl is not watertight")
for name, shape in shapes.items():
    export_stl(shape, parts_dir / f"{name}.stl")

# Displacement below the waterline, as a rough sanity figure for the total mass the hull can carry.
below_waterline = Part.makeBox(4000, 4000, 2000, Vector(-2000, -2000, WATERLINE_Z - 2000))
displaced_m3 = fused.common(below_waterline).Volume / 1e9
box = fused.BoundBox
print(f"BUOY_OK solids={len(fused.Solids)} volume_m3={fused.Volume / 1e9:.3f}")
print(f"BUOY_SIZE_MM x={box.XLength:.0f} y={box.YLength:.0f} z={box.ZLength:.0f} zmin={box.ZMin:.0f} zmax={box.ZMax:.0f}")
print(f"BUOY_DISPLACEMENT waterline_z={WATERLINE_Z} displaced_m3={displaced_m3:.3f} seawater_kg={displaced_m3 * 1025:.0f}")
print(f"BUOY_STL triangles={mesh.CountFacets} watertight={mesh.isSolid()}")
