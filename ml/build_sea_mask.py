"""Build ml/assets/sea_mask.npz (static sea mask on a lon/lat grid) from one calm-sea scene.
Usage: .venv/bin/python build_sea_mask.py <calm scene.tiff>   (region: Jebel Ali to Khalifa Port, ~80 km)
"""
import sys
import numpy as np, rasterio
from rasterio.transform import GCPTransformer
from infer import sea_model, GEO_MASK

lon0, lat0, lon1, lat1, res = 54.45, 24.55, 55.30, 25.30, 0.001
with rasterio.open(sys.argv[1]) as ds:
    tr = GCPTransformer(ds.gcps[0])
    r0, c0 = tr.rowcol(54.86, 24.91); half = 4000
    X0, X1, Y0, Y1 = max(0, int(c0) - half), min(ds.width, int(c0) + half), max(0, int(r0) - half), min(ds.height, int(r0) + half)
    thr, in_sea = sea_model(ds, X0, X1, Y0, Y1, margin_m=0)
    f = in_sea.f
    lons = lon0 + (np.arange(int(round((lon1 - lon0) / res))) + 0.5) * res
    lats = lat0 + (np.arange(int(round((lat1 - lat0) / res))) + 0.5) * res
    LON, LAT = np.meshgrid(lons, lats)
    rows, cols = tr.rowcol(LON.ravel(), LAT.ravel())
    rows, cols = np.asarray(rows), np.asarray(cols)
    a, b = ((rows - Y0) // f), ((cols - X0) // f)
    ok = (a >= 0) & (a < in_sea.mask.shape[0]) & (b >= 0) & (b < in_sea.mask.shape[1])
    grid = np.zeros(LON.size, bool)
    grid[ok] = in_sea.mask[a[ok], b[ok]]
    grid = grid.reshape(LON.shape)
np.savez_compressed(GEO_MASK, lon0=lon0, lat0=lat0, res=res, mask=grid)
print(f"saved {GEO_MASK} grid {grid.shape}, sea fraction {grid.mean():.2f}, scene threshold {thr:.1f} dB")
