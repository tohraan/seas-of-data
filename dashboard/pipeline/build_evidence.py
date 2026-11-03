"""Build the dashboard's evidence files from real radar. Run yolo_scan.py first.

Run from dashboard/pipeline:
  uv run python build_evidence.py --weights ../../data/model/best.pt --runs ../../data/yolo_runs

Writes ../derived/evidence.json and ../derived/radar/*.webp, which are small enough to commit.
The model and the scenes are only needed here, not to run the dashboard.
"""
import argparse
import hashlib
import io
import json
import math
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from PIL import Image

from evidence_math import (
    MATCH_GATE_M,
    MIN_ELONGATION,
    bearing_deg,
    chip_data_uri,
    downsample_amplitude,
    local_contrast,
    match_detections,
    ship_shape,
)
from sentinel import Scene, SeaMask, amplitude_db, find_product, read_scene, signed_url

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "contracts" / "detections.geojson"
OUTPUT = Path(__file__).resolve().parent.parent / "derived"

YOLO_THRESHOLD = 0.25  # the default in ml/infer.py
SENSITIVITY_THRESHOLDS = [0.10, 0.15, 0.25, 0.35, 0.50, 0.70]
CONTROL_POINTS = 3000
CONTROL_CLEARANCE_M = 500
VH_CONFIRM_PERCENTILE = 99.0
PRESENT_PERCENTILE = 99.5
RADAR_IMAGE_FACTOR = 5
RADAR_IMAGE_QUALITY = 55
# A real pass over the same water that isn't in the contract: only used to test whether a target is always there.
EXTRA_PERSISTENCE_SCENES = ["S1D_20261021T021455"]


def control_contrasts(scene: Scene, mask: SeaMask, avoid: list[tuple[float, float]], seed: int) -> np.ndarray:
    """The same measurement at random open-water points, which tells us how bright sea clutter gets in this pass."""
    rng = np.random.default_rng(seed)
    height, width = scene.pixels.shape
    rows = rng.uniform(40, height - 40, CONTROL_POINTS * 6)
    cols = rng.uniform(40, width - 40, CONTROL_POINTS * 6)
    lon, lat = scene.to_lonlat(rows, cols)
    usable = mask.contains(lon, lat)
    contrasts: list[float] = []
    avoid_lon = np.array([p[0] for p in avoid]) if avoid else np.empty(0)
    avoid_lat = np.array([p[1] for p in avoid]) if avoid else np.empty(0)
    for row, col, point_lon, point_lat in zip(rows[usable], cols[usable], lon[usable], lat[usable]):
        if avoid_lon.size:
            dx = (avoid_lon - point_lon) * 111320 * math.cos(math.radians(point_lat))
            dy = (avoid_lat - point_lat) * 110540
            if np.hypot(dx, dy).min() < CONTROL_CLEARANCE_M:
                continue
        value = local_contrast(scene.pixels, row, col)
        if not math.isnan(value):
            contrasts.append(value)
        if len(contrasts) >= CONTROL_POINTS:
            break
    return np.array(contrasts)


def sea_median_db(scene: Scene, mask: SeaMask) -> float:
    step = 16
    rows, cols = np.meshgrid(np.arange(0, scene.pixels.shape[0], step), np.arange(0, scene.pixels.shape[1], step), indexing="ij")
    lon, lat = scene.to_lonlat(rows.ravel(), cols.ravel())
    sampled = scene.pixels[rows.ravel(), cols.ravel()]
    water = mask.contains(lon, lat) & (sampled > 0)
    return round(float(np.median(amplitude_db(sampled[water]))), 1)


def save_radar_image(scene: Scene, path: Path) -> list[list[float]]:
    """Save a lighter radar image and return its corners as bottom-left, top-left, top-right, bottom-right."""
    low, high = scene.stretch
    reduced = downsample_amplitude(scene.pixels, RADAR_IMAGE_FACTOR)
    image = np.clip((amplitude_db(reduced) - low) / (high - low) * 255, 0, 255).astype("uint8")
    buffer = io.BytesIO()
    Image.fromarray(image).save(buffer, "WEBP", quality=RADAR_IMAGE_QUALITY, method=6)
    path.write_bytes(buffer.getvalue())
    height = reduced.shape[0] * RADAR_IMAGE_FACTOR
    width = reduced.shape[1] * RADAR_IMAGE_FACTOR
    lon, lat = scene.to_lonlat(np.array([height, 0, 0, height]), np.array([0, 0, width, width]))
    return [[round(float(x), 6), round(float(y), 6)] for x, y in zip(lon, lat)]


