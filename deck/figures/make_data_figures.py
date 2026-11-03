"""Real-data figures for the deck: raw radar crop, sea-mask overlay, detection zoom and ship chips (2 Nov 2026 pass).
Run with the ml venv:  ml/.venv/bin/python deck/figures/make_data_figures.py   (scenes live in ml/data/scenes, not in git)
"""
import json, os, sys
from pathlib import Path
import numpy as np, rasterio
from PIL import Image, ImageDraw
from rasterio.transform import GCPTransformer
from rasterio.windows import Window

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ML = Path(os.environ.get("ML_DIR", "/Users/tohraan/space/ml"))  # folder holding data/scenes (not in git)
sys.path.insert(0, str(ROOT / "ml"))
from infer import scene_window, to_uint8, geo_sea

TEAL, SLATE, WHITE = (63, 184, 166), (143, 163, 181), (238, 240, 234)
COL = {"ship": TEAL, "uncertain": SLATE, "likely_fixed": WHITE}
scene = next((ML / "data/scenes").glob("*20261102T021455*_vv.tiff"))
fc = [f for f in json.loads((ROOT / "contracts/detections.geojson").read_text())["features"]
      if f["properties"]["scene_id"].endswith("20261102T021455")]

with rasterio.open(scene) as ds:
    tr = GCPTransformer(ds.gcps[0])
    lo, hi = scene_window(ds)
    # 1 + 2: coast window, raw and with the sea mask tinted
    X0, X1, Y0, Y1, W = 11200, 17400, 4600, 9600, 1100
    s = W / (X1 - X0)
    shape = (int((Y1 - Y0) * s), W)
    arr = ds.read(1, window=Window(X0, Y0, X1 - X0, Y1 - Y0), out_shape=shape)
    raw = Image.fromarray(to_uint8(arr, lo, hi)).convert("RGB")
    raw.save(HERE / "radar_raw.png")
    in_sea, water = geo_sea(ds, X0, X1, Y0, Y1)
    wm = Image.fromarray((water * 255).astype("uint8")).resize(raw.size, Image.NEAREST)
    tint = Image.new("RGB", raw.size, (52, 116, 150))
    masked = Image.composite(Image.blend(raw, tint, 0.55), raw, wm)
    masked.save(HERE / "radar_seamask.png")
    # 3: zoom on an offshore group, rings coloured by radar class (teal ship, slate uncertain, white likely fixed)
    cx, cy = 16300, 6950
    zx0, zy0, zs = cx - 450, cy - 350, 900
    z = ds.read(1, window=Window(zx0, zy0, zs, 700))
    zi = Image.fromarray(to_uint8(z, lo, hi)).convert("RGB").resize((zs * 2, 1400), Image.BICUBIC)
    d = ImageDraw.Draw(zi)
    n = 0
    for f in fc:
        lon, lat = f["geometry"]["coordinates"]
        r, c = tr.rowcol(lon, lat)
        x, y = (c - zx0) * 2, (r - zy0) * 2
        if 0 <= x < zi.width and 0 <= y < zi.height:
            col = COL[f["properties"]["radar_class"]]
            d.ellipse([x - 34, y - 34, x + 34, y + 34], outline=col, width=5)
            n += 1
    zi.save(HERE / "radar_zoom.png")
    # 4: chips (48 px = 480 m square, upscaled): top row ship class, bottom row uncertain class
    pts = []
    for cls, pick in (("ship", lambda f: f["properties"]["port"] is None), ("uncertain", lambda f: True)):
        k = 0
        for f in sorted(fc, key=lambda f: -f["properties"]["snr_z"]):
            if f["properties"]["radar_class"] != cls or not pick(f):
                continue
            lon, lat = f["geometry"]["coordinates"]
            r, c = tr.rowcol(lon, lat)
            if 24 < r < ds.height - 24 and 24 < c < ds.width - 24:
                pts.append((int(r), int(c), cls)); k += 1
            if k == 4:
                break
    S = 240
    sheet = Image.new("RGB", (4 * S + 3 * 10, 2 * S + 10), (10, 23, 34))
    for i, (r, c, cls) in enumerate(pts[:8]):
        a = ds.read(1, window=Window(c - 24, r - 24, 48, 48))
        im = Image.fromarray(to_uint8(a, lo, hi)).convert("RGB").resize((S, S), Image.BICUBIC)
        ImageDraw.Draw(im).rectangle([0, 0, S - 1, S - 1], outline=COL[cls], width=5)
        sheet.paste(im, ((i % 4) * (S + 10), (i // 4) * (S + 10)))
    sheet.save(HERE / "ship_chips.png")
print("figures:", [p.name for p in HERE.glob("radar_*.png")], "chips", len(pts), "rings in zoom", n)
