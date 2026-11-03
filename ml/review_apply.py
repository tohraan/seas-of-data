"""Apply visual-review verdicts (reports/review_verdicts.json) to the sample (reports/review_sample.json).
Writes contracts/labels.csv and contracts/metrics_gulf.json, and stamps `review` on contracts/detections.geojson.

Precision is estimated on a stratified sample (equal draws per size band), so the overall figure re-weights each
band by its share of the catalogue. Interval: 5,000-resample stratified bootstrap. U (unsure) is counted two ways:
strict (U = not a ship) and lenient (U dropped). This is a visual review of 10 m radar chips, NOT ground truth.
Usage: .venv/bin/python review_apply.py [--halves]   (prints half-sample figures used for detector tuning)
"""
import csv, json, random, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CH = ROOT / "contracts"
V = {"S": "confirmed", "N": "rejected", "U": "unsure"}


def wilson(k, n, z=1.96):
    if n == 0:
        return (None, None)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return round(c - h, 3), round(c + h, 3)


def load():
    samp = json.loads((ROOT / "ml/reports/review_sample.json").read_text())
    ver = json.loads((ROOT / "ml/reports/review_verdicts.json").read_text())
    feats = {f["properties"]["id"]: f["properties"] for f in json.loads((CH / "detections.geojson").read_text())["features"]}
    rows = []
    for si, (ids, vs) in enumerate(zip(samp["sheets"], ver["sheets"]), 1):
        assert len(ids) == len(vs), f"sheet {si}"
        for pos, (i, v) in enumerate(zip(ids, vs), 1):
            rows.append({"id": i, "sheet": si, "pos": pos, "verdict": V[v], "size_class": feats[i]["size_class"], "port": feats[i]["port"]})
    return samp, ver, feats, rows


def band(sc):
    return "large+" if sc in ("large", "very_large") else sc


def estimate(rows, feats, strict, rng):
    pops, by = {}, {}
    for p in feats.values():
        pops[band(p["size_class"])] = pops.get(band(p["size_class"]), 0) + 1
    for r in rows:
        by.setdefault(band(r["size_class"]), []).append(r["verdict"])
    def stat(sample):
        tot = sum(pops[b] for b in sample); acc = 0.0
        for b, vs in sample.items():
            ok = sum(v == "confirmed" for v in vs)
            den = len(vs) if strict else sum(v != "unsure" for v in vs)
            acc += pops[b] / tot * (ok / den if den else 0)
        return acc
    point = stat(by)
    boots = sorted(stat({b: [rng.choice(vs) for _ in vs] for b, vs in by.items()}) for _ in range(5000))
    return round(point, 3), round(boots[125], 3), round(boots[4874], 3), {b: (sum(v == "confirmed" for v in vs), len(vs)) for b, vs in by.items()}


def class_block(rows, feats, rng):
    """Precision inside each radar_class, plus the share of reviewed ships that the `ship` class keeps (weighted by band)."""
    out = {}
    for cls in ("ship", "uncertain", "likely_fixed"):
        fc = {i: p for i, p in feats.items() if p["radar_class"] == cls}
        sub = [r for r in rows if r["id"] in fc]
        if not sub:
            out[cls] = {"catalogue_n": len(fc), "reviewed_n": 0}
            continue
        st, le = estimate(sub, fc, True, rng), estimate(sub, fc, False, rng)
        out[cls] = {"catalogue_n": len(fc), "reviewed_n": len(sub),
                    "confirmed": sum(r["verdict"] == "confirmed" for r in sub), "rejected": sum(r["verdict"] == "rejected" for r in sub),
                    "unsure": sum(r["verdict"] == "unsure" for r in sub),
                    "precision_strict": {"estimate": st[0], "ci95": [st[1], st[2]]},
                    "precision_lenient": {"estimate": le[0], "ci95": [le[1], le[2]]}}
    pops = {}
    for p in feats.values():
        pops[band(p["size_class"])] = pops.get(band(p["size_class"]), 0) + 1
    nb = {}
    for r in rows:
        nb[band(r["size_class"])] = nb.get(band(r["size_class"]), 0) + 1
    w = lambda r: pops[band(r["size_class"])] / nb[band(r["size_class"])]
    conf = [r for r in rows if r["verdict"] == "confirmed"]
    kept = sum(w(r) for r in conf if feats[r["id"]]["radar_class"] == "ship")
    out["ship_class_keeps_share_of_reviewed_ships"] = round(kept / sum(w(r) for r in conf), 3)
    return out


def main():
    samp, ver, feats, rows = load()
    rng = random.Random(1)
    if "--halves" in sys.argv:
        for name, keep in (("tune (odd sheets)", lambda r: r["sheet"] % 2 == 1), ("report (even sheets)", lambda r: r["sheet"] % 2 == 0)):
            sub = [r for r in rows if keep(r)]
            cb = class_block(sub, feats, rng)
            print(name, len(sub), "all strict", estimate(sub, feats, True, rng)[:3], "| ship class", cb["ship"].get("precision_strict"),
                  "n", cb["ship"]["reviewed_n"], "| keeps", cb["ship_class_keeps_share_of_reviewed_ships"])
        return
    with open(CH / "labels.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["id", "verdict", "reviewer", "size_class", "port"])
        for r in rows:
            w.writerow([r["id"], r["verdict"], "claude-visual", r["size_class"], r["port"] or ""])
    n = len(rows); k = sum(r["verdict"] == "confirmed" for r in rows)
    nn = sum(r["verdict"] == "rejected" for r in rows); u = n - k - nn
    strict = estimate(rows, feats, True, rng); lenient = estimate(rows, feats, False, rng)
    metrics = {
        "what": "Share of detections that look like ships on visual review of the 10 m Sentinel-1 radar chips (precision proxy).",
        "not": "NOT ground truth: no AIS or survey confirms these. Recall cannot be measured. Reviewer is the ML agent, pending human spot-check.",
        "sample": {"n": n, "seed": samp["seed"], "per_band": samp["per_band"], "confirmed": k, "rejected": nn, "unsure": u,
                   "design": "stratified random draw from the 250 detections, equal draws per size band, drawn before any detector change"},
        "precision_strict_unsure_counts_as_not_ship": {"estimate": strict[0], "ci95": [strict[1], strict[2]]},
        "precision_lenient_unsure_dropped": {"estimate": lenient[0], "ci95": [lenient[1], lenient[2]]},
        "by_radar_class": class_block(rows, feats, rng),
        "rule": json.loads((ROOT / "ml/reports/build_meta.json").read_text())["rule"],
        "rule_note": "Thresholds picked on the odd-numbered review sheets (63 chips) and checked on the even ones (57 chips); the review labels were written before the rule existed.",
        "by_size_band": {b: {"confirmed": c, "n": t, "raw_share": round(c / t, 3), "wilson95": list(wilson(c, t))} for b, (c, t) in strict[3].items()},
        "catalogue_size": len(feats),
    }
    (CH / "metrics_gulf.json").write_text(json.dumps(metrics, indent=1))
    verdict = {r["id"]: r["verdict"] for r in rows}
    fc = json.loads((CH / "detections.geojson").read_text())
    for f in fc["features"]:
        f["properties"]["review"] = verdict.get(f["properties"]["id"], "unreviewed")
    (CH / "detections.geojson").write_text(json.dumps(fc, indent=1))
    print(json.dumps({k_: metrics[k_] for k_ in ("precision_strict_unsure_counts_as_not_ship", "by_radar_class")}, indent=1))


if __name__ == "__main__":
    main()
