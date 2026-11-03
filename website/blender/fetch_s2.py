"""Mosaic Sentinel-2 cloudless (EOX, 2016, CC BY 4.0) tiles over the UAE coast into equirectangular PNGs (alpha = land).

The orbit push-in ends low enough that NASA's 500 m Blue Marble goes soft, so seq_b_orbit.py blends these in.
Colours are matched to the Blue Marble crop so the feathered seams do not show.
  python3 website/blender/fetch_s2.py
Attribution: Sentinel-2 cloudless - https://s2maps.eu by EOX IT Services GmbH (Contains modified Copernicus Sentinel data 2016)
"""
import math
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

ASSETS = Path(__file__).resolve().parent / "assets"
CACHE = ASSETS / "s2_tiles"
URL = "https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless_3857/default/g/{z}/{y}/{x}.jpg"
# name: (zoom, lon0, lon1, lat0, lat1)
LAYERS = {
    "s2_z10": (10, 52.5, 57.5, 23.0, 27.0),
    "s2_z11": (11, 54.0, 56.4, 24.2, 26.2),
}
REFERENCE = (ASSETS / "gulf_44E64E_14N34N.jpg", (44.0, 64.0, 14.0, 34.0))


def tile_xy(lon, lat, z):
    n = 2 ** z
    x = (lon + 180) / 360 * n
    y = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n
    return x, y


def fetch(z, x, y):
    path = CACHE / f"{z}_{x}_{y}.jpg"
    if not path.exists():
        # curl uses the system trust store (python.org builds often ship without certificates).
        subprocess.run(["curl", "-sfL", "--retry", "3", "-A", "interstellar-seas-of-data/1.0", "-o", str(path),
                        URL.format(z=z, x=x, y=y)], check=True)
    return path


def mosaic(z, lon0, lon1, lat0, lat1):
    x0, y0 = (math.floor(v) for v in tile_xy(lon0, lat1, z))
    x1, y1 = (math.floor(v) for v in tile_xy(lon1, lat0, z))
    jobs = [(z, x, y) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)]
    with ThreadPoolExecutor(4) as pool:
        paths = list(pool.map(lambda j: fetch(*j), jobs))
    merc = Image.new("RGB", ((x1 - x0 + 1) * 256, (y1 - y0 + 1) * 256))
    for (_, x, y), p in zip(jobs, paths):
        merc.paste(Image.open(p).convert("RGB"), ((x - x0) * 256, (y - y0) * 256))
    merc = np.asarray(merc)
    # Resample Mercator rows onto an equirectangular grid at the tile's native pixel size.
    px_per_deg = 2 ** z * 256 / 360
    w = round((lon1 - lon0) * px_per_deg)
    h = round((lat1 - lat0) * px_per_deg / math.cos(math.radians((lat0 + lat1) / 2)))
    lons = lon0 + (np.arange(w) + 0.5) / w * (lon1 - lon0)
    lats = lat1 - (np.arange(h) + 0.5) / h * (lat1 - lat0)
    gx = ((lons + 180) / 360 * 2 ** z - x0) * 256
    gy = ((1 - np.arcsinh(np.tan(np.radians(lats))) / np.pi) / 2 * 2 ** z - y0) * 256
    return merc[np.clip(gy.astype(int), 0, merc.shape[0] - 1)][:, np.clip(gx.astype(int), 0, merc.shape[1] - 1)]


def land_mask(img):
    """Land (red over blue) or bright surf; EOX's open sea is quilted from many scenes, so the base map keeps it."""
    f = img.astype(np.float32)
    luma = f @ np.array([0.299, 0.587, 0.114], np.float32)
    m = np.maximum(np.clip((f[..., 0] - f[..., 2] - 4) / 16, 0, 1) * np.clip((luma - 40) / 30, 0, 1),
                   np.clip((luma - 150) / 40, 0, 1))
    return np.asarray(Image.fromarray((m * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(3)))


def match_colours(img, bounds):
    """Per-channel mean/std match to the Blue Marble crop over the same area, measured on land only."""
    ref_path, (rl0, rl1, rb0, rb1) = REFERENCE
    Image.MAX_IMAGE_PIXELS = None
    ref = Image.open(ref_path)
    lon0, lon1, lat0, lat1 = bounds
    W, H = ref.size
    box = (round((lon0 - rl0) / (rl1 - rl0) * W), round((rb1 - lat1) / (rb1 - rb0) * H),
           round((lon1 - rl0) / (rl1 - rl0) * W), round((rb1 - lat0) / (rb1 - rb0) * H))
    ref = np.asarray(ref.crop(box).convert("RGB"))
    ref = ref[land_mask(ref) > 200].astype(np.float32)
    src = img[land_mask(img) > 200].astype(np.float32)
    out = (img.astype(np.float32) - src.mean(0)) / (src.std(0) + 1e-6) * ref.std(0) + ref.mean(0)
    return np.clip(out, 0, 255).astype(np.uint8).reshape(img.shape)


def main():
    CACHE.mkdir(parents=True, exist_ok=True)
    for name, (z, *bounds) in LAYERS.items():
        raw = mosaic(z, *bounds)
        rgba = np.dstack([match_colours(raw, bounds), land_mask(raw)])
        Image.fromarray(rgba, "RGBA").save(ASSETS / f"{name}.png")
        print(name, rgba.shape)


if __name__ == "__main__":
    main()
