"""Detect ships in a Sentinel-1 GRD GeoTIFF (or any georeferenced SAR GeoTIFF) and write raw detections.

Usage:
  .venv/bin/python infer.py <scene.tiff> --weights models/best.pt --out runs/detections_raw.json \
      [--scene-id S1A_...] [--timestamp 2026-10-20T02:14:00Z] [--conf 0.25]

Output JSON: {"scene_id", "timestamp", "detections": [{"lon","lat","confidence","box_px":[x0,y0,x1,y1],"length_m"}]}
Works on Sentinel-1 SAFE measurement tiffs (georeferenced by GCPs) and on normal affine-georeferenced tiffs.
"""
import argparse
import json
import math
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from rasterio.transform import GCPTransformer, xy
from rasterio.windows import Window

TILE, STRIDE = 800, 640  # HRSID images are 800 px; overlap so ships on tile edges are not cut


def scene_window(ds):
    """Per-scene log-amplitude stretch (robust percentiles) from a decimated read, so tiles are comparable."""
    ov = ds.read(1, out_shape=(min(ds.height, 2000), min(ds.width, 2000))).astype("float32")
    v = 20 * np.log10(np.maximum(ov[ov > 0], 1.0))
    return float(np.percentile(v, 2)), float(np.percentile(v, 99.95))


def water_threshold(ds):
    """Otsu split of the scene's dB histogram: below = open water, above = land/structures."""
    ov = ds.read(1, out_shape=(min(ds.height, 2000), min(ds.width, 2000))).astype("float32")
    v = 20 * np.log10(np.maximum(ov[ov > 0], 1.0))
    hist, edges = np.histogram(v, bins=256)
    p = hist / hist.sum()
    w0, mu = np.cumsum(p), np.cumsum(p * (edges[:-1] + edges[1:]) / 2)
    sb = (mu[-1] * w0 - mu) ** 2 / np.maximum(w0 * (1 - w0), 1e-9)
    return float(edges[int(np.argmax(sb))])


def on_open_water(ds, box, thr, min_dark=0.4):
    """Context test: enough of the ring around the box must be dark water. Drops land and building returns;
    ships alongside a quay keep a partly dark ring and survive."""
    x0, y0, x1, y1 = box
    m = max(x1 - x0, y1 - y0)
    pad = int(max(30, 1.5 * m))
    X0, Y0 = max(0, int(x0) - pad), max(0, int(y0) - pad)
    X1, Y1 = min(ds.width, int(x1) + pad), min(ds.height, int(y1) + pad)
    a = ds.read(1, window=Window(X0, Y0, X1 - X0, Y1 - Y0)).astype("float32")
    db = 20 * np.log10(np.maximum(a, 1.0))
    ring = np.ones(a.shape, bool)
    ring[int(y0) - Y0:int(y1) - Y0 + 1, int(x0) - X0:int(x1) - X0 + 1] = False
    valid = ring & (a > 0)
    return valid.sum() > 0 and float((db[valid] < thr).mean()) >= min_dark


def sea_model(ds, x0, x1, y0, y1, f=8, margin_m=160):
    """Sea mask for a pixel window. Sea backscatter is far below land and desert, so: threshold = darkest 10% + 6 dB,
    keep the single largest connected dark region (the sea), fill ship-sized holes, dilate by margin_m so quayside ships count.
    Returns (threshold_dB, in_sea(x, y) in full-res pixel coords)."""
    from scipy import ndimage as ndi
    h, w = (y1 - y0) // f, (x1 - x0) // f
    a = ds.read(1, window=Window(x0, y0, w * f, h * f), out_shape=(h, w)).astype("float32")
    db = ndi.uniform_filter(20 * np.log10(np.maximum(a, 1.0)), 3)
    valid = a > 0
    thr = float(np.percentile(db[valid], 10)) + 6.0
    lab, n = ndi.label((db < thr) & valid)
    sizes = ndi.sum(np.ones_like(lab), lab, range(1, n + 1))
    sea = lab == (1 + int(np.argmax(sizes)))
    sea = ndi.binary_closing(sea, iterations=2)
    sea = ndi.binary_dilation(sea, iterations=max(1, int(margin_m / (f * 10))))
    def in_sea(x, y):
        i, j = int((y - y0) / f), int((x - x0) / f)
        return 0 <= i < h and 0 <= j < w and bool(sea[i, j])
    in_sea.mask, in_sea.f = sea, f
    return thr, in_sea


GEO_MASK = Path(__file__).parent / "assets" / "sea_mask.npz"


def geo_sea(ds, x0, x1, y0, y1, f=8):
    """Static land/sea mask in lon/lat (built once from a calm-sea scene by build_sea_mask.py), applied to any scene.
    Needed because wind-roughened sea can be as bright as desert, so brightness alone cannot find the coastline.
    Returns (in_sea(x, y) in full-res pixel coords, water: boolean full-res array for the window)."""
    m = np.load(GEO_MASK)
    lon0, lat0, res, grid = float(m["lon0"]), float(m["lat0"]), float(m["res"]), m["mask"]
    tr = GCPTransformer(ds.gcps[0])
    h, w = (y1 - y0) // f, (x1 - x0) // f
    rows, cols = np.meshgrid(y0 + (np.arange(h) + 0.5) * f, x0 + (np.arange(w) + 0.5) * f, indexing="ij")
    lon, lat = tr.xy(rows.ravel(), cols.ravel())
    i = np.floor((np.asarray(lat) - lat0) / res).astype(int)
    j = np.floor((np.asarray(lon) - lon0) / res).astype(int)
    ok = (i >= 0) & (i < grid.shape[0]) & (j >= 0) & (j < grid.shape[1])
    coarse = np.zeros(h * w, bool)
    coarse[ok] = grid[i[ok], j[ok]]
    coarse = coarse.reshape(h, w)

    def in_sea(x, y):
        a, b = int((y - y0) / f), int((x - x0) / f)
        return 0 <= a < h and 0 <= b < w and bool(coarse[a, b])

    water = np.repeat(np.repeat(coarse, f, 0), f, 1)
    return in_sea, water


