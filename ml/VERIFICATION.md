# ML verification status (v2, 3 Nov 2026)

| Item | How verified | Status |
|---|---|---|
| Detections come from real Sentinel-1 | Four IW GRDH VV scenes, sha256 + Copernicus catalogue ids in `contracts/manifest.json`; the Planetary Computer copy of the 2 Nov scene is pixel-identical to the Copernicus file on a 512 px window | DONE |
| Reproducible | `cfar.py --k 8 --center 54.86 24.91 --radius-km 40` regenerates exactly the same 40/80/57/73 positions from the local files, and the 24 Oct scene read remotely from the public mirror gives the same 40 | DONE |
| Every detection checkable by eye | 128 px radar chip + 7.7 km context crop per detection (`contracts/chips/`) | DONE |
| Precision on Gulf scenes | Seeded stratified random sample of 120 chips, visual review (`labels.csv`). Whole catalogue about 57% ship-like (95% CI 49-65%); `ship` class 94% (88-99%), held-out half 95%; `uncertain` about 9%. Reviewer: ML agent, **no independent ground truth**; human spot-check pending | DONE, with that limit |
| Recall | Cannot be measured without ground truth (no labelled Gulf scenes, no real AIS). The `ship` class keeps about 87% of the chips judged ships; true recall is unknown | NOT MEASURABLE |
| Geocoding | Synthetic scene with known GCPs: max error 7.5 m | DONE (synthetic) |
| HRSID benchmark (YOLO11s): P 0.91, R 0.82, mAP50 0.90 | Colab run, 1,962 test images | DONE, but **not** a Gulf accuracy: finer pixels. YOLO finds far fewer targets than CFAR on our scenes (7 vs 40, 12 vs 80 at conf 0.25), so CFAR is the production detector |
| AIS match / dark vessels | Matcher written and unit-tested (`ml/ais/match.py`); refuses to call anything dark unless AIS coverage in the scene window is proven. aisstream collector and Global Fishing Watch client written, **not yet run** (no keys) | NOT DONE: no real AIS joined to these four passes |
| Port boxes | Compared with OpenStreetMap extents for Jebel Ali and Khalifa Port; generous | DONE (approximate) |
| Berth occupancy / activity index | Occupancy used assumed capacities and was removed. `activity_index` stays as a raw-count baseline vs the 4-pass median | REMOVED / BASELINE |
| Study area | Limited to the static sea mask, 54.45-55.30 E, 24.55-25.30 N, not the scene (53.7-56.6 E). Hormuz is not covered | LIMIT |
