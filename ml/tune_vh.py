"""Does VH (cross-polarisation) improve the ship/uncertain rule? Sweeps VH rule variants on the review halves.

Usage: .venv/bin/python tune_vh.py            (needs contracts/detections.geojson built with vh_contrast_db)
Writes reports/vh_tuning.json. Variants are picked on the odd review sheets and checked on the even ones, as for RULE.
  and:  ship = VV rule AND vh_contrast_db >= t                     (VH as a precision gate)
  or:   ship = VV rule OR (vh >= t, contrast >= c2, snr_z >= z2)   (VH rescues weaker VV targets; coast rule kept)
Counts are raw reviewed-chip counts inside the ship class (S confirmed, N rejected, U unsure), not band-weighted.
"""
import json
import sys

import review_apply as ra
from features import RULE


def radar_class(p, rule):
    if p["radar_class"] == "likely_fixed":
        return "likely_fixed"
    c, z, land, vh = p["contrast_db"], p["snr_z"], p["land_distance_m"], p["vh_contrast_db"]
    coast_ok = land is None or land >= RULE["coast_m"] or c >= RULE["coast_contrast_db"]
    vv_ok = c >= RULE["min_contrast_db"] and z >= RULE["min_snr_z"] and coast_ok
    if rule["kind"] == "and":
        return "ship" if vv_ok and vh >= rule["t"] else "uncertain"
    if rule["kind"] == "or":
        alt = vh >= rule["t"] and c >= rule["c2"] and z >= rule["z2"] and coast_ok
        return "ship" if vv_ok or alt else "uncertain"
    return "ship" if vv_ok else "uncertain"


def score(rows, feats, rule):
    ship = [r for r in rows if radar_class(feats[r["id"]], rule) == "ship"]
    conf = sum(r["verdict"] == "confirmed" for r in rows)
    s = sum(r["verdict"] == "confirmed" for r in ship)
    n = sum(r["verdict"] == "rejected" for r in ship)
    return {"ship_class_n": sum(radar_class(p, rule) == "ship" for p in feats.values()), "reviewed_in_ship": len(ship),
            "S": s, "N": n, "U": len(ship) - s - n, "precision_strict": round(s / max(1, len(ship)), 3),
            "keeps_confirmed": f"{s}/{conf}", "keeps_share": round(s / conf, 3)}


def main():
    _, _, feats, rows = ra.load()
    if any(p.get("vh_contrast_db") is None for p in feats.values()):
        sys.exit("detections.geojson has no vh_contrast_db: run build_catalog.py without --no-vh first")
    odd = [r for r in rows if r["sheet"] % 2 == 1]
    even = [r for r in rows if r["sheet"] % 2 == 0]
    rules = [{"kind": "v2"}] + [{"kind": "and", "t": t} for t in (8, 10, 12, 14, 16)]
    rules += [{"kind": "or", "t": t, "c2": c2, "z2": z2} for t in (14, 16, 18, 20) for c2 in (12, 15) for z2 in (8, 9)]
    out = [{"rule": r, "tune_odd": score(odd, feats, r), "check_even": score(even, feats, r)} for r in rules]
    base = out[0]
    better = [o for o in out[1:] if o["tune_odd"]["precision_strict"] > base["tune_odd"]["precision_strict"]
              or o["tune_odd"]["keeps_share"] > base["tune_odd"]["keeps_share"]]
    held = [o for o in better if o["check_even"]["precision_strict"] >= base["check_even"]["precision_strict"]
            and o["check_even"]["keeps_share"] >= base["check_even"]["keeps_share"]]
    verdict = ("adopt " + json.dumps(held[0]["rule"])) if held else \
        "keep v2 rule: no VH variant that helps on the odd sheets also holds on the even sheets"
    report = {"what": "VH rule variants vs the v2 VV-only rule, on the 120-chip visual review (odd sheets tune, even sheets check)",
              "verdict": verdict, "results": out}
    (ra.ROOT / "ml/reports/vh_tuning.json").write_text(json.dumps(report, indent=1))
    for o in out:
        print(f"{json.dumps(o['rule']):45s} odd {o['tune_odd']['precision_strict']:.2f}/{o['tune_odd']['keeps_share']:.2f}"
              f"  even {o['check_even']['precision_strict']:.2f}/{o['check_even']['keeps_share']:.2f}")
    print(verdict)


if __name__ == "__main__":
    main()
