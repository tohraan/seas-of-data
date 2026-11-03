"""Measure the CAD model and write geometry.json, which calc_buoy.py turns into the buoy's numbers.

Run from the repo root, after build_buoy.py:
  flatpak run --command=FreeCADCmd org.freecad.FreeCAD cad/buoy/measure_buoy.py

All lengths are in millimetres. z = 0 is the flat underside of the hull.
"""
import json
import os
from pathlib import Path

import FreeCAD
import Part
from FreeCAD import Vector

WATERLINE_STEPS_MM = range(150, 701, 10)
BOX_MM = 6000


def script_dir():
    try:
        return Path(__file__).resolve().parent
    except NameError:
        return Path(os.getcwd()) / "cad" / "buoy"


def centre_z(shape):
    solids = shape.Solids
    total = sum(solid.Volume for solid in solids)
    return sum(solid.Volume * solid.CenterOfMass.z for solid in solids) / total


def below(shape, z_mm):
    box = Part.makeBox(BOX_MM, BOX_MM, BOX_MM, Vector(-BOX_MM / 2, -BOX_MM / 2, z_mm - BOX_MM))
    return shape.common(box)


output = script_dir()
doc = FreeCAD.openDocument(str(output / "buoy.FCStd"))
parts = {}
solids = []
for feature in doc.Objects:
    shape = feature.Shape
    solids.extend(shape.Solids)
    parts[feature.Name] = {
        "volume_mm3": shape.Volume,
        "area_mm2": shape.Area,
        "centre_z_mm": centre_z(shape),
        "z_min_mm": shape.BoundBox.ZMin,
        "z_max_mm": shape.BoundBox.ZMax,
    }
fused = solids[0].multiFuse(solids[1:]).removeSplitter()

curve = []
for z_mm in WATERLINE_STEPS_MM:
    submerged = below(fused, z_mm)
    # A 1 mm slice just below the waterline gives the water-plane area, which sets the buoy's form stability.
    slice_shape = submerged.common(Part.makeBox(BOX_MM, BOX_MM, 1.0, Vector(-BOX_MM / 2, -BOX_MM / 2, z_mm - 1.0)))
    curve.append({
        "z_mm": z_mm,
        "volume_mm3": submerged.Volume,
        "centre_z_mm": centre_z(submerged),
        "waterplane_area_mm2": slice_shape.Volume,
    })

(output / "geometry.json").write_text(json.dumps({
    "z_top_mm": fused.BoundBox.ZMax,
    "z_bottom_mm": fused.BoundBox.ZMin,
    "parts": parts,
    "displacement_curve": curve,
}, indent=1))
print(f"BUOY_MEASURED parts={len(parts)} stations={len(curve)} top_mm={fused.BoundBox.ZMax:.0f} bottom_mm={fused.BoundBox.ZMin:.0f}")
