"""Save a light radar image of each whole scene, so the map shows real radar well beyond the study area.

Run from dashboard/pipeline:
  uv run python build_wide_radar.py

Writes ../derived/radar_wide/*.webp and ../derived/wide_radar.json. Needs neither the model nor a login.
"""
import io
import json
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from rasterio.enums import Resampling
from rasterio.transform import GCPTransformer

from sentinel import (
    amplitude_db,
    contract_scene_ids,
    distance_m,
    find_product,
    signed_url,
)

OUTPUT = Path(__file__).resolve().parent.parent / "derived"
FACTOR = 16  # about 160 m per pixel: enough for coastlines and sea state, not for individual ships
QUALITY = 50


def corner_mapping_error(transformer: GCPTransformer, corners: list[list[float]], height: int, width: int) -> np.ndarray:
    """How far the map's four-corner stretch puts points from where the scene's own ground control points say they are."""
    bottom_left, top_left, top_right, bottom_right = (np.array(corner) for corner in corners)
    errors = []
    for v in np.linspace(0, 1, 7):
        for u in np.linspace(0, 1, 7):
            stretched = (1 - u) * (1 - v) * top_left + u * (1 - v) * top_right + u * v * bottom_right + (1 - u) * v * bottom_left
            lon, lat = transformer.xy(v * height, u * width)
            errors.append(distance_m(float(stretched[0]), float(stretched[1]), lon, lat))
    return np.array(errors)


def main() -> None:
    (OUTPUT / "radar_wide").mkdir(parents=True, exist_ok=True)
    scenes = {}
    for scene_id in contract_scene_ids():
        product = find_product(scene_id)
        with rasterio.open(signed_url(product, "vv")) as source:
            height, width = source.height, source.width
            reduced = source.read(1, out_shape=(height // FACTOR, width // FACTOR), resampling=Resampling.average)
            transformer = GCPTransformer(source.gcps[0])
        valid = reduced > 0
        levels = amplitude_db(reduced[valid])
        low, high = float(np.percentile(levels, 2)), float(np.percentile(levels, 99.95))
        grey = np.clip((amplitude_db(reduced) - low) / (high - low) * 255, 0, 255).astype("uint8")
        # The scene's slanted no-data edges become see-through rather than black wedges.
        image = Image.fromarray(np.dstack([grey, (valid * 255).astype("uint8")]), "LA").convert("RGBA")
        buffer = io.BytesIO()
        image.save(buffer, "WEBP", quality=QUALITY, method=6)
        relative = f"radar_wide/{scene_id}.webp"
        (OUTPUT / relative).write_bytes(buffer.getvalue())
        lon, lat = transformer.xy(np.array([height, 0, 0, height]), np.array([0, 0, width, width]))
        corners = [[round(float(x), 6), round(float(y), 6)] for x, y in zip(lon, lat)]
        errors = corner_mapping_error(transformer, corners, height, width)
        scenes[scene_id] = {"image": relative, "corners": corners, "product": product["id"]}
        print(f"{scene_id}: {image.size[0]}x{image.size[1]}, {len(buffer.getvalue()) // 1024} KB, corner error median {np.median(errors):.0f} m, max {errors.max():.0f} m", flush=True)
    (OUTPUT / "wide_radar.json").write_text(json.dumps({"scenes": scenes}, indent=1))


if __name__ == "__main__":
    main()
