"""Raw detector output -> contracts (v2): detections.geojson, port_activity.json, chips/.

Usage: .venv/bin/python build_catalog.py runs/cfar_2026*T*.json [--scenes data/scenes] [--no-chips]

Every feature is a RADAR detection from a real Sentinel-1 scene. AIS is NOT joined here: status="not_checked",
ais_source="none", dark=null, until ml/ais/match.py has a real AIS source for that pass. Nothing is simulated.
Each detection gets a stable id (hash of scene + position), a radar chip (contracts/chips/<id>.png + _ctx.jpg),
its pixel box and the ESA product name, so a reader can verify it against the original scene.
"""
import argparse
import hashlib
import json
import math
import re
import statistics
from datetime import datetime, timezone
from pathlib import Path

import jsonschema
import numpy as np

from features import RULE, LandDistance, contrast_db, is_ship_like

ROOT = Path(__file__).resolve().parent.parent
CONTRACTS = ROOT / "contracts"
DETECTOR = "cfar-v1"
PERSIST_GATE_M = 150          # same spot in another pass within this distance = same place
CHIP, CTX_WIN, CTX_OUT = 128, 768, 256

# lon_min, lat_min, lon_max, lat_max (port + immediate approaches)
PORTS = {
    "Jebel Ali": (54.95, 24.97, 55.12, 25.08),
    "Khalifa Port": (54.55, 24.76, 54.75, 24.90),
}
SIZE_BANDS = [(30, "tiny"), (60, "small"), (120, "medium"), (200, "large"), (1e9, "very_large")]


def metres(lon1, lat1, lon2, lat2):
    return math.hypot((lon1 - lon2) * 111320 * math.cos(math.radians(lat1)), (lat1 - lat2) * 110540)


def in_port(lon, lat):
    for name, (x0, y0, x1, y1) in PORTS.items():
        if x0 <= lon <= x1 and y0 <= lat <= y1:
            return name
    return None


def size_class(length):
    if length is None:
        return None
    return next(name for top, name in SIZE_BANDS if length < top)


