"""Sequence C2: the buoy riding the morning swell with the dark tanker on the horizon, its slick spreading.
The camera pushes in slowly from just above the water.

  blender -b -P website/blender/seq_c2_watch.py
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bpy  # noqa: E402

from common import (animate_ocean_time, camera, far_sea, key_path, ocean, render_frames, reset_scene,  # noqa: E402
                    save_blend, sky_world, sun_lamp)
from seq_a_ship import oil_slick  # noqa: E402
from seq_c_buoy import bake_bobbing, contact_foam, import_buoy  # noqa: E402
from ship import build_ship  # noqa: E402

SEQ = "c2"
FRAMES = (1, 150)
SUN_EL, SUN_ROT = 16.0, 205.0
HAZE = (0.60, 0.62, 0.66)
TANKER = (250.0, 1100.0, 0.0)  # cheated to 1.1 km so it reads on screen; the story puts it 3.5 km out
TANKER_HEADING = -15.0  # bow to +X, so the slick drifts toward the camera


def build_scene(name):
    reset_scene(name)
    sky_world(SUN_EL, SUN_ROT, strength=0.2, aerosol=1.8)
    sun_lamp(SUN_EL, SUN_ROT, energy=2.8, colour=(1.0, 0.80, 0.62))

    tanker = build_ship("Tanker", kind="tanker")
    tanker.location = TANKER
    tanker.rotation_euler.z = math.radians(TANKER_HEADING)
    buoy = import_buoy()
    sea, mod = ocean(spatial_size=40, repeat=8, wave_scale=0.22, choppiness=0.85, wind=6.0, alignment=0.45,
                     direction_deg=40, foam_coverage=0.25, extra_foam=contact_foam(buoy), haze=HAZE,
                     haze_distance=3500, haze_strength=0.6)
    far_sea(haze=HAZE, haze_distance=3500, haze_strength=0.6, slick=oil_slick(tanker), ripple=(0.08, 1.0, 2.5))
    animate_ocean_time(mod, *FRAMES, t0=4.0)
    bake_bobbing(buoy, sea, mod)
    return buoy, tanker


def main():
    build_scene("SeqC2")
    cam, target = camera(lens=32, clip_end=60000)
    key_path(cam, [(FRAMES[0], (7.4, -12.6, 2.4)), (FRAMES[1], (5.9, -10.0, 2.5))])
    key_path(target, [(FRAMES[0], (-48.0, 300.0, 8.0)), (FRAMES[1], (-44.0, 300.0, 8.0))])
    save_blend(SEQ)
    render_frames(SEQ, *FRAMES)


if __name__ == "__main__":
    main()
