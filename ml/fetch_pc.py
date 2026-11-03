"""Open a Sentinel-1 GRD scene from the public Microsoft Planetary Computer mirror (no login, no 1 GB download).

Usage:  .venv/bin/python fetch_pc.py S1C_20261024T142351            # prints a signed COG URL (valid about an hour)
        .venv/bin/python cfar.py "$(.venv/bin/python fetch_pc.py S1C_20261024T142351)" --out ... [same flags as local]
Scenes are cloud-optimised GeoTIFFs, so rasterio reads only the windows it needs over HTTP. Same ESA product as the
Copernicus Data Space copy; check_same() proves it pixel for pixel on a window.
"""
import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

STAC = "https://planetarycomputer.microsoft.com/api/stac/v1/search"
SIGN = "https://planetarycomputer.microsoft.com/api/sas/v1/sign?href="
LON, LAT = 54.875, 24.925


def _post(url, body):
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.load(r)


def find_item(scene_id):
    sat, ts = scene_id.split("_")
    t = datetime.strptime(ts, "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
    span = f"{(t - timedelta(minutes=2)):%Y-%m-%dT%H:%M:%SZ}/{(t + timedelta(minutes=2)):%Y-%m-%dT%H:%M:%SZ}"
    res = _post(STAC, {"collections": ["sentinel-1-grd"], "intersects": {"type": "Point", "coordinates": [LON, LAT]},
                       "datetime": span, "limit": 10})
    for f in res["features"]:
        if f["id"].startswith(f"{sat}_IW_GRDH_1SDV_{ts}"):
            return f
    raise SystemExit(f"{scene_id} not found in the Planetary Computer catalogue")


def signed_vv_url(scene_id):
    item = find_item(scene_id)
    href = urllib.parse.quote(item["assets"]["vv"]["href"], safe="")
    with urllib.request.urlopen(SIGN + href, timeout=90) as r:
        return json.load(r)["href"], item["id"]


def check_same(scene_id, local_tiff, size=512):
    """True if a window near the Jebel Ali detections is pixel-identical in the PC copy and the local CDSE copy."""
    import numpy as np
    import rasterio
    from rasterio.windows import Window
    url, _ = signed_vv_url(scene_id)
    with rasterio.open(url) as a, rasterio.open(local_tiff) as b:
        if (a.width, a.height) != (b.width, b.height):
            return False, f"size differs {a.width}x{a.height} vs {b.width}x{b.height}"
        w = Window(b.width // 2, b.height // 2, size, size)
        return bool(np.array_equal(a.read(1, window=w), b.read(1, window=w))), "window identical" 


if __name__ == "__main__":
    url, item_id = signed_vv_url(sys.argv[1])
    print(url)
    print(item_id, file=sys.stderr)
