"""Export the live map's data: every detection in the real catalogue with its real AIS check.

Reads contracts/detections.geojson and contracts/ais_check.json (built by ml/ais/gfw_join.py against Global Fishing Watch)
and writes public/data/detections.geojson with one point per detection. `status` is what the map colours by:
  ais_match    GFW saw a target within 1 km and matched it to an AIS broadcast
  no_ais       GFW saw a target within 1 km with no AIS: a lead, not a verdict
  not_checked  no GFW target within 1 km, or GFW has not published the pass yet (`check` says which)
Refuses to run if ais_check.json was built for a different detections.geojson.
  python3 website/scripts/export_live.py <contracts dir> website/public/data/detections.geojson
"""
import hashlib
import json
import sys
from pathlib import Path

CONTRACTS, OUT = Path(sys.argv[1]), Path(sys.argv[2])
raw = (CONTRACTS / "detections.geojson").read_bytes()
check = json.loads((CONTRACTS / "ais_check.json").read_text())
if check["contract_sha256"] != hashlib.sha256(raw).hexdigest():
    sys.exit("ais_check.json does not match detections.geojson: rebuild it with ml/ais/gfw_join.py")

feats = []
for f in json.loads(raw)["features"]:
    p = f["properties"]
    c = check["detections"].get(p["id"], {"check": "not_available"})
    status = c["check"] if c["check"] in ("ais_match", "no_ais") else "not_checked"
    props = {"id": p["id"], "scene_id": p["scene_id"], "timestamp": p["timestamp"], "length_m": p["length_m"],
             "radar_class": p["radar_class"], "port": p["port"], "status": status, "check": c["check"]}
    if status == "ais_match":
        props.update({"name": c.get("name"), "flag": c.get("flag")})
    lon, lat = f["geometry"]["coordinates"]
    feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(lon, 5), round(lat, 5)]},
                  "properties": props})

out = {"type": "FeatureCollection", "source": "contracts/detections.geojson + contracts/ais_check.json",
       "ais_attribution": check["attribution"], "features": feats}
OUT.write_text(json.dumps(out, separators=(",", ":")))
n = {s: sum(x["properties"]["status"] == s for x in feats) for s in ("ais_match", "no_ais", "not_checked")}
print(f"wrote {OUT} · {len(feats)} detections · {n}")
