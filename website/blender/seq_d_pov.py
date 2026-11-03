"""Sequence D: what the buoy's camera sees. A long lens on the mast, rocking with the buoy, framed on the tanker
and the slick around it.

  blender -b -P website/blender/seq_d_pov.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bpy  # noqa: E402

from common import camera, render_frames, save_blend  # noqa: E402
from seq_c2_watch import TANKER, build_scene  # noqa: E402

SEQ = "d"
FRAMES = (1, 120)
MAST = 4.5  # camera dome height above the waterline, m


def main():
    buoy, tanker = build_scene("SeqD")
    cam, target = camera(lens=135, clip_end=60000)
    # Ride on the buoy so the frame rocks with it; aim at the tanker's midship.
    cam.parent = buoy
    cam.location = (0, 0, MAST)
    target.location = (TANKER[0] - 40, TANKER[1], 6.0)
    save_blend(SEQ)
    render_frames(SEQ, *FRAMES)


if __name__ == "__main__":
    main()
