"""LEGACY (v1, simulated AIS): kept for reference and the AIS-simulation demo only. contracts/ are built by build_catalog.py (v2, no simulated AIS).

Raw detections -> contracts/detections.geojson + contracts/port_activity.json (validated against the schema).

Usage: .venv/bin/python postprocess.py runs/detections_raw_*.json [--seed 0]

AIS is SIMULATED (no free real Gulf AIS feed): ~80% of detections get a jittered AIS report, ~20% get none (= dark).
Every output is labelled ais_source="simulated". Replace simulate_ais() with a real feed to go live.
"""
import argparse
import json
import math
import random
import re
import statistics
from datetime import datetime, timezone
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parent.parent
CONTRACTS = ROOT / "contracts"

# lon_min, lat_min, lon_max, lat_max (approximate port + immediate approaches) and nominal vessel capacity (assumption)
PORTS = {
    "Jebel Ali": {"bbox": (54.95, 24.97, 55.12, 25.08), "capacity": 60},
    "Khalifa Port": {"bbox": (54.55, 24.76, 54.75, 24.90), "capacity": 30},
}
AIS_KEEP, JITTER_M, MATCH_GATE_M = 0.80, 120, 500


def haversine_m(lon1, lat1, lon2, lat2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 12742000 * math.asin(math.sqrt(a))


def in_port(lon, lat):
    for name, p in PORTS.items():
        x0, y0, x1, y1 = p["bbox"]
        if x0 <= lon <= x1 and y0 <= lat <= y1:
            return name
    return None


def simulate_ais(dets, rng):
    ais = []
    for d in dets:
        if rng.random() < AIS_KEEP:
            dlat = rng.gauss(0, JITTER_M) / 110540
            dlon = rng.gauss(0, JITTER_M) / (111320 * math.cos(math.radians(d["lat"])))
            ais.append({"mmsi": str(rng.randint(400000000, 699999999)), "lon": d["lon"] + dlon, "lat": d["lat"] + dlat})
    for _ in range(max(1, len(dets) // 12)):  # ghost AIS reports with no radar return (anchored/moored/missed)
        base = rng.choice(dets)
        ais.append({"mmsi": str(rng.randint(400000000, 699999999)),
                    "lon": base["lon"] + rng.uniform(-0.05, 0.05), "lat": base["lat"] + rng.uniform(-0.05, 0.05)})
    return ais


def match(dets, ais):
    free = list(ais)
    for d in sorted(dets, key=lambda x: -x["confidence"]):
        best = min(free, key=lambda a: haversine_m(d["lon"], d["lat"], a["lon"], a["lat"]), default=None)
        if best and haversine_m(d["lon"], d["lat"], best["lon"], best["lat"]) <= MATCH_GATE_M:
            d["mmsi"], d["ais_matched"], d["dark"] = best["mmsi"], True, False
            free.remove(best)
        else:
            d["mmsi"], d["ais_matched"], d["dark"] = None, False, True


def main():
    import sys
    if "--legacy-simulated" not in sys.argv:
        sys.exit("postprocess.py is LEGACY (simulated AIS) and would overwrite the v2 contracts. Use ml/build_catalog.py, or pass --legacy-simulated knowingly.")
    sys.argv.remove("--legacy-simulated")
    ap = argparse.ArgumentParser()
    ap.add_argument("raw", nargs="+")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    rng = random.Random(args.seed)

    features, per_scene = [], []
    n = 0
    for path in args.raw:
        raw = json.loads(Path(path).read_text())
        ts = raw.get("timestamp")
        if not ts:
            m = re.search(r"(\d{8})T(\d{6})", raw["scene_id"])
            ts = (datetime.strptime("".join(m.groups()), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
                  .strftime("%Y-%m-%dT%H:%M:%SZ")) if m else datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        dets = raw["detections"]
        if dets:
            match(dets, simulate_ais(dets, rng))
        for d in dets:
            n += 1
            port = in_port(d["lon"], d["lat"])
            d["port"] = port
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [round(d["lon"], 6), round(d["lat"], 6)]},
                "properties": {"id": f"d{n:04d}", "scene_id": raw["scene_id"], "timestamp": ts,
                               "confidence": round(d["confidence"], 3), "length_m": d.get("length_m"),
                               "ais_matched": d["ais_matched"], "dark": d["dark"], "mmsi": d["mmsi"],
                               "port": port, "ais_source": "simulated"},
            })
        per_scene.append((ts[:10], raw["scene_id"], dets))

    fc = {"type": "FeatureCollection", "features": features}
    jsonschema.validate(fc, json.loads((CONTRACTS / "detections.schema.json").read_text()))
    (CONTRACTS / "detections.geojson").write_text(json.dumps(fc, indent=1))

    rows = []
    for date, _, dets in per_scene:
        for name, p in PORTS.items():
            cnt = sum(1 for d in dets if d["port"] == name)
            rows.append({"port": name, "date": date, "vessel_count": cnt,
                         "berth_occupancy_pct": round(min(100.0, 100 * cnt / p["capacity"]), 1)})
    for name in PORTS:  # activity index: vessel count relative to the median of this port's scenes (=100)
        mine = [r for r in rows if r["port"] == name]
        base = statistics.median(r["vessel_count"] for r in mine) or 1
        for r in mine:
            r["activity_index"] = round(100 * r["vessel_count"] / base, 1)
    (CONTRACTS / "port_activity.json").write_text(json.dumps(rows, indent=1))
    dark = sum(f["properties"]["dark"] for f in features)
    print(f"{len(features)} detections ({dark} dark, simulated AIS), {len(rows)} port rows -> {CONTRACTS}")


if __name__ == "__main__":
    main()
