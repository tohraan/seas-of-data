"""Draw detections on a downsampled view of a scene window, for eyeballing.
Usage: .venv/bin/python overlay.py <scene.tiff> <raw.json> <out.png> [--x0 --x1 --y0 --y1]  (pixel window; default = bbox of detections +/- margin)
"""
import argparse, json
import numpy as np, rasterio
from PIL import Image, ImageDraw
from rasterio.windows import Window
from infer import scene_window, to_uint8

ap = argparse.ArgumentParser()
ap.add_argument("scene"); ap.add_argument("raw"); ap.add_argument("out")
ap.add_argument("--x0", type=int); ap.add_argument("--x1", type=int); ap.add_argument("--y0", type=int); ap.add_argument("--y1", type=int)
ap.add_argument("--max", type=int, default=2000)
a = ap.parse_args()
dets = json.load(open(a.raw))["detections"]
with rasterio.open(a.scene) as ds:
    lo, hi = scene_window(ds)
    if a.x0 is None:
        xs = [(d["box_px"][0] + d["box_px"][2]) / 2 for d in dets]; ys = [(d["box_px"][1] + d["box_px"][3]) / 2 for d in dets]
        a.x0, a.x1, a.y0, a.y1 = max(0, int(min(xs)) - 500), min(ds.width, int(max(xs)) + 500), max(0, int(min(ys)) - 500), min(ds.height, int(max(ys)) + 500)
    w, h = a.x1 - a.x0, a.y1 - a.y0
    s = min(1.0, a.max / max(w, h))
    arr = ds.read(1, window=Window(a.x0, a.y0, w, h), out_shape=(int(h * s), int(w * s)))
img = Image.fromarray(to_uint8(arr, lo, hi)).convert("RGB")
dr = ImageDraw.Draw(img)
for d in dets:
    b = d["box_px"]; cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    if a.x0 <= cx <= a.x1 and a.y0 <= cy <= a.y1:
        x, y = (cx - a.x0) * s, (cy - a.y0) * s
        dr.ellipse([x - 14, y - 14, x + 14, y + 14], outline=(240, 169, 59), width=3)
img.save(a.out); print(a.out, img.size, "window", a.x0, a.x1, a.y0, a.y1)