def measure(vv: Scene, vh: Scene, lon: float, lat: float, vh_threshold: float) -> dict:
    row, col = vv.to_pixel(lon, lat)
    row, col = float(row), float(col)
    vv_contrast = local_contrast(vv.pixels, row, col)
    vh_contrast = local_contrast(vh.pixels, row, col)
    result = {
        "vv_contrast_db": None if math.isnan(vv_contrast) else round(vv_contrast, 1),
        "vh_contrast_db": None if math.isnan(vh_contrast) else round(vh_contrast, 1),
        "vh_confirmed": bool(not math.isnan(vh_contrast) and vh_contrast >= vh_threshold),
        "radar_length_m": None,
        "axis_deg": None,
        "chip_vv": chip_data_uri(vv.pixels, row, col, vv.stretch),
        "chip_vh": chip_data_uri(vh.pixels, row, col, vh.stretch),
    }
    shape = ship_shape(vv.pixels, row, col)
    if shape is not None:
        length_px, elongation, axis_row, axis_col = shape
        result["radar_length_m"] = round(length_px * vv.metres_per_pixel, 1)
        if elongation >= MIN_ELONGATION:
            lons, lats = vv.to_lonlat(np.array([row - 20 * axis_row, row + 20 * axis_row]), np.array([col - 20 * axis_col, col + 20 * axis_col]))
            result["axis_deg"] = round(bearing_deg(float(lons[0]), float(lats[0]), float(lons[1]), float(lats[1])), 1)
    return result


