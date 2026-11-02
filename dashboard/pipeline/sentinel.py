"""Read real Sentinel-1 GRD scenes from the public Microsoft Planetary Computer mirror. No login needed.

Scenes are cloud-optimised, so only the area around the ports is downloaded, not the whole file.
"""
import json
import math
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import GCPTransformer
from rasterio.windows import Window

STAC_SEARCH = "https://planetarycomputer.microsoft.com/api/stac/v1/search"
SIGN = "https://planetarycomputer.microsoft.com/api/sas/v1/sign?href="
COLLECTION = "sentinel-1-grd"
SEA_MASK = Path(__file__).resolve().parents[2] / "ml" / "assets" / "sea_mask.npz"

os.environ.update(
    GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
    GDAL_HTTP_MULTIRANGE="YES",
    GDAL_HTTP_MERGE_CONSECUTIVE_RANGES="YES",
    GDAL_HTTP_MAX_RETRY="5",
    GDAL_HTTP_RETRY_DELAY="2",
)


def _post_json(url: str, body: dict) -> dict:
    request = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=90) as response:
        return json.load(response)


def find_product(scene_id: str, lon: float = 54.875, lat: float = 24.925) -> dict:
    """Find the catalogue entry for a contract scene ID such as S1D_20261102T021455."""
    platform, start = scene_id.split("_")
    moment = datetime.strptime(start, "%Y%m%dT%H%M%S").replace(tzinfo=UTC)
    span = f"{moment - timedelta(minutes=2):%Y-%m-%dT%H:%M:%SZ}/{moment + timedelta(minutes=2):%Y-%m-%dT%H:%M:%SZ}"
    found = _post_json(STAC_SEARCH, {
        "collections": [COLLECTION],
        "intersects": {"type": "Point", "coordinates": [lon, lat]},
        "datetime": span,
        "limit": 10,
    })
    prefix = f"{platform}_IW_GRDH_1SDV_{start}"
    for feature in found["features"]:
        if feature["id"].startswith(prefix):
            return feature
    raise LookupError(f"{scene_id} is not in the {COLLECTION} catalogue")


def signed_url(product: dict, band: str) -> str:
    href = urllib.parse.quote(product["assets"][band]["href"], safe="")
    with urllib.request.urlopen(SIGN + href, timeout=90) as response:
        return json.load(response)["href"]


@dataclass
class SeaMask:
    lon0: float
    lat0: float
    res: float
    grid: np.ndarray

    @classmethod
    def load(cls, path: Path = SEA_MASK) -> "SeaMask":
        mask = np.load(path)
        return cls(float(mask["lon0"]), float(mask["lat0"]), float(mask["res"]), mask["mask"])

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        rows, cols = self.grid.shape
        return self.lon0, self.lat0, self.lon0 + cols * self.res, self.lat0 + rows * self.res

    def contains(self, lon, lat) -> np.ndarray:
        """True where the point is on the sea side of the mask. Points outside the mask's extent are False."""
        i = np.floor((np.asarray(lat, float) - self.lat0) / self.res).astype(int)
        j = np.floor((np.asarray(lon, float) - self.lon0) / self.res).astype(int)
        inside = (i >= 0) & (i < self.grid.shape[0]) & (j >= 0) & (j < self.grid.shape[1])
        result = np.zeros(i.shape, bool)
        result[inside] = self.grid[i[inside], j[inside]]
        return result


@dataclass
class Scene:
    """One band of one pass, cropped to the study area and held in memory."""

    pixels: np.ndarray
    x0: int
    y0: int
    transformer: GCPTransformer
    metres_per_pixel: float
    stretch: tuple[float, float]

    def to_lonlat(self, rows, cols):
        lon, lat = self.transformer.xy(np.asarray(rows) + self.y0, np.asarray(cols) + self.x0)
        return np.asarray(lon), np.asarray(lat)

    def to_pixel(self, lon, lat):
        rows, cols = self.transformer.rowcol(lon, lat)
        return np.asarray(rows, float) - self.y0, np.asarray(cols, float) - self.x0


def amplitude_db(pixels: np.ndarray) -> np.ndarray:
    return 20 * np.log10(np.maximum(pixels.astype("float32"), 1.0))


def to_uint8(pixels: np.ndarray, low: float, high: float) -> np.ndarray:
    return np.clip((amplitude_db(pixels) - low) / (high - low) * 255, 0, 255).astype("uint8")


def read_scene(url: str, bounds: tuple[float, float, float, float], margin_px: int = 64) -> Scene:
    lon_min, lat_min, lon_max, lat_max = bounds
    with rasterio.Env(GDAL_CACHEMAX=128), rasterio.open(url) as source:
        gcps = source.gcps[0]
        transformer = GCPTransformer(gcps)
        rows, cols = transformer.rowcol(
            [lon_min, lon_min, lon_max, lon_max],
            [lat_min, lat_max, lat_max, lat_min],
        )
        x0 = max(0, int(min(cols)) - margin_px)
        y0 = max(0, int(min(rows)) - margin_px)
        x1 = min(source.width, int(max(cols)) + margin_px)
        y1 = min(source.height, int(max(rows)) + margin_px)

        # The same robust stretch as ml/infer.py, taken across the whole scene so tiles are comparable.
        overview = source.read(1, out_shape=(min(source.height, 2000), min(source.width, 2000)))
        levels = amplitude_db(overview[overview > 0])
        stretch = float(np.percentile(levels, 2)), float(np.percentile(levels, 99.95))

        pixels = source.read(1, window=Window(x0, y0, x1 - x0, y1 - y0))
        (lon_a, lat_a), (lon_b, lat_b) = transformer.xy(0, 0), transformer.xy(0, 1000)
        metres = math.hypot((lon_b - lon_a) * 111320 * math.cos(math.radians(lat_a)), (lat_b - lat_a) * 110540) / 1000
    return Scene(pixels, x0, y0, GCPTransformer(gcps), metres, stretch)
