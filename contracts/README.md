# Contracts v3 (owner: Tohraan / ML agent)

The ONLY interface between `ml/` and `dashboard/`. Need a field? Open an issue labelled `contract-change`; do not edit these files.

| File | What it is |
|---|---|
| `detections.geojson` | 250 radar detections from 4 real Sentinel-1 passes. Schema: `detections.schema.json`. |
| `chips/<id>.png`, `chips/<id>_ctx.jpg` | The radar picture of every detection: 128 px VV chip (1.3 km) and a 7.7 km context crop. Image axes follow the satellite track, not north. |
| `manifest.json` | Provenance: ESA product names, sha256, Copernicus catalogue ids, Planetary Computer ids, CFAR parameters and stage counts, area searched, how to reproduce. |
| `ais_check.json` | Independent AIS check (new in v3): per detection `check` = `ais_match` / `no_ais` / `no_gfw_target` / `not_available`, `offset_m`, and vessel `name, flag, type, imo, mmsi, vessel_id` for `ais_match`. Per pass totals and recall vs GFW. Tied to `detections.geojson` by `contract_sha256`: if they differ, ignore it. Credit "Powered by Global Fishing Watch". |
| `metrics_gulf.json` | Measured precision from a visual review of 120 random chips (not ground truth). |
| `labels.csv` | The review verdicts behind `metrics_gulf.json` (`confirmed / rejected / unsure`). |
| `port_activity.json` | Per pass, per port: count of `radar_class = ship` detections, by size. A baseline, not a trend. |
| `sample_*` | Fake data, for tests only. |

## What is real and what is not
- **Real:** every detection is a bright target found by a CFAR detector in a real Sentinel-1 VV scene (listed in `manifest.json`).
- **AIS:** `detections.geojson` itself still carries no AIS verdict (`status = not_checked`, `dark = null`, `mmsi = null`). The AIS check lives beside it in `ais_check.json`: Global Fishing Watch's own detections on the same Sentinel-1 scenes, matched or not to AIS, paired with ours within 1 km. `no_ais` means GFW also saw a target there and found no AIS for it: a lead for a patrol, not proof a ship is dark (reception gaps and ships at berth do this too). GFW has not published 2 Nov yet (`not_available`).
- **`vh_contrast_db`** (new in v3): the same contrast measured in the VH (cross-polarisation) band. Evidence only; the class rule does not use it (`vh_confirmed` is null). Tested and not adopted, see `ml/VERIFICATION.md`.
- **`confidence`** is the CFAR peak z-score divided by 20. It is a strength score, not a probability.
- **`length_m`** comes from the bounding box of the bright blob (10 m pixels): good to about +/- 20 m, no use for naming a ship.

## Reading a detection
`radar_class`: `ship` = bright enough over the local sea and not hugging the coast (rule in `ml/features.py`); `uncertain` = fails that rule (faint, or within 600 m of land unless very bright); `likely_fixed` = detected at the same spot (within 150 m) in every pass, so a moored vessel, platform or buoy rather than traffic. `persistence` = number of passes with a detection at that spot. `review` = verdict from `labels.csv` where a chip was reviewed.
Measured on the review sample: `ship` class about 94% ship-like, `uncertain` about 9% (see `metrics_gulf.json` for intervals and caveats). Independently, 72% of `ship`-class detections sit on a Global Fishing Watch target versus 4% of `uncertain`.

## Rebuild
`ml/run_all.sh` rebuilds everything from the scenes (local copy, or the public Planetary Computer mirror when absent), then `cd ml && .venv/bin/python -m ais.gfw_join` refreshes `ais_check.json` (needs `GFW_TOKEN` in `ml/.env`).
