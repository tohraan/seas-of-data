"""Classical CFAR ship detector (baseline + sanity check for the YOLO model). Writes the same raw JSON as infer.py.
Usage: .venv/bin/python cfar.py <scene.tiff> --out runs/cfar_x.json --center LON LAT --radius-km 40 [--k 6] [--k-grow 5]
With --k-grow below --k, hysteresis adds weak targets: blobs grown over z > k_grow that hold a seed pixel z > k and no k-pass
detection. Every k-pass detection is kept unchanged, so ids and review verdicts stay valid.
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
ap.add_argument("--k-grow", type=float, default=None, help="hysteresis grow threshold (default: same as --k, no hysteresis)")
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
k_grow = a.k if a.k_grow is None else min(a.k_grow, a.k)


def blobs(cand):
    """Size-filtered blobs of a candidate mask -> (detections, label image, labels kept)."""
    lab, n = ndi.label(cand)
    out, kept = [], []
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
        out.append({"box_px": [X0 + x0 - 2, Y0 + y0 - 2, X0 + x1 + 2, Y0 + y1 + 2], "confidence": round(min(1.0, zmax / 20), 3),
                    "lon": float(lon), "lat": float(lat), "length_m": round(length, 1)})
        kept.append(i)
    return out, lab, n, kept


def sea_merge(dets, merged):
    """Keep returns inside the sea mask (drops buildings, desert glints, island structures), then merge returns closer than
    150 m to anything already kept (one structure often fragments into several blobs), strongest first."""
    sea = [d for d in dets if in_sea((d["box_px"][0] + d["box_px"][2]) / 2, (d["box_px"][1] + d["box_px"][3]) / 2)]
    for d in sorted(sea, key=lambda d: -d["confidence"]):
        if all(math.hypot((d["lon"] - m["lon"]) * 111320 * math.cos(math.radians(d["lat"])), (d["lat"] - m["lat"]) * 110540) > 150 for m in merged):
            merged.append(d)
    return len(sea)


cand = ndi.binary_closing((z > a.k) & (frac > 0.6) & valid, iterations=1)
dets, lab, n, kept = blobs(cand)
n_all = len(dets)
merged = []
n_sea = sea_merge(dets, merged)
n_grown = 0
if k_grow < a.k:  # additive hysteresis: weak targets whose seed blob was too small grow over z > k_grow; seed-pass detections stay as they are
    grow = ndi.binary_closing((z > k_grow) & (frac > 0.6) & valid, iterations=1)
    glab, _ = ndi.label(grow)
    seeds = np.unique(glab[(z > a.k) & grow])
    taken = np.unique(glab[np.isin(lab, kept)])   # grown blobs that hold a seed-pass detection: that target is already in
    grown, _, _, _ = blobs(np.isin(glab, np.setdiff1d(seeds[seeds > 0], taken)))
    before = len(merged)
    sea_merge(grown, merged)
    n_grown = len(merged) - before
print(f"sea mask + merge kept {len(merged)} ({n_grown} from hysteresis) of {n_all}")
stages = {"blobs_above_threshold": int(n), "after_size_filter": n_all, "after_sea_mask": n_sea, "after_merge": len(merged) - n_grown,
          "added_by_hysteresis": n_grown}
dets = merged
Path(a.out).parent.mkdir(parents=True, exist_ok=True)
Path(a.out).write_text(json.dumps({"scene_id": a.scene_id or Path(a.scene).stem, "timestamp": None,
                                  "params": {"k": a.k, "k_grow": k_grow, "win": a.win, "min_px": a.min_px, "max_m": a.max_m, "center": a.center, "radius_km": a.radius_km},
                                  "stages": stages, "detections": dets}, indent=1))
print(f"{len(dets)} CFAR detections (k={a.k}, k_grow={k_grow}, static sea mask) -> {a.out}")