MAX_SHIP_M = 450  # nothing afloat is longer; longer "ships" are piers, breakwaters or building rows


def to_uint8(a, lo, hi):
    db = 20 * np.log10(np.maximum(a.astype("float32"), 1.0))
    return np.clip((db - lo) / (hi - lo) * 255, 0, 255).astype("uint8")


def iou(a, b):
    ix0, iy0, ix1, iy1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, ix1 - ix0) * max(0, iy1 - iy0)
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0


def nms(dets, thr=0.4):
    dets = sorted(dets, key=lambda d: -d["confidence"])
    keep = []
    for d in dets:
        if all(iou(d["box_px"], k["box_px"]) < thr for k in keep):
            keep.append(d)
    return keep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scene")
    ap.add_argument("--weights", default="models/best.pt")
    ap.add_argument("--out", default="runs/detections_raw.json")
    ap.add_argument("--scene-id", default=None)
    ap.add_argument("--timestamp", default=None)
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--device", default="mps")
    ap.add_argument("--center", type=float, nargs=2, metavar=("LON", "LAT"), help="only scan around this point")
    ap.add_argument("--radius-km", type=float, default=30)
    ap.add_argument("--scale", type=float, default=3.0, help="upsample factor applied to each tile before the model")
    args = ap.parse_args()

    from ultralytics import YOLO

    model = YOLO(args.weights)
    dets = []
    with rasterio.open(args.scene) as ds:
        H, W = ds.height, ds.width
        gcps = ds.gcps[0] if ds.gcps and ds.gcps[0] else None
        tr = GCPTransformer(gcps) if gcps else None
        # approximate pixel size in metres from GCP spacing or affine
        if tr is not None:
            (l0, a0), (l1, a1) = tr.xy(0, 0), tr.xy(0, 1000)
            m_per_px = math.hypot((l1 - l0) * 111320 * math.cos(math.radians(a0)), (a1 - a0) * 110540) / 1000
        else:
            m_per_px = abs(ds.transform.a) * (111320 if ds.crs and ds.crs.is_geographic else 1)
        lo, hi = scene_window(ds)
        x0, x1, y0, y1 = 0, W, 0, H
        if args.center and tr is not None:  # limit to a square around a point, e.g. a port
            r0, c0 = tr.rowcol(args.center[0], args.center[1])
            half = int(args.radius_km * 1000 / m_per_px)
            x0, x1 = max(0, int(c0) - half), min(W, int(c0) + half)
            y0, y1 = max(0, int(r0) - half), min(H, int(r0) + half)
            print(f"window x {x0}-{x1}, y {y0}-{y1} (scene {W}x{H})")
        tile, stride = int(TILE / args.scale), int(STRIDE / args.scale)
        for y in range(y0, y1, stride):
            for x in range(x0, x1, stride):
                w, h = min(tile, W - x), min(tile, H - y)
                if w < 64 or h < 64:
                    continue
                a = ds.read(1, window=Window(x, y, w, h))
                if a.max() == 0:  # no-data border
                    continue
                img = np.stack([to_uint8(a, lo, hi)] * 3, -1)
                if args.scale != 1:  # Sentinel-1 pixels are ~10 m, HRSID's ~3 m: upsample so ships look the size the model learned
                    img = np.asarray(Image.fromarray(img).resize((int(w * args.scale), int(h * args.scale)), Image.BICUBIC))
                r = model.predict(img, imgsz=640, conf=args.conf, device=args.device, verbose=False)[0]
                for b, c in zip(r.boxes.xyxy.cpu().numpy(), r.boxes.conf.cpu().numpy()):
                    sx, sy = w / r.orig_shape[1], h / r.orig_shape[0]
                    box = [x + b[0] * sx, y + b[1] * sy, x + b[2] * sx, y + b[3] * sy]
                    dets.append({"box_px": [float(v) for v in box], "confidence": float(c)})
        dets = nms(dets)
        for d in dets:
            cx, cy = (d["box_px"][0] + d["box_px"][2]) / 2, (d["box_px"][1] + d["box_px"][3]) / 2
            lon, lat = tr.xy(cy, cx) if tr is not None else xy(ds.transform, cy, cx)
            d["lon"], d["lat"] = float(lon), float(lat)
            d["length_m"] = round(max(d["box_px"][2] - d["box_px"][0], d["box_px"][3] - d["box_px"][1]) * m_per_px, 1)
        n_all = len(dets)
        thr, in_sea = sea_model(ds, x0, x1, y0, y1)
        dets = [d for d in dets if d["length_m"] <= MAX_SHIP_M
                and in_sea((d["box_px"][0] + d["box_px"][2]) / 2, (d["box_px"][1] + d["box_px"][3]) / 2)]
        print(f"sea mask (water < {thr:.1f} dB, length <= {MAX_SHIP_M} m): kept {len(dets)} of {n_all}")

    out = {"scene_id": args.scene_id or Path(args.scene).stem, "timestamp": args.timestamp, "detections": dets}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=1))
    print(f"{len(dets)} ships -> {args.out}")


if __name__ == "__main__":
    main()
