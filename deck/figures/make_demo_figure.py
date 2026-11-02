"""Radar crop of one real pass with detections coloured by AIS match (teal = matched, amber = dark; AIS is simulated).
Run with the ml venv:  ml/.venv/bin/python deck/figures/make_demo_figure.py
"""
import json, sys
from pathlib import Path
import numpy as np, rasterio
from PIL import Image, ImageDraw
from rasterio.transform import GCPTransformer
from rasterio.windows import Window

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ml"))
from infer import scene_window, to_uint8
import postprocess

scene = next((ROOT / "ml/data/scenes").glob("*20261102T021455*_vv.tiff"))
fc = json.loads((ROOT / "contracts/detections.geojson").read_text())["features"]
fc = [f for f in fc if f["properties"]["scene_id"].endswith("20261102T021455")]
X0, X1, Y0, Y1, OUT_W = 11200, 17400, 4600, 9600, 1700
with rasterio.open(scene) as ds:
    tr = GCPTransformer(ds.gcps[0])
    lo, hi = scene_window(ds)
    s = OUT_W / (X1 - X0)
    arr = ds.read(1, window=Window(X0, Y0, X1 - X0, Y1 - Y0), out_shape=(int((Y1 - Y0) * s), OUT_W))
    img = Image.fromarray(to_uint8(arr, lo, hi)).convert("RGB")
    d = ImageDraw.Draw(img)
    for name, p in postprocess.PORTS.items():
        x0, y0, x1, y1 = p["bbox"]
        pts = []
        for lon, lat in [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]:
            r, c = tr.rowcol(lon, lat)
            pts.append(((c - X0) * s, (r - Y0) * s))
        d.line(pts, fill=(143, 163, 181), width=2)
    n_m = n_d = 0
    for f in fc:
        lon, lat = f["geometry"]["coordinates"]
        r, c = tr.rowcol(lon, lat)
        x, y = (c - X0) * s, (r - Y0) * s
        if not (0 <= x < img.width and 0 <= y < img.height):
            continue
        dark = f["properties"]["dark"]
        col = (240, 169, 59) if dark else (63, 184, 166)
        d.ellipse([x - 15, y - 15, x + 15, y + 15], outline=col, width=4)
        n_d += dark; n_m += not dark
img.save(Path(__file__).parent / "demo_20261102.png")
print("saved", img.size, "matched", n_m, "dark", n_d)
