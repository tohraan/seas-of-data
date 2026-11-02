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
from rasterio.transform import GCPTransformer, xy
from rasterio.windows import Window

TILE, STRIDE = 800, 640  # HRSID images are 800 px; overlap so ships on tile edges are not cut


def scene_window(ds):
    """Per-scene log-amplitude stretch (robust percentiles) from a decimated read, so tiles are comparable."""
    ov = ds.read(1, out_shape=(min(ds.height, 2000), min(ds.width, 2000))).astype("float32")
    v = 20 * np.log10(np.maximum(ov[ov > 0], 1.0))
    return float(np.percentile(v, 2)), float(np.percentile(v, 99.95))


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
        for y in range(0, H, STRIDE):
            for x in range(0, W, STRIDE):
                w, h = min(TILE, W - x), min(TILE, H - y)
                if w < 64 or h < 64:
                    continue
                a = ds.read(1, window=Window(x, y, w, h))
                if a.max() == 0:  # no-data border
                    continue
                img = np.stack([to_uint8(a, lo, hi)] * 3, -1)
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

    out = {"scene_id": args.scene_id or Path(args.scene).stem, "timestamp": args.timestamp, "detections": dets}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=1))
    print(f"{len(dets)} ships -> {args.out}")


if __name__ == "__main__":
    main()
