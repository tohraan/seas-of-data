"""Classical CFAR ship detector (baseline + sanity check for the YOLO model). Writes the same raw JSON as infer.py.
Usage: .venv/bin/python cfar.py <scene.tiff> --out runs/cfar_x.json --center LON LAT --radius-km 40 [--k 6]
Background mean/std are estimated from open-water pixels only (Otsu split), so quays and buildings do not raise the threshold.
"""
import argparse, json, math
from pathlib import Path
import numpy as np, rasterio
from rasterio.transform import GCPTransformer
from rasterio.windows import Window
from scipy import ndimage as ndi
from infer import geo_sea

ap = argparse.ArgumentParser()
ap.add_argument("scene"); ap.add_argument("--out", required=True)
ap.add_argument("--center", type=float, nargs=2, required=True); ap.add_argument("--radius-km", type=float, default=40)
ap.add_argument("--k", type=float, default=6.0); ap.add_argument("--win", type=int, default=61)
ap.add_argument("--min-px", type=int, default=3); ap.add_argument("--max-m", type=float, default=450)
ap.add_argument("--scene-id", default=None)
a = ap.parse_args()

with rasterio.open(a.scene) as ds:
    tr = GCPTransformer(ds.gcps[0])
    (l0, a0), (l1, a1) = tr.xy(0, 0), tr.xy(0, 1000)
    mpp = math.hypot((l1 - l0) * 111320 * math.cos(math.radians(a0)), (a1 - a0) * 110540) / 1000
    r0, c0 = tr.rowcol(*a.center); half = int(a.radius_km * 1000 / mpp)
    X0, X1, Y0, Y1 = max(0, int(c0) - half), min(ds.width, int(c0) + half), max(0, int(r0) - half), min(ds.height, int(r0) + half)
    raw = ds.read(1, window=Window(X0, Y0, X1 - X0, Y1 - Y0)).astype("float32")
    in_sea, water_full = geo_sea(ds, X0, X1, Y0, Y1)
db = 20 * np.log10(np.maximum(raw, 1.0))
valid = raw > 0
water = np.zeros(raw.shape, bool)
hh, ww = min(raw.shape[0], water_full.shape[0]), min(raw.shape[1], water_full.shape[1])
water[:hh, :ww] = water_full[:hh, :ww]
water &= valid
p99 = np.percentile(db[water], 99)          # ships and sea spikes must not inflate their own background estimate
stat = water & (db < p99)
f = lambda x: ndi.uniform_filter(x, a.win, mode="constant")
frac = f(water.astype("float32"))
fs = np.maximum(f(stat.astype("float32")), 1e-6)
mu = f(np.where(stat, db, 0)) / fs
var = f(np.where(stat, db * db, 0)) / fs - mu ** 2
sd = np.sqrt(np.maximum(var, 0.25))  # floor: never let sd collapse in featureless water
z = (db - mu) / sd
cand = (z > a.k) & (frac > 0.6) & valid
cand = ndi.binary_closing(cand, iterations=1)
lab, n = ndi.label(cand)
dets = []
for i, sl in enumerate(ndi.find_objects(lab), 1):
    area = int((lab[sl] == i).sum())
    h, wd = sl[0].stop - sl[0].start, sl[1].stop - sl[1].start
    length = max(h, wd) * mpp
    if area < a.min_px or length > a.max_m:
        continue
    y0, y1, x0, x1 = sl[0].start, sl[0].stop, sl[1].start, sl[1].stop
    cx, cy = X0 + (x0 + x1) / 2, Y0 + (y0 + y1) / 2
    lon, lat = tr.xy(cy, cx)
    zmax = float(z[sl][lab[sl] == i].max())
    dets.append({"box_px": [X0 + x0 - 2, Y0 + y0 - 2, X0 + x1 + 2, Y0 + y1 + 2], "confidence": round(min(1.0, zmax / 20), 3),
                 "lon": float(lon), "lat": float(lat), "length_m": round(length, 1)})
n_all = len(dets)  # keep only returns inside the sea mask (drops buildings, desert glints, island structures)
dets = [d for d in dets if in_sea((d["box_px"][0] + d["box_px"][2]) / 2, (d["box_px"][1] + d["box_px"][3]) / 2)]
merged = []  # one structure often fragments into several blobs: merge returns closer than 150 m, keep the strongest
for d in sorted(dets, key=lambda d: -d["confidence"]):
    if all(math.hypot((d["lon"] - m["lon"]) * 111320 * math.cos(math.radians(d["lat"])), (d["lat"] - m["lat"]) * 110540) > 150 for m in merged):
        merged.append(d)
dets = merged
print(f"sea mask + merge kept {len(dets)} of {n_all}")
Path(a.out).parent.mkdir(parents=True, exist_ok=True)
Path(a.out).write_text(json.dumps({"scene_id": a.scene_id or Path(a.scene).stem, "timestamp": None, "detections": dets}, indent=1))
print(f"{len(dets)} CFAR detections (k={a.k}, static sea mask) -> {a.out}")
