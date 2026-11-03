"""Draw hidden-line side and plan views of the buoy from the CAD part meshes (cad/buoy/parts/*.stl).
Usage: python3 -I deck/figures/make_blueprint.py <parts dir> <out dir>
Output: blueprint_side.png and blueprint_plan.png, 1120x1280 (2x of the 560x640 slide panels), no dimensions:
the slide draws the dimension lines over them, using the same scale and origin as below.
"""
import struct, sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import binary_erosion

BG, LINE = (14, 53, 87), (191, 217, 242)
SS, OUT = 3, 2          # supersample factor, output density relative to slide px
W, H = 560, 640         # slide panel size

# slide-px mapping, shared with the slide generator
SIDE = dict(s=0.13, cx=215, top=40, ztop=4085)      # y = top + (ztop - z) * s
PLAN = dict(s=0.26, cx=280, cy=275)


def load(path):
    b = Path(path).read_bytes()
    n = struct.unpack("<I", b[80:84])[0]
    a = np.frombuffer(b[84:84 + 50 * n], dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]))
    return a["v"].astype(float)          # (n, 3 vertices, xyz)


def draw(parts, project, depth, out):
    k = OUT * SS
    img = Image.new("RGB", (W * k, H * k), BG)
    px = img.load()
    for tri in sorted(parts, key=depth):
        mask = Image.new("L", (W * k, H * k), 0)
        d = ImageDraw.Draw(mask)
        for t in project(tri):
            d.polygon([(x * k, y * k) for x, y in t], fill=255)
        m = np.array(mask) > 0
        edge = m & ~binary_erosion(m, iterations=k)
        arr = np.array(img)
        arr[m] = BG
        arr[edge] = LINE
        img = Image.fromarray(arr)
    img.resize((W * OUT, H * OUT), Image.LANCZOS).save(out)


def main(parts_dir, out_dir):
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    parts = [load(p) for p in sorted(Path(parts_dir).glob("*.stl"))]
    s, cx, top, zt = SIDE["s"], SIDE["cx"], SIDE["top"], SIDE["ztop"]
    draw(parts, lambda m: [[(cx + v[0] * s, top + (zt - v[2]) * s) for v in t] for t in m],
         lambda m: -m[:, :, 1].mean(), out / "blueprint_side.png")      # far (large y) first
    s, cx, cy = PLAN["s"], PLAN["cx"], PLAN["cy"]
    draw(parts, lambda m: [[(cx + v[0] * s, cy - v[1] * s) for v in t] for t in m],
         lambda m: m[:, :, 2].mean(), out / "blueprint_plan.png")       # low z first
    print("wrote", out)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
