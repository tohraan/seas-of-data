"""Sequence A: water-level view of a container ship under way, craning up to a high aerial view of the ship and its wake.

  blender -b -P website/blender/seq_a_ship.py               # all 180 frames
  SEAS_FRAMES=1,90,180 blender -b -P website/blender/seq_a_ship.py
"""
import math
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bpy  # noqa: E402

from common import (animate_ocean_time, camera, far_sea, key_path, link, math_node, node, ocean,  # noqa: E402
                    render_frames, reset_scene, save_blend, sky_world, sun_lamp)
from ship import BOW_START, HALF_BEAM, LENGTH_AFT, LENGTH_FWD, build_ship  # noqa: E402

SEQ = "a"
FRAMES = (1, 180)
SUN_EL, SUN_ROT = 10.0, 107.0
HAZE = (0.50, 0.56, 0.64)
SPEED = 7.0  # m/s through the water
OCEAN_CENTRE_X = -180.0


def wake_foam(ship):
    """Bow wave, hull wash, turbulent stern wake and Kelvin arms, computed in the ship's frame."""
    def build(t, tc, water_noise):
        stc = node(t, "ShaderNodeTexCoord", (-2000, -1200))
        stc.object = ship
        sep = node(t, "ShaderNodeSeparateXYZ", (-1800, -1200))
        link(t, stc.outputs["Object"], sep.inputs[0])
        x, y = sep.outputs["X"], sep.outputs["Y"]
        ay = math_node(t, "ABSOLUTE", y)
        # Distance behind the stern.
        d = math_node(t, "SUBTRACT", LENGTH_AFT, x)
        dpos = math_node(t, "MAXIMUM", d, 0.0)
        behind = math_node(t, "GREATER_THAN", d, -2.0)
        # Turbulent centreline wake: widens slowly, fades over ~400 m.
        width = math_node(t, "ADD", 9.0, math_node(t, "MULTIPLY", dpos, 0.06))
        inside = math_node(t, "SUBTRACT", 1.0, math_node(t, "DIVIDE", ay, width), clamp=True)
        fade = math_node(t, "EXPONENT", math_node(t, "DIVIDE", dpos, -260.0))
        turb = math_node(t, "MULTIPLY", math_node(t, "MULTIPLY", math_node(t, "POWER", inside, 0.6), fade), behind)
        # Kelvin arms at 19.47 degrees, starting from the hull sides.
        arm_y = math_node(t, "ADD", HALF_BEAM, math_node(t, "MULTIPLY", dpos, 0.354))
        arm_w = math_node(t, "ADD", 2.5, math_node(t, "MULTIPLY", dpos, 0.03))
        arm = math_node(t, "SUBTRACT", 1.0,
                        math_node(t, "DIVIDE", math_node(t, "ABSOLUTE", math_node(t, "SUBTRACT", ay, arm_y)), arm_w),
                        clamp=True)
        arm = math_node(t, "MULTIPLY", math_node(t, "MULTIPLY", arm, math_node(t, "EXPONENT",
                        math_node(t, "DIVIDE", dpos, -150.0))), math_node(t, "MULTIPLY", behind, 0.45))
        # Hull wash: a band just outside the hull, strongest at the bow.
        s = math_node(t, "DIVIDE", math_node(t, "SUBTRACT", x, BOW_START), LENGTH_FWD - BOW_START)
        s = math_node(t, "MINIMUM", math_node(t, "MAXIMUM", s, 0.0), 1.0)
        hb = math_node(t, "MULTIPLY", HALF_BEAM, math_node(t, "POWER", math_node(t, "SUBTRACT", 1.0,
                       math_node(t, "POWER", s, 1.8)), 0.75))
        out = math_node(t, "SUBTRACT", ay, hb)
        band_w = math_node(t, "ADD", 3.0, math_node(t, "MULTIPLY", s, 8.0))
        wash = math_node(t, "SUBTRACT", 1.0, math_node(t, "DIVIDE", math_node(t, "MAXIMUM", out, 0.0), band_w), clamp=True)
        along = math_node(t, "MULTIPLY", math_node(t, "GREATER_THAN", x, LENGTH_AFT - 2),
                          math_node(t, "LESS_THAN", x, LENGTH_FWD + 6))
        wash = math_node(t, "MULTIPLY", wash, math_node(t, "MULTIPLY", along, math_node(t, "ADD", 0.6,
                         math_node(t, "MULTIPLY", s, 1.8))))
        total = math_node(t, "MAXIMUM", math_node(t, "MAXIMUM", turb, arm), wash)
        # Break it up with the water-locked noise so the foam streams past the ship.
        grain = math_node(t, "POWER", math_node(t, "MULTIPLY", water_noise, 1.7), 2.2)
        return math_node(t, "MULTIPLY", math_node(t, "MULTIPLY", total, grain), 1.3)
    return build


def main():
    scene = reset_scene("SeqA")
    sky_world(SUN_EL, SUN_ROT, strength=0.14, aerosol=1.6)
    sun_lamp(SUN_EL, SUN_ROT, energy=2.4, colour=(1.0, 0.74, 0.52))

    ship = build_ship()
    sea, mod = ocean(spatial_size=150, repeat=8, wave_scale=0.9, choppiness=1.2, wind=10.0, alignment=0.4,
                     direction_deg=200, foam_coverage=0.4, extra_foam=wake_foam(ship), haze=HAZE, haze_distance=5000,
                     haze_strength=0.6)
    far_sea(haze=HAZE, haze_distance=5000, haze_strength=0.6)
    base = sea.location.copy()
    base.x += OCEAN_CENTRE_X
    # Water streams aft past the ship: move the ocean, keep the ship and its wake mask fixed.
    drift = SPEED * (FRAMES[1] - FRAMES[0]) / 24
    key_path(sea, [(FRAMES[0], base.copy()), (FRAMES[1], (base.x - drift, base.y, base.z))], interpolation="LINEAR")
    animate_ocean_time(mod, *FRAMES)

    # Gentle heave and pitch.
    for f in range(FRAMES[0], FRAMES[1] + 1, 12):
        ship.location.z = 0.25 * math.sin(f / 24 * 2 * math.pi / 9.0)
        ship.rotation_euler.y = math.radians(0.35) * math.sin(f / 24 * 2 * math.pi / 11.0 + 1.0)
        ship.rotation_euler.x = math.radians(0.6) * math.sin(f / 24 * 2 * math.pi / 13.0)
        ship.keyframe_insert("location", frame=f)
        ship.keyframe_insert("rotation_euler", frame=f)

    cam, target = camera(lens=40, clip_end=60000)
    key_path(cam, [
        (1, (165, -52, 2.6)),
        (45, (95, -62, 5.5)),
        (90, (10, -150, 40)),
        (135, (-140, -230, 180)),
        (180, (-330, -120, 640)),
    ])
    key_path(target, [
        (1, (88, -2, 9)),
        (45, (40, 0, 11)),
        (90, (-20, 0, 8)),
        (135, (-90, 0, 0)),
        (180, (-230, 0, 0)),
    ])
    lens = cam.data
    for f, v in ((1, 45), (90, 35), (180, 32)):
        lens.lens = v
        lens.keyframe_insert("lens", frame=f)
    lens.dof.use_dof = True
    lens.dof.aperture_fstop = 8.0
    lens.dof.focus_object = target

    save_blend(SEQ)
    render_frames(SEQ, *FRAMES)


main()
