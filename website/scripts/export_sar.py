"""Export the 2 Nov Sentinel-1 pass as a north-up crop that lines up with the last frame of the orbit render, plus
detection and port-box pixel positions, so the site can cross-fade from the render into real radar and draw the rings.

The crop covers the ground the orbit camera sees at its final frame (seq_b_orbit.py: 110 km above Jebel Ali, 40 mm
lens, 36 mm sensor, 16:9), on the same 6371 km sphere. Run from a checkout that has ml/ (with data/scenes) and contracts/:
  ml/.venv/bin/python website/scripts/export_sar.py <repo root> <out dir>
"""
import json, math, sys
from pathlib import Path
import numpy as np, rasterio
from PIL import Image
from rasterio.enums import Resampling
from rasterio.transform import GCPTransformer
from rasterio.windows import Window
from scipy import ndimage as ndi

ROOT, OUT = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
sys.path.insert(0, str(ROOT / "ml"))
from infer import scene_window, to_uint8
import postprocess

LON0, LAT0 = 55.06, 25.01          # Jebel Ali, the orbit camera's final target
GROUND_W_KM = 110.0 * 36 / 40      # camera height x sensor width / focal length
GROUND_H_KM = GROUND_W_KM * 9 / 16
KM_PER_DEG = 6371.0 * math.pi / 180
OUT_W, OUT_H = 3200, 1800
LON_SPAN = GROUND_W_KM / (KM_PER_DEG * math.cos(math.radians(LAT0)))
LAT_SPAN = GROUND_H_KM / KM_PER_DEG
WEST, EAST = LON0 - LON_SPAN / 2, LON0 + LON_SPAN / 2
SOUTH, NORTH = LAT0 - LAT_SPAN / 2, LAT0 + LAT_SPAN / 2


def px(lon, lat):
    return round((lon - WEST) / LON_SPAN * OUT_W, 1), round((NORTH - lat) / LAT_SPAN * OUT_H, 1)


OUT.mkdir(parents=True, exist_ok=True)
scene = next((ROOT / "ml/data/scenes").glob("*20261102T021455*_vv.tiff"))
fc = json.loads((ROOT / "contracts/detections.geojson").read_text())["features"]
fc = [f for f in fc if f["properties"]["scene_id"].endswith("20261102T021455")]
with rasterio.open(scene) as ds:
    tr = GCPTransformer(ds.gcps[0])
    lo, hi = scene_window(ds)
    # Scene row/col for every output pixel: exact on a coarse grid, interpolated between (the GCP warp is smooth).
    step = 16
    gx = np.arange(0, OUT_W + step, step)
    gy = np.arange(0, OUT_H + step, step)
    lons = WEST + (gx + 0.5) / OUT_W * LON_SPAN
    lats = NORTH - (gy + 0.5) / OUT_H * LAT_SPAN
    LL, TT = np.meshgrid(lons, lats)
    rows, cols = (np.asarray(a, dtype=np.float64).reshape(LL.shape) for a in tr.rowcol(LL.ravel(), TT.ravel(), op=lambda v: v))
    yy, xx = np.mgrid[0:OUT_H, 0:OUT_W] / step
    rows = ndi.map_coordinates(rows, [yy, xx], order=1)
    cols = ndi.map_coordinates(cols, [yy, xx], order=1)
    # Read the covering window at about the output pixel size (area average cuts speckle), then sample it.
    r0, r1 = max(int(rows.min()) - 8, 0), min(int(rows.max()) + 8, ds.height)
    c0, c1 = max(int(cols.min()) - 8, 0), min(int(cols.max()) + 8, ds.width)
    scale = max(1, round(GROUND_W_KM * 1000 / OUT_W / 10))  # source pixels are 10 m
    win = ds.read(1, window=Window(c0, r0, c1 - c0, r1 - r0),
                  out_shape=((r1 - r0) // scale, (c1 - c0) // scale), resampling=Resampling.average)
    img = ndi.map_coordinates(win.astype(np.float32), [(rows - r0) / scale, (cols - c0) / scale], order=1, cval=0)
Image.fromarray(to_uint8(img, lo, hi)).save(OUT / "sar_20261102.webp", quality=80, method=6)

# The pipeline's static lon/lat sea mask (ml/assets/sea_mask.npz), sampled on the same grid at quarter size.
m = np.load(ROOT / "ml/assets/sea_mask.npz")
mlon0, mlat0, res, grid = float(m["lon0"]), float(m["lat0"]), float(m["res"]), m["mask"]
mw, mh = OUT_W // 4, OUT_H // 4
mlon = WEST + (np.arange(mw) + 0.5) / mw * LON_SPAN
mlat = NORTH - (np.arange(mh) + 0.5) / mh * LAT_SPAN
i = np.floor((mlat - mlat0) / res).astype(int)[:, None].repeat(mw, 1)
j = np.floor((mlon - mlon0) / res).astype(int)[None, :].repeat(mh, 0)
ok = (i >= 0) & (i < grid.shape[0]) & (j >= 0) & (j < grid.shape[1])
sea = np.zeros((mh, mw), bool)
sea[ok] = grid[i[ok], j[ok]]
# White with the mask in alpha, so CSS mask-image works without mask-mode: luminance.
a = (sea * 255).astype(np.uint8)
Image.fromarray(np.dstack([np.full_like(a, 255), a]), "LA").save(OUT / "sea_mask.png", optimize=True)

ports = {n: [px(p["bbox"][0], p["bbox"][3]), px(p["bbox"][2], p["bbox"][3]), px(p["bbox"][2], p["bbox"][1]),
             px(p["bbox"][0], p["bbox"][1])] for n, p in postprocess.PORTS.items()}
pts = []
for f in fc:
    x, y = px(*f["geometry"]["coordinates"])
    if 0 <= x < OUT_W and 0 <= y < OUT_H:
        q = f["properties"]
        pts.append({"x": x, "y": y, "dark": q["dark"], "conf": q["confidence"], "len": q["length_m"], "id": q["id"],
                    "lon": f["geometry"]["coordinates"][0], "lat": f["geometry"]["coordinates"][1]})
(OUT / "sar_points.json").write_text(json.dumps({
    "w": OUT_W, "h": OUT_H, "scene": fc[0]["properties"]["scene_id"],
    "bounds": [round(v, 5) for v in (WEST, SOUTH, EAST, NORTH)], "points": pts, "ports": ports}))
print("saved", OUT_W, OUT_H, "points", len(pts), "dark", sum(p["dark"] for p in pts), "of", len(fc))
