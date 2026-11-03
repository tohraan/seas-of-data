"""Per-detection radar features and the rule that sorts detections into ship / uncertain.

contrast_db   brightest pixel in the detection box minus the median of its 81 x 81 px surroundings (box + 6 px excluded), in dB
vh_contrast_db  the same measure on the VH (cross-polarised) band of the same product. Ships, with their corners and
              superstructure, stay bright in VH; sea clutter and most sidelobes fall away, so VH confirms a VV target.
land_m        distance from the detection to the nearest land cell of the static sea mask (assets/sea_mask.npz, 0.001 deg cells,
              so it is only good to about 110 m)

RULE was chosen on half of a 120-chip visual review sample (odd sheets) and checked on the other half (even sheets);
see reports/review_verdicts.json and review_apply.py. Near-coast detections are kept as `ship` only when very bright,
because buildings, piers and reclaimed land look like ships at 10 m. They are tagged `uncertain`, never deleted.
"""
from pathlib import Path

import numpy as np
from scipy import ndimage as ndi

MASK = Path(__file__).parent / "assets" / "sea_mask.npz"
RULE = {"min_contrast_db": 18.0, "min_snr_z": 9.0, "coast_m": 600.0, "coast_contrast_db": 32.0, "min_vh_contrast_db": None}
HALF = 40          # window half-size, px
EXCL = 6           # px excluded around the box when estimating the background


class LandDistance:
    def __init__(self, path=MASK):
        m = np.load(path)
        self.lon0, self.lat0, self.res = float(m["lon0"]), float(m["lat0"]), float(m["res"])
        self.grid = m["mask"].astype(bool)
        self.dist = ndi.distance_transform_edt(self.grid) * self.res * 110540

    def __call__(self, lon, lat):
        i, j = int((lat - self.lat0) / self.res), int((lon - self.lon0) / self.res)
        if 0 <= i < self.grid.shape[0] and 0 <= j < self.grid.shape[1]:
            return float(self.dist[i, j])
        return None


def contrast_db(ds, box):
    from rasterio.windows import Window
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    X0, Y0 = max(0, cx - HALF), max(0, cy - HALF)
    w = ds.read(1, window=Window(X0, Y0, min(ds.width, cx + HALF) - X0, min(ds.height, cy + HALF) - Y0)).astype("float32")
    db = 20 * np.log10(np.maximum(w, 1))
    bx0, by0, bx1, by1 = x0 - X0, y0 - Y0, x1 - X0, y1 - Y0
    inside = db[max(0, by0):by1, max(0, bx0):bx1]
    keep = np.ones(db.shape, bool)
    keep[max(0, by0 - EXCL):by1 + EXCL, max(0, bx0 - EXCL):bx1 + EXCL] = False
    bg = float(np.median(db[keep]))
    return float(inside.max()) - bg


def is_ship_like(contrast, snr_z, land_m, vh_contrast=None, rule=RULE):
    if contrast is None or contrast < rule["min_contrast_db"] or snr_z < rule["min_snr_z"]:
        return False
    if rule.get("min_vh_contrast_db") is not None and (vh_contrast is None or vh_contrast < rule["min_vh_contrast_db"]):
        return False   # not confirmed in VH (or VH unavailable): uncertain, never deleted
    return land_m is None or land_m >= rule["coast_m"] or contrast >= rule["coast_contrast_db"]
