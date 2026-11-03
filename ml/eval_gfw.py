"""Recall of CFAR runs against Global Fishing Watch's SAR targets (an independent detector on the same scenes, not ground truth).

Usage: .venv/bin/python eval_gfw.py [label=runs/dir ...]     (default: shipped=runs; needs ml/reports/gfw_reference.json
                                                              from `python -m ais.gfw_join`)
A GFW target counts if it lies inside the 40 km search circle; it is found if a detection of the same pass is within 1 km
(one to one, as in ais/gfw_join.py). Recall is also split by our static sea mask: targets the mask calls land (ships at berth
in port basins) cannot be found by design. Writes ml/reports/eval_gfw.json.
"""
import json
import sys
from pathlib import Path

import numpy as np

from ais.gfw_join import in_circle, pair

ML = Path(__file__).resolve().parent
MASK = np.load(ML / "assets" / "sea_mask.npz")


def on_sea_mask(lon, lat):
    i = int(np.floor((lat - float(MASK["lat0"])) / float(MASK["res"])))
    j = int(np.floor((lon - float(MASK["lon0"])) / float(MASK["res"])))
    g = MASK["mask"]
    return bool(0 <= i < g.shape[0] and 0 <= j < g.shape[1] and g[i, j])


def score(run_dir, reference):
    rows, tot = [], {"targets": 0, "found": 0, "sea_targets": 0, "sea_found": 0, "detections": 0, "unpaired_detections": 0}
    for p in reference["passes"]:
        ts = p["scene_id"].split("_")[1]
        dets = json.loads((run_dir / f"cfar_{ts}.json").read_text())["detections"]
        theirs = [t for t in p["targets"] if in_circle(t["lon"], t["lat"])]
        found = {j for j, _ in pair(dets, theirs).values()}
        sea = [j for j, t in enumerate(theirs) if on_sea_mask(t["lon"], t["lat"])]
        allpairs = pair(dets, p["targets"])
        r = {"scene_id": p["scene_id"], "targets": len(theirs), "found": len(found), "sea_targets": len(sea),
             "sea_found": len(found & set(sea)), "detections": len(dets), "unpaired_detections": len(dets) - len(allpairs)}
        rows.append(r)
        for k in tot:
            tot[k] += r[k]
    tot["recall"] = round(tot["found"] / tot["targets"], 3)
    tot["recall_on_sea_mask"] = round(tot["sea_found"] / tot["sea_targets"], 3)
    return {"passes": rows, "total": tot}


def main():
    reference = json.loads((ML / "reports" / "gfw_reference.json").read_text())
    runs = dict(a.split("=", 1) for a in sys.argv[1:]) or {"shipped_k8": "runs"}
    out = {"what": "Recall vs Global Fishing Watch SAR targets inside the 40 km search circle, 1 km one-to-one gate. GFW is an "
                   "independent detector on the same scenes (weak near quays, drops small boats), not ground truth.",
           "passes_scored": [p["scene_id"] for p in reference["passes"]],
           "runs": {label: score(ML / d, reference) for label, d in runs.items()}}
    (ML / "reports" / "eval_gfw.json").write_text(json.dumps(out, indent=1))
    for label, s in out["runs"].items():
        t = s["total"]
        print(f"{label:22s} recall {t['found']}/{t['targets']} = {t['recall']:.1%}   on sea mask {t['sea_found']}/{t['sea_targets']}"
              f" = {t['recall_on_sea_mask']:.1%}   detections {t['detections']} ({t['unpaired_detections']} with no GFW target)")


if __name__ == "__main__":
    main()
