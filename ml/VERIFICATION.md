# ML verification status (v3, 3 Nov 2026)

| Item | How verified | Status |
|---|---|---|
| Detections come from real Sentinel-1 | Four IW GRDH VV scenes, sha256 + Copernicus catalogue ids in `contracts/manifest.json`; the Planetary Computer copy of the 2 Nov scene is pixel-identical to the Copernicus file on a 512 px window | DONE |
| Reproducible | `cfar.py --k 8 --center 54.86 24.91 --radius-km 40` regenerates exactly the same 40/80/57/73 positions from the local files, and the 24 Oct scene read remotely from the public mirror gives the same 40 | DONE |
| Every detection checkable by eye | 128 px radar chip + 7.7 km context crop per detection (`contracts/chips/`) | DONE |
| Precision on Gulf scenes | Seeded stratified random sample of 120 chips, visual review (`labels.csv`). Whole catalogue about 57% ship-like (95% CI 49-65%); `ship` class 94% (88-99%), held-out half 95%; `uncertain` about 9%. Reviewer: ML agent, **no independent ground truth**; human spot-check pending | DONE, with that limit |
| Recall | Against Global Fishing Watch's own SAR targets (an independent detector on the same scenes, **not ground truth**), 3 passes, 40 km circle, 1 km gate: **59 of 81 = 73%**; 79% of the targets on our sea mask (`ml/eval_gfw.py`, `reports/eval_gfw.json`). Of the 22 misses, 7 are ships at berth that the static sea mask calls land; most of the rest are faint | MEASURED vs GFW, with that limit |
| Geocoding | Synthetic scene with known GCPs: max error 7.5 m | DONE (synthetic) |
| HRSID benchmark (YOLO11s): P 0.91, R 0.82, mAP50 0.90 | Colab run, 1,962 test images | DONE, but **not** a Gulf accuracy: finer pixels. YOLO finds far fewer targets than CFAR on our scenes (7 vs 40, 12 vs 80 at conf 0.25), so CFAR is the production detector |
| AIS match / dark vessels | `python -m ais.gfw_join` pairs each detection with GFW's SAR targets (AIS-matched or not) within 1 km, one to one; reproduces the dashboard's independent check exactly. 48 detections match an AIS-broadcasting vessel, 18 a GFW target with no AIS (16 of them in the `ship` class), 111 no GFW target; 2 Nov (73) not published by GFW yet. Result in `contracts/ais_check.json`, tied to the sha256 of `detections.geojson`. `no_ais` is a lead, not a verdict | DONE for 3 of 4 passes |
| Port boxes | Compared with OpenStreetMap extents for Jebel Ali and Khalifa Port; generous | DONE (approximate) |
| Berth occupancy / activity index | Occupancy used assumed capacities and was removed. `activity_index` stays as a raw-count baseline vs the 4-pass median | REMOVED / BASELINE |
| Study area | Limited to the static sea mask, 54.45-55.30 E, 24.55-25.30 N, not the scene (53.7-56.6 E). Hormuz is not covered | LIMIT |
| Class rule cross-check vs GFW | In the 3 GFW passes, 57 of 79 `ship`-class detections (72%) sit on a GFW target, against 4 of 91 `uncertain` (4%): an independent agreement with the visual review (94% vs 9%) | DONE |
| VH (cross-pol) confirmation | `vh_contrast_db` added per detection (same contrast definition, read from the VH band). VH gates and VH rescues were tuned on the odd review sheets and checked on the even ones; none beat the VV-only rule held out (`reports/vh_tuning.json`), so the rule is unchanged and VH is evidence only | TRIED, NOT ADOPTED |
| Hysteresis CFAR (`--k-grow 6`) | Recall vs GFW 72.8% -> 77.8% (gate 80%) for 79 more detections, 74 of them with no GFW target (`reports/hysteresis_eval.json`). Default stays k=8, output byte-identical to v2 | TRIED, NOT ADOPTED |
