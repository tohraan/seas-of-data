"""Run the trained YOLO model on the real Sentinel-1 passes behind the contract detections.

Run from dashboard/pipeline:
  uv run python yolo_scan.py --weights ../../data/model/best.pt --out ../../data/yolo_runs

Image preparation matches ml/infer.py, so results stay comparable: the same tiles, stretch and 3x upsampling.
The final land filter is the static sea mask that ml/cfar.py uses, so both detectors see exactly the same water.
"""
import argparse
import json
import time
from pathlib import Path

import numpy as np
from PIL import Image
from sentinel import SeaMask, find_product, read_scene, signed_url, to_uint8
from ultralytics import YOLO

CONTRACT = Path(__file__).resolve().parents[2] / "contracts" / "detections.geojson"
TILE_PX, STRIDE_PX = 800, 640
UPSCALE = 3.0
MODEL_INPUT_PX = 640
# Saved lower than the 0.25 the dashboard uses, so the threshold can be studied without scanning again.
CONFIDENCE_FLOOR = 0.10
NMS_OVERLAP = 0.4
MAX_SHIP_M = 450
MASK_STEP_PX = 8


def contract_scene_ids(path: Path = CONTRACT) -> list[str]:
    features = json.loads(path.read_text())["features"]
    return sorted({feature["properties"]["scene_id"] for feature in features})


def overlap(a: list[float], b: list[float]) -> float:
    x0, y0, x1, y1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    shared = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - shared
    return shared / union if union > 0 else 0.0


def suppress_duplicates(detections: list[dict]) -> list[dict]:
    """Tiles overlap, so the same ship can appear twice: keep the strongest box."""
    kept: list[dict] = []
    for detection in sorted(detections, key=lambda d: -d["confidence"]):
        if all(overlap(detection["box_px"], other["box_px"]) < NMS_OVERLAP for other in kept):
            kept.append(detection)
    return kept


def water_grid(scene, mask: SeaMask) -> np.ndarray:
    height, width = scene.pixels.shape
    rows, cols = np.meshgrid(
        (np.arange(height // MASK_STEP_PX) + 0.5) * MASK_STEP_PX,
        (np.arange(width // MASK_STEP_PX) + 0.5) * MASK_STEP_PX,
        indexing="ij",
    )
    lon, lat = scene.to_lonlat(rows.ravel(), cols.ravel())
    return mask.contains(lon, lat).reshape(rows.shape)


def scan(model, scene, mask: SeaMask, device: str) -> tuple[list[dict], int, int]:
    tile, stride = int(TILE_PX / UPSCALE), int(STRIDE_PX / UPSCALE)
    low, high = scene.stretch
    height, width = scene.pixels.shape
    water = water_grid(scene, mask)
    raw: list[dict] = []
    scanned = skipped = 0
    for y in range(0, height, stride):
        for x in range(0, width, stride):
            w, h = min(tile, width - x), min(tile, height - y)
            if w < 64 or h < 64:
                continue
            block = water[y // MASK_STEP_PX : (y + h) // MASK_STEP_PX + 1, x // MASK_STEP_PX : (x + w) // MASK_STEP_PX + 1]
            pixels = scene.pixels[y : y + h, x : x + w]
            if not block.any() or pixels.max() == 0:  # land or outside the mask: the filter would drop it anyway
                skipped += 1
                continue
            image = np.stack([to_uint8(pixels, low, high)] * 3, -1)
            image = np.asarray(Image.fromarray(image).resize((int(w * UPSCALE), int(h * UPSCALE)), Image.BICUBIC))
            result = model.predict(image, imgsz=MODEL_INPUT_PX, conf=CONFIDENCE_FLOOR, device=device, verbose=False)[0]
            scanned += 1
            scale_x, scale_y = w / result.orig_shape[1], h / result.orig_shape[0]
            for box, confidence in zip(result.boxes.xyxy.cpu().numpy(), result.boxes.conf.cpu().numpy()):
                raw.append({
                    "box_px": [
                        float(x + box[0] * scale_x), float(y + box[1] * scale_y),
                        float(x + box[2] * scale_x), float(y + box[3] * scale_y),
                    ],
                    "confidence": float(confidence),
                })
    detections = suppress_duplicates(raw)
    kept = []
    for detection in detections:
        x0, y0, x1, y1 = detection["box_px"]
        length = max(x1 - x0, y1 - y0) * scene.metres_per_pixel
        lon, lat = scene.to_lonlat(np.array([(y0 + y1) / 2]), np.array([(x0 + x1) / 2]))
        if length <= MAX_SHIP_M and mask.contains(lon, lat)[0]:
            kept.append({**detection, "lon": float(lon[0]), "lat": float(lat[0]), "length_m": round(float(length), 1)})
    return kept, scanned, skipped


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weights", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--scenes", nargs="*", help="contract scene IDs; defaults to every pass in the contract")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--force", action="store_true", help="scan again even if a result already exists")
    args = parser.parse_args()

    model = YOLO(str(args.weights))
    mask = SeaMask.load()
    args.out.mkdir(parents=True, exist_ok=True)
    for scene_id in args.scenes or contract_scene_ids():
        target = args.out / f"{scene_id}.json"
        if target.exists() and not args.force:
            print(f"{scene_id}: already scanned, skipping", flush=True)
            continue
        started = time.time()
        product = find_product(scene_id)
        scene = read_scene(signed_url(product, "vv"), mask.bounds)
        read_seconds = time.time() - started
        print(f"{scene_id}: read {scene.pixels.shape} in {read_seconds:.0f}s, {scene.metres_per_pixel:.2f} m/px", flush=True)
        detections, scanned, skipped = scan(model, scene, mask, args.device)
        target.write_text(json.dumps({
            "scene_id": scene_id,
            "product_id": product["id"],
            "timestamp": product["properties"].get("datetime"),
            "weights": args.weights.name,
            "confidence_floor": CONFIDENCE_FLOOR,
            "tiles_scanned": scanned,
            "tiles_skipped": skipped,
            "seconds": round(time.time() - started),
            "detections": detections,
        }, indent=1))
        counts = sum(detection["confidence"] >= 0.25 for detection in detections)
        print(
            f"{scene_id}: {scanned} tiles scanned, {skipped} skipped, {len(detections)} boxes "
            f"({counts} at 0.25 or above) in {time.time() - started:.0f}s -> {target}",
            flush=True,
        )


if __name__ == "__main__":
    main()
