# ML verification status

| Item | How verified / how it will be | Status |
|---|---|---|
| Tiling, NMS, pixel->lon/lat via GCPs | Synthetic 2400x2400 scene with known GCPs (HRSID mosaic): geocode error 7.5 m max (< 1 px at 10 m); detections landed on real labelled ships | DONE (synthetic) |
| Port bounding boxes | Compared with OpenStreetMap extents for Jebel Ali (24.96-25.00N, 55.04-55.08E) and Khalifa Port (24.79-24.83N, 54.63-54.67E); our boxes contain both and add approaches | DONE (generous boxes) |
| Real scenes exist | Public catalogue: 4 Sentinel-1 GRDH scenes over Jebel Ali since 24 Oct (24, 27, 30 Oct, 2 Nov) | DONE |
| Downloader | `fetch_scenes.py --list` works unauthenticated; `--download` needs `ml/.env` | LIST DONE, DOWNLOAD PENDING login |
| Model accuracy | Colab train, then `ml/reports/metrics.json` on HRSID official test split | PENDING Colab |
| Brightness scaling on real Sentinel-1 DN | Run infer.py on a real scene, overlay boxes, eyeball | PENDING scene + model |
| Domain gap (HRSID -> Sentinel-1 10 m) | Compare YOLO counts vs a CFAR baseline on the same scene; spot-check 20 detections | PENDING scene + model |
| Port capacities, AIS | Capacities are assumptions; AIS is simulated and labelled `ais_source: simulated` | NOT VERIFIABLE (disclosed) |

Notes: the epoch-1 checkpoint found only 2 of 21 ships in the synthetic scene (both correct); it is undertrained, so that is no accuracy figure.