def model_card(weights: Path) -> dict:
    from ultralytics import YOLO

    model = YOLO(str(weights))
    checkpoint = model.ckpt
    arguments = checkpoint.get("train_args", {})
    validation = checkpoint.get("train_metrics", {})
    card = {
        "file": weights.name,
        "architecture": Path(str(arguments.get("model", "unknown"))).stem,
        "classes": list(model.names.values()),
        "trained_on": "HRSID" if "hrsid" in str(arguments.get("data", "")).lower() else str(arguments.get("data")),
        "epochs": arguments.get("epochs"),
        "image_size": arguments.get("imgsz"),
        "saved": str(checkpoint.get("date", ""))[:10],
        "ultralytics_version": checkpoint.get("version"),
        "license": checkpoint.get("license"),
        "best_validation": {
            "precision": validation.get("metrics/precision(B)"),
            "recall": validation.get("metrics/recall(B)"),
            "mAP50": validation.get("metrics/mAP50(B)"),
            "mAP50_95": validation.get("metrics/mAP50-95(B)"),
        },
    }
    del model
    return card


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weights", required=True, type=Path)
    parser.add_argument("--runs", required=True, type=Path)
    parser.add_argument("--out", default=OUTPUT, type=Path)
    args = parser.parse_args()

    card = model_card(args.weights)
    contract_bytes = CONTRACT.read_bytes()
    contract = json.loads(contract_bytes)["features"]
    scene_ids = sorted({feature["properties"]["scene_id"] for feature in contract})
    mask = SeaMask.load()
    (args.out / "radar").mkdir(parents=True, exist_ok=True)

    # Line up the two detectors first, so all passes can be tested against every target.
    cfar_by_scene, yolo_by_scene, pair_by_scene = {}, {}, {}
    next_yolo_id = 1
    targets: list[dict] = []
    for scene_id in scene_ids:
        cfar = [f for f in contract if f["properties"]["scene_id"] == scene_id]
        run = json.loads((args.runs / f"{scene_id}.json").read_text())
        yolo_all = run["detections"]
        yolo = sorted((d for d in yolo_all if d["confidence"] >= YOLO_THRESHOLD), key=lambda d: -d["confidence"])
        cfar_points = [tuple(f["geometry"]["coordinates"]) for f in cfar]
        yolo_points = [(d["lon"], d["lat"]) for d in yolo]
        pairs = match_detections(cfar_points, yolo_points)
        yolo_for_cfar = {i: j for i, j in pairs}
        matched_yolo = set(yolo_for_cfar.values())
        cfar_by_scene[scene_id], yolo_by_scene[scene_id], pair_by_scene[scene_id] = cfar, yolo, yolo_for_cfar
        sensitivity = {}
        for threshold in SENSITIVITY_THRESHOLDS:
            subset = [(d["lon"], d["lat"]) for d in yolo_all if d["confidence"] >= threshold]
            both = len(match_detections(cfar_points, subset))
            sensitivity[f"{threshold:.2f}"] = {"yolo": len(subset), "both": both}
        run["sensitivity"] = sensitivity
        for i, feature in enumerate(cfar):
            targets.append({
                "id": feature["properties"]["id"],
                "scene_id": scene_id,
                "lon": feature["geometry"]["coordinates"][0],
                "lat": feature["geometry"]["coordinates"][1],
                "detector": "both" if i in yolo_for_cfar else "cfar",
                "yolo_confidence": round(yolo[yolo_for_cfar[i]]["confidence"], 3) if i in yolo_for_cfar else None,
                "yolo_only": False,
            })
        for j, detection in enumerate(yolo):
            if j not in matched_yolo:
                targets.append({
                    "id": f"y{next_yolo_id:04d}",
                    "scene_id": scene_id,
                    "lon": round(detection["lon"], 6),
                    "lat": round(detection["lat"], 6),
                    "detector": "yolo",
                    "yolo_confidence": round(detection["confidence"], 3),
                    "length_m": detection["length_m"],
                    "timestamp": cfar[0]["properties"]["timestamp"] if cfar else run["timestamp"],
                    "yolo_only": True,
                })
                next_yolo_id += 1
        yolo_by_scene[scene_id] = {"run": run, "kept": yolo, "matched": len(pairs)}

    measured_passes = []
    present = {target["id"]: [] for target in targets}
    by_id = {target["id"]: target for target in targets}
    for seed, scene_id in enumerate(scene_ids + EXTRA_PERSISTENCE_SCENES):
        is_extra = scene_id not in scene_ids
        product = find_product(scene_id)
        vv = read_scene(signed_url(product, "vv"), mask.bounds)
        controls_vv = control_contrasts(vv, mask, [(t["lon"], t["lat"]) for t in targets if t["scene_id"] == scene_id], seed)
        present_threshold = float(np.percentile(controls_vv, PRESENT_PERCENTILE))
        for target in targets:
            row, col = vv.to_pixel(target["lon"], target["lat"])
            value = local_contrast(vv.pixels, float(row), float(col))
            if not math.isnan(value):
                present[target["id"]].append(bool(value >= present_threshold))
        if is_extra:
            print(f"{scene_id}: persistence only, threshold {present_threshold:.1f} dB", flush=True)
            del vv
            continue

        vh = read_scene(signed_url(product, "vh"), mask.bounds)
        controls_vh = control_contrasts(vh, mask, [(t["lon"], t["lat"]) for t in targets if t["scene_id"] == scene_id], seed + 100)
        vh_threshold = float(np.percentile(controls_vh, VH_CONFIRM_PERCENTILE))
        for target in targets:
            if target["scene_id"] == scene_id:
                target.update(measure(vv, vh, target["lon"], target["lat"], vh_threshold))
                if not target["yolo_only"]:  # the contract already holds a VV chip for its own detections
                    del target["chip_vv"]
        corners = save_radar_image(vv, args.out / "radar" / f"{scene_id}.webp")

        cfar = cfar_by_scene[scene_id]
        info = yolo_by_scene[scene_id]
        here = [t for t in targets if t["scene_id"] == scene_id]
        measured_passes.append({
            "scene_id": scene_id,
            "product_id": product["id"],
            "timestamp": cfar[0]["properties"]["timestamp"],
            "orbit": product["properties"].get("sat:orbit_state"),
            "image": f"radar/{scene_id}.webp",
            "corners": corners,
            "cfar": len(cfar),
            "yolo": len(info["kept"]),
            "both": info["matched"],
            "cfar_only": len(cfar) - info["matched"],
            "yolo_only": len(info["kept"]) - info["matched"],
            "vh_confirmed": sum(t["vh_confirmed"] for t in here),
            "sea_median_db": sea_median_db(vv, mask),
            "vv_clutter_p99_db": round(float(np.percentile(controls_vv, 99)), 1),
            "vh_clutter_p99_db": round(vh_threshold, 1),
            "control_points": int(controls_vv.size),
            "tiles_scanned": info["run"]["tiles_scanned"],
            "sensitivity": info["run"]["sensitivity"],
        })
        print(
            f"{scene_id}: cfar {len(cfar)}, yolo {len(info['kept'])}, both {info['matched']}, "
            f"vh confirmed {measured_passes[-1]['vh_confirmed']} of {len(here)}, clutter p99 vh {vh_threshold:.1f} dB",
            flush=True,
        )
        del vv, vh

    for target_id, checks in present.items():
        target = by_id[target_id]
        target["passes_bright"] = sum(checks)
        target["passes_measured"] = len(checks)
        target["fixed_likely"] = len(checks) >= 4 and all(checks)

    evidence = {
        "schema": 1,
        "built_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "contract_sha256": hashlib.sha256(contract_bytes).hexdigest(),
        "source": "Copernicus Sentinel-1 GRD, read from the Microsoft Planetary Computer mirror",
        "model": card,
        "settings": {
            "yolo_threshold": YOLO_THRESHOLD,
            "match_gate_m": MATCH_GATE_M,
            "control_points_per_pass": CONTROL_POINTS,
            "vh_confirm_percentile": VH_CONFIRM_PERCENTILE,
            "present_percentile": PRESENT_PERCENTILE,
            "persistence_extra_scenes": EXTRA_PERSISTENCE_SCENES,
            "sea_mask_bounds": [round(v, 3) for v in mask.bounds],
        },
        "passes": measured_passes,
        "targets": targets,
    }
    (args.out / "evidence.json").write_text(json.dumps(evidence, separators=(",", ":")))
    size = (args.out / "evidence.json").stat().st_size / 1e6
    print(f"{len(targets)} targets across {len(measured_passes)} passes -> {args.out / 'evidence.json'} ({size:.1f} MB)", flush=True)


if __name__ == "__main__":
    main()
