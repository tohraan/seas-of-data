"""Check every radar detection against Global Fishing Watch's own SAR targets for the same pass, split by AIS match.

Usage: .venv/bin/python -m ais.gfw_join          (needs GFW_TOKEN in ml/.env; reads contracts/detections.geojson)
Writes ml/reports/gfw_reference.json (every GFW target per pass, for eval_gfw.py) and contracts/ais_check.json (one check per
detection, tied to the sha256 of detections.geojson). Checks:
  ais_match      GFW saw a target within 1 km and matched it to an AIS broadcast (vessel identity attached)
  no_ais         GFW saw a target within 1 km and found no AIS for it: a lead for a patrol, not a verdict
  no_gfw_target  GFW has the pass but no target within 1 km (GFW is weak near quays and drops small targets)
  not_available  GFW has not published this pass yet
GFW rounds positions to 0.01 degrees, so the gate is 1 km, paired one to one, closest first. GFW is an independent detector
(a CNN on the same Sentinel-1 scenes), not ground truth. Non-commercial use only; credit "Powered by Global Fishing Watch".
"""
import hashlib
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "contracts" / "detections.geojson"
GATE_M = 1000
PASS_WINDOW = timedelta(minutes=30)      # a day can hold two passes: keep only targets near this overpass
CENTER, RADIUS_KM = (54.86, 24.91), 40   # the CFAR search circle; recall is only fair inside it


def metres(lon1, lat1, lon2, lat2):
    return math.hypot((lon1 - lon2) * 111320 * math.cos(math.radians(lat1)), (lat1 - lat2) * 110540)


def in_circle(lon, lat):
    return metres(lon, lat, *CENTER) <= RADIUS_KM * 1000


def target(row, matched):
    """One GFW row -> the fields we keep. Identity only exists for AIS-matched targets."""
    t = {"lon": row["lon"], "lat": row["lat"], "matched": matched, "time": row.get("entryTimestamp")}
    if matched:
        t.update({"name": row.get("shipName") or None, "flag": row.get("flag") or None, "type": row.get("vesselType") or None,
                  "imo": row.get("imo") or None, "mmsi": row.get("mmsi") or None, "vessel_id": row.get("vesselId") or None})
    return t


def near_pass(rows, moment):
    return [r for r in rows if r.get("entryTimestamp")
            and abs(datetime.fromisoformat(r["entryTimestamp"].replace("Z", "+00:00")) - moment) <= PASS_WINDOW]


def pair(ours, theirs, gate_m=GATE_M):
    """One-to-one pairs within gate_m, closest first. Returns {our index: (their index, metres)}."""
    cands = sorted((metres(d["lon"], d["lat"], t["lon"], t["lat"]), i, j)
                   for i, d in enumerate(ours) for j, t in enumerate(theirs))
    pairs, used = {}, set()
    for m, i, j in cands:
        if m > gate_m:
            break
        if i not in pairs and j not in used:
            pairs[i] = (j, m)
            used.add(j)
    return pairs


def check_pass(ours, theirs):
    """ours: [{id, lon, lat}], theirs: [target()]. Returns ({id: check}, per-pass totals)."""
    pairs = pair(ours, theirs)
    checks = {}
    for i, d in enumerate(ours):
        if i not in pairs:
            checks[d["id"]] = {"check": "no_gfw_target"}
            continue
        j, m = pairs[i]
        t = theirs[j]
        c = {"check": "ais_match" if t["matched"] else "no_ais", "offset_m": round(m)}
        if t["matched"]:
            c.update({k: t[k] for k in ("name", "flag", "type", "imo", "mmsi", "vessel_id")})
        checks[d["id"]] = c
    inside = [j for j, t in enumerate(theirs) if in_circle(t["lon"], t["lat"])]
    found = {j for j, _ in pairs.values()}
    totals = {"gfw_targets": len(theirs), "gfw_ais_matched": sum(t["matched"] for t in theirs),
              "ours": len(ours), "paired": len(pairs),
              "paired_ais_match": sum(theirs[j]["matched"] for j, _ in pairs.values()),
              "paired_no_ais": sum(not theirs[j]["matched"] for j, _ in pairs.values()),
              "gfw_targets_in_circle": len(inside), "found_in_circle": len(found & set(inside)),
              "recall_vs_gfw_in_circle": round(len(found & set(inside)) / len(inside), 3) if inside else None}
    return checks, totals


def main():
    from ais.gfw import report, token
    raw = CONTRACT.read_bytes()
    feats = json.loads(raw)["features"]
    tok = token()
    checks, passes, reference = {}, [], []
    for scene_id in sorted({f["properties"]["scene_id"] for f in feats}):
        fs = [f for f in feats if f["properties"]["scene_id"] == scene_id]
        moment = datetime.fromisoformat(fs[0]["properties"]["timestamp"].replace("Z", "+00:00"))
        ours = [{"id": f["properties"]["id"], "lon": f["geometry"]["coordinates"][0], "lat": f["geometry"]["coordinates"][1]} for f in fs]
        day = moment.date().isoformat()
        theirs = [target(r, True) for r in near_pass(report(tok, day, True), moment)] + \
                 [target(r, False) for r in near_pass(report(tok, day, False), moment)]
        ts = moment.strftime("%Y-%m-%dT%H:%M:%SZ")
        if not theirs:
            checks.update({d["id"]: {"check": "not_available"} for d in ours})
            passes.append({"scene_id": scene_id, "timestamp": ts, "available": False})
            print(f"{scene_id}: GFW has not published this pass")
            continue
        c, totals = check_pass(ours, theirs)
        checks.update(c)
        passes.append({"scene_id": scene_id, "timestamp": ts, "available": True, **totals})
        reference.append({"scene_id": scene_id, "timestamp": ts, "targets": theirs})
        print(f"{scene_id}: {totals}")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    head = {"built_at": now, "source": "Global Fishing Watch 4Wings, public-global-sar-presence:latest",
            "attribution": "Powered by Global Fishing Watch", "gate_m": GATE_M}
    (ROOT / "ml" / "reports" / "gfw_reference.json").write_text(json.dumps({**head, "passes": reference}, indent=1))
    out = {**head, "contract_sha256": hashlib.sha256(raw).hexdigest(),
           "note": "Independent AIS check. GFW is another detector on the same scenes, not ground truth. no_ais is a lead "
                   "for a patrol, not a verdict: AIS reception gaps and ships at berth also produce it.",
           "passes": passes, "detections": dict(sorted(checks.items()))}
    (ROOT / "contracts" / "ais_check.json").write_text(json.dumps(out, indent=1))
    n = {k: sum(c["check"] == k for c in checks.values()) for k in ("ais_match", "no_ais", "no_gfw_target", "not_available")}
    print("contracts/ais_check.json:", n)


if __name__ == "__main__":
    main()
