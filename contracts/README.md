# Contracts v2 (owner: Tohraan / ML agent)

The ONLY interface between `ml/` and `dashboard/`. Need a field? Open an issue labelled `contract-change`; do not edit these files.

| File | What it is |
|---|---|
| `detections.geojson` | 250 radar detections from 4 real Sentinel-1 passes. Schema: `detections.schema.json`. |
| `chips/<id>.png`, `chips/<id>_ctx.jpg` | The radar picture of every detection: 128 px VV chip (1.3 km) and a 7.7 km context crop. Image axes follow the satellite track, not north. |
| `manifest.json` | Provenance: ESA product names, sha256, Copernicus catalogue ids, Planetary Computer ids, CFAR parameters and stage counts, area searched, how to reproduce. |
| `metrics_gulf.json` | Measured precision from a visual review of 120 random chips (not ground truth). |
| `labels.csv` | The review verdicts behind `metrics_gulf.json` (`confirmed / rejected / unsure`). |
| `port_activity.json` | Per pass, per port: count of `radar_class = ship` detections, by size. A baseline, not a trend. |
| `sample_*` | Fake data, for tests only. |

## What is real and what is not
- **Real:** every detection is a bright target found by a CFAR detector in a real Sentinel-1 VV scene (listed in `manifest.json`).
- **Not joined yet:** AIS. `status = not_checked`, `ais_source = none`, `dark = null`, `mmsi = null` for every detection. Nothing in this release says a ship is dark. Real AIS plumbing lives in `ml/ais/` (matcher tested, aisstream collector and Global Fishing Watch client need keys).
- **`confidence`** is the CFAR peak z-score divided by 20. It is a strength score, not a probability.
- **`length_m`** comes from the bounding box of the bright blob (10 m pixels): good to about +/- 20 m, no use for naming a ship.

## Reading a detection
`radar_class`: `ship` = bright enough over the local sea and not hugging the coast (rule in `ml/features.py`); `uncertain` = fails that rule (faint, or within 600 m of land unless very bright); `likely_fixed` = detected at the same spot (within 150 m) in every pass, so a moored vessel, platform or buoy rather than traffic. `persistence` = number of passes with a detection at that spot. `review` = verdict from `labels.csv` where a chip was reviewed.
Measured on the review sample: `ship` class about 94% ship-like, `uncertain` about 9% (see `metrics_gulf.json` for intervals and caveats).

## Rebuild
`ml/run_all.sh` rebuilds everything from the scenes (local copy, or the public Planetary Computer mirror when absent).