def scene_timestamp(scene_id):
    m = re.search(r"(\d{8})T(\d{6})", scene_id)
    return datetime.strptime("".join(m.groups()), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def detection_id(scene_id, lon, lat):
    """Stable across reruns: same scene + same position = same id."""
    h = hashlib.sha1(f"{scene_id}|{lon:.5f}|{lat:.5f}".encode()).hexdigest()[:6]
    return f"{scene_id[:3].lower()}-{scene_id[4:12]}-{h}"


def classify(d):
    """radar_class: ship | likely_fixed | uncertain. Tag, never delete: ships alongside quays legitimately repeat."""
    if d["persistence"] >= d["n_scenes"] and d["n_scenes"] >= 4:
        return "likely_fixed"          # bright at the same spot in every pass
    return "ship" if is_ship_like(d["contrast_db"], d["confidence"] * 20, d["land_m"]) else "uncertain"


def enrich(per_scene):
    allp = [(i, d) for i, (_, dets) in enumerate(per_scene) for d in dets]
    n = len(per_scene)
    for i, d in allp:
        seen = {j for j, e in allp if j != i and metres(d["lon"], d["lat"], e["lon"], e["lat"]) <= PERSIST_GATE_M}
        d["persistence"], d["n_scenes"] = 1 + len(seen), n
        d["radar_class"] = classify(d)


# ---------- chips ----------
def scene_path(scenes_dir, scene_id):
    m = re.search(r"(\d{8}T\d{6})", scene_id)
    hits = sorted(Path(scenes_dir).glob(f"{scene_id[:3]}*{m.group(1)}*_vv.tiff"))
    return hits[0] if hits else None


def scene_window(ds):
    ov = ds.read(1, out_shape=(min(ds.height, 2000), min(ds.width, 2000))).astype("float32")
    v = 20 * np.log10(np.maximum(ov[ov > 0], 1.0))
    return float(np.percentile(v, 2)), float(np.percentile(v, 99.95))


def crop_db(ds, cx, cy, size, lo, hi):
    """size x size window centred on (cx, cy), zero-padded at scene edges, stretched to 0..255."""
    from rasterio.windows import Window
    x0, y0 = int(cx) - size // 2, int(cy) - size // 2
    out = np.zeros((size, size), "float32")
    sx0, sy0, sx1, sy1 = max(0, x0), max(0, y0), min(ds.width, x0 + size), min(ds.height, y0 + size)
    if sx1 > sx0 and sy1 > sy0:
        out[sy0 - y0:sy1 - y0, sx0 - x0:sx1 - x0] = ds.read(1, window=Window(sx0, sy0, sx1 - sx0, sy1 - sy0)).astype("float32")
    db = 20 * np.log10(np.maximum(out, 1.0))
    return np.clip((db - lo) / (hi - lo), 0, 1) * 255, x0, y0


def ticks(img, x0, y0, bx, size, colour=(240, 169, 59), pad=7, arm=9):
    """Four corner ticks around the box (not a full outline, so the target stays visible)."""
    bx0, by0, bx1, by1 = bx
    l, t, r, b = bx0 - x0 - pad, by0 - y0 - pad, bx1 - x0 + pad, by1 - y0 + pad
    for (px, py, dx, dy) in [(l, t, 1, 1), (r, t, -1, 1), (l, b, 1, -1), (r, b, -1, -1)]:
        for k in range(arm):
            for (x, y) in [(px + dx * k, py), (px, py + dy * k)]:
                if 0 <= x < size and 0 <= y < size:
                    img[y, x] = colour


def write_chips(ds, lo, hi, d, out_dir):
    from PIL import Image
    x0b, y0b, x1b, y1b = d["box_px"]
    cx, cy = (x0b + x1b) / 2, (y0b + y1b) / 2
    g, ox, oy = crop_db(ds, cx, cy, CHIP, lo, hi)
    img = np.stack([g] * 3, -1).astype("uint8")
    ticks(img, ox, oy, d["box_px"], CHIP)
    Image.fromarray(img).save(out_dir / f"{d['id']}.png", optimize=True)
    g2, _, _ = crop_db(ds, cx, cy, CTX_WIN, lo, hi)
    im2 = Image.fromarray(g2.astype("uint8")).resize((CTX_OUT, CTX_OUT), Image.BOX).convert("RGB")
    px = np.array(im2)
    c = CTX_OUT // 2
    for k in range(-9, 10):
        for (x, y) in [(c + k, c - 9), (c + k, c + 9), (c - 9, c + k), (c + 9, c + k)]:
            px[y, x] = (240, 169, 59)
    Image.fromarray(px).save(out_dir / f"{d['id']}_ctx.jpg", quality=80)


def main():
    import rasterio
    ap = argparse.ArgumentParser()
    ap.add_argument("raw", nargs="+")
    ap.add_argument("--scenes", default=str(ROOT / "ml" / "data" / "scenes"))
    ap.add_argument("--no-chips", action="store_true")
    args = ap.parse_args()

    per_scene, meta = [], {}
    for path in sorted(args.raw, key=lambda p: re.search(r"(\d{8}T\d{6})", p).group(1)):
        raw = json.loads(Path(path).read_text())
        per_scene.append((raw["scene_id"], raw["detections"]))
        meta[raw["scene_id"]] = {"params": raw.get("params"), "stages": raw.get("stages")}

    chip_dir = CONTRACTS / "chips"
    if not args.no_chips:
        chip_dir.mkdir(parents=True, exist_ok=True)
        for old in chip_dir.glob("*"):
            old.unlink()
    land = LandDistance()
    products = {}
    for scene_id, dets in per_scene:      # pass 1: ids, radar features, chips (needs the scene file)
        sp = scene_path(args.scenes, scene_id)
        if sp is None:
            raise SystemExit(f"scene file for {scene_id} not found in {args.scenes}")
        products[scene_id] = sp.name.removesuffix("_vv.tiff") + ".SAFE"
        with rasterio.open(sp) as ds:
            lo, hi = scene_window(ds)
            for d in dets:
                d["id"] = detection_id(scene_id, d["lon"], d["lat"])
                d["contrast_db"] = round(contrast_db(ds, d["box_px"]), 1)
                d["land_m"] = land(d["lon"], d["lat"])
                if not args.no_chips:
                    write_chips(ds, lo, hi, d, chip_dir)
    enrich(per_scene)                      # pass 2: persistence + radar_class (needs every pass)

    features, rows = [], []
    for scene_id, dets in per_scene:
        ts = scene_timestamp(scene_id)
        for d in sorted(dets, key=lambda d: d["id"]):
            port = in_port(d["lon"], d["lat"])
            d["port"] = port
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [round(d["lon"], 6), round(d["lat"], 6)]},
                "properties": {
                    "id": d["id"], "scene_id": scene_id, "timestamp": ts, "product": products[scene_id],
                    "confidence": round(d["confidence"], 3), "snr_z": round(d["confidence"] * 20, 1),
                    "contrast_db": d["contrast_db"], "land_distance_m": None if d["land_m"] is None else round(d["land_m"]),
                    "length_m": d.get("length_m"), "size_class": size_class(d.get("length_m")),
                    "box_px": d["box_px"], "persistence": d["persistence"], "radar_class": d["radar_class"],
                    "ais_matched": False, "dark": None, "mmsi": None, "port": port,
                    "ais_source": "none", "status": "not_checked", "detector": DETECTOR, "review": "unreviewed",
                    "chip": f"chips/{d['id']}.png", "chip_context": f"chips/{d['id']}_ctx.jpg",
                },
            })
        for name in PORTS:
            inside = [d for d in dets if d["port"] == name]
            ships = [d for d in inside if d["radar_class"] == "ship"]
            by_size = {s: sum(1 for d in ships if size_class(d.get("length_m")) == s) for _, s in SIZE_BANDS}
            rows.append({"port": name, "date": ts[:10], "scene_id": scene_id, "vessel_count": len(ships),
                         "uncertain_count": sum(1 for d in inside if d["radar_class"] == "uncertain"),
                         "by_size": by_size, "basis": "radar_class=ship detections inside the port box (uncertain and likely_fixed excluded)"})
    for name in PORTS:  # baseline: count relative to the median of this port's passes (=100). Not a trend.
        mine = [r for r in rows if r["port"] == name]
        base = statistics.median(r["vessel_count"] for r in mine) or 1
        for r in mine:
            r["activity_index"] = round(100 * r["vessel_count"] / base, 1)

    fc = {"type": "FeatureCollection", "features": features}
    jsonschema.validate(fc, json.loads((CONTRACTS / "detections.schema.json").read_text()))
    (CONTRACTS / "detections.geojson").write_text(json.dumps(fc, indent=1))
    (CONTRACTS / "port_activity.json").write_text(json.dumps(rows, indent=1))
    (ROOT / "ml" / "reports" / "build_meta.json").write_text(json.dumps(
        {"detector": DETECTOR, "rule": RULE, "persist_gate_m": PERSIST_GATE_M, "products": products, "scenes": meta}, indent=1))
    from collections import Counter
    print(f"{len(features)} radar detections {dict(Counter(f['properties']['radar_class'] for f in features))}, "
          f"{len(rows)} port rows, AIS not checked -> {CONTRACTS}")


if __name__ == "__main__":
    main()
