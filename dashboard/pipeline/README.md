# Radar evidence pipeline

Runs the trained YOLO model on the real Sentinel-1 passes behind `contracts/detections.geojson`, then measures every detection from the radar pixels. The dashboard doesn't need this folder, the model or the scenes to run.

**Status: work in progress.** `yolo_scan.py` works and resumes where it stopped. `build_evidence.py` hasn't been run end to end yet, and the dashboard doesn't read its output yet.

## Data sources
- **Scenes:** Copernicus Sentinel-1 GRD, read from the public [Microsoft Planetary Computer](https://planetarycomputer.microsoft.com/dataset/sentinel-1-grd) mirror. No login needed, and only the study area is downloaded.
- **Model:** `data/model/best.pt`, which Git ignores. If a browser unpacked your copy into a folder, rebuild it with `repack_model.py`.
- **Sea mask:** `ml/assets/sea_mask.npz`. It sets the study area, 54.45-55.30 E and 24.55-25.30 N.

## Run
Run these from `dashboard/pipeline`. The first run installs a CPU-only environment of about 1.5 GB.

```bash
# Scan each pass with the model, about 4-5 minutes per pass on CPU. Finished passes are skipped.
uv run python yolo_scan.py --weights ../../data/model/best.pt --out ../../data/yolo_runs

# Compare the detectors, measure each target, and write ../derived/
uv run python build_evidence.py --weights ../../data/model/best.pt --runs ../../data/yolo_runs
```

## What gets measured
| Measurement | How |
|---|---|
| Detector agreement | YOLO at 0.25 or above against CFAR, paired within 250 m |
| VV and VH contrast | Brightest point within about 40 m, in dB above the surrounding water |
| Confirmed in VH | Brighter than 99% of 3,000 random open-water points in that pass and band |
| Radar length and hull direction | Shape of the bright blob. A hull axis has no front or back, so direction of travel stays unknown |
| Likely fixed | Bright at the same spot in every pass, including the 21 Oct pass that isn't in the contract |

## Test
```bash
uv run python -m pytest tests
```
