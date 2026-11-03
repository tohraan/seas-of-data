"""Write contracts/manifest.json: the provenance record of every number in contracts/.

Usage: .venv/bin/python manifest.py [--scenes data/scenes] [--offline]
Per scene: ESA product name, acquisition window, file size and sha256 of the VV GeoTIFF, scene extent from its GCPs,
Copernicus Data Space product id (read from the public catalogue) and Planetary Computer item id, CFAR parameters and
stage counts (from the raw run JSON), and how many detections ended up in each radar_class.
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ML = ROOT / "ml"
CDSE = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products"


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 24), b""):
            h.update(chunk)
    return h.hexdigest()


def cdse_lookup(product):
    q = urllib.parse.urlencode({"$filter": f"Name eq '{product}'", "$select": "Id,Name,ContentLength,ContentDate"})
    try:
        with urllib.request.urlopen(f"{CDSE}?{q}", timeout=60) as r:
            v = json.load(r)["value"]
    except Exception as exc:  # network is optional
        return {"error": str(exc)}
    if not v:
        return {"error": "not found in catalogue"}
    return {"id": v[0]["Id"], "download_size_bytes": v[0]["ContentLength"],
            "url": f"https://catalogue.dataspace.copernicus.eu/odata/v1/Products({v[0]['Id']})"}


def extent(ds):
    from rasterio.transform import GCPTransformer
    pts = ds.gcps[0]
    lons, lats = [p.x for p in pts], [p.y for p in pts]
    return {"lon_min": round(min(lons), 3), "lon_max": round(max(lons), 3), "lat_min": round(min(lats), 3), "lat_max": round(max(lats), 3)}


def main():
    import rasterio
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenes", default=str(ML / "data" / "scenes"))
    ap.add_argument("--offline", action="store_true")
    a = ap.parse_args()
    meta = json.loads((ML / "reports" / "build_meta.json").read_text())
    feats = json.loads((ROOT / "contracts" / "detections.geojson").read_text())["features"]
    sys.path.insert(0, str(ML))
    scenes = []
    for scene_id, info in sorted(meta["scenes"].items(), key=lambda kv: kv[0].split("_")[1]):
        product = meta["products"][scene_id]
        path = Path(a.scenes) / (product.removesuffix(".SAFE") + "_vv.tiff")
        m = re.match(r"(S1[A-D])_IW_GRDH_1SDV_(\d{8}T\d{6})_(\d{8}T\d{6})_(\d{6})_([0-9A-F]{6})_([0-9A-F]{4})", product)
        mine = [f["properties"] for f in feats if f["properties"]["scene_id"] == scene_id]
        with rasterio.open(path) as ds:
            ext, size = extent(ds), [ds.width, ds.height]
        item_id = None
        if not a.offline:
            try:
                import fetch_pc
                item_id = fetch_pc.find_item(scene_id)["id"]
            except BaseException as exc:
                item_id = f"lookup failed: {exc}"
        iso = lambda s: datetime.strptime(s, "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        scenes.append({
            "scene_id": scene_id, "product": product, "satellite": m.group(1), "mode": "IW GRDH 1SDV (VV used)",
            "acquired_start_utc": iso(m.group(2)), "acquired_stop_utc": iso(m.group(3)),
            "absolute_orbit": int(m.group(4)), "file": path.name, "size_bytes": path.stat().st_size, "sha256": sha256(path),
            "pixels": {"width": size[0], "height": size[1]}, "scene_extent_deg": ext,
            "copernicus_data_space": {} if a.offline else cdse_lookup(product),
            "planetary_computer_item": item_id,
            "cfar": {"params": info.get("params"), "stages": info.get("stages")},
            "detections": {"n": len(mine), "by_radar_class": dict(Counter(p["radar_class"] for p in mine)), "by_size_class": dict(Counter(p["size_class"] for p in mine))},
        })
    sha = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    mask = __import__("numpy").load(ML / "assets" / "sea_mask.npz")
    lon0, lat0, res, shp = float(mask["lon0"]), float(mask["lat0"]), float(mask["res"]), mask["mask"].shape
    def ais_note():
        f = ROOT / "contracts" / "ais_check.json"
        base = "detections.geojson carries no AIS verdicts (status not_checked, dark null). "
        if not f.exists():
            return base + "No AIS check has been run."
        chk = json.loads(f.read_text())
        if chk["contract_sha256"] != hashlib.sha256((ROOT / "contracts" / "detections.geojson").read_bytes()).hexdigest():
            return base + "contracts/ais_check.json is stale (built for another detections.geojson): rerun python -m ais.gfw_join."
        n = Counter(c["check"] for c in chk["detections"].values())
        off = [p["scene_id"] for p in chk["passes"] if not p["available"]]
        return (base + f"An independent AIS check against Global Fishing Watch's SAR targets is in contracts/ais_check.json: "
                f"{n['ais_match']} detections match an AIS-broadcasting vessel, {n['no_ais']} match a GFW target with no AIS "
                f"(leads for a patrol, not verdicts), {n['no_gfw_target']} have no GFW target within 1 km"
                + (f", {n['not_available']} are not checked yet (GFW has not published {', '.join(off)})." if off else "."))

    manifest = {
        "title": "Seas of Data: Gulf radar ship detections (Jebel Ali and Khalifa Port), contract v3",
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "code_git_sha": sha,
        "attribution": "Contains modified Copernicus Sentinel data (2026). Sentinel-1 data are free and open under the Copernicus licence.",
        "what_is_real": "Every detection is a bright target found by a CFAR detector in a real Sentinel-1 VV scene; the scenes are listed below with sha256, so anyone can re-download them and check.",
        "what_is_not": ais_note(),
        "area_searched": {"lon_min": lon0, "lon_max": round(lon0 + res * shp[1], 3), "lat_min": lat0, "lat_max": round(lat0 + res * shp[0], 3),
                          "note": "limited by the static sea mask ml/assets/sea_mask.npz, not by the scene, which is wider"},
        "detector": {"name": meta["detector"], "radar_class_rule": meta["rule"], "persistence_gate_m": meta["persist_gate_m"],
                     "note": "confidence is the CFAR peak z-score divided by 20, not a probability"},
        "totals": {"scenes": len(scenes), "detections": len(feats), "by_radar_class": dict(Counter(f["properties"]["radar_class"] for f in feats))},
        "scenes": scenes,
        "reproduce": [
            "cd ml && uv sync",
            "ml/run_all.sh   # reads scenes from the Planetary Computer mirror if ml/data/scenes is empty, runs CFAR (k=8), builds contracts/ + chips",
            "ml/.venv/bin/python ml/manifest.py   # re-checks hashes and rewrites this file",
        ],
    }
    (ROOT / "contracts" / "manifest.json").write_text(json.dumps(manifest, indent=1))
    print("manifest:", len(scenes), "scenes,", len(feats), "detections")


if __name__ == "__main__":
    main()
