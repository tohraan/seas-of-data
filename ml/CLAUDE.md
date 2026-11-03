# ml/ — owner: Tohraan (ml-agent)
Ship detection on Sentinel-1 SAR: fine-tune a pretrained YOLO (ultralytics) on a public SAR ship dataset (SSDD / HRSID / xView3),
run on Gulf scenes (Jebel Ali, Khalifa Port, Strait of Hormuz), match detections to AIS (real sample or clearly-labelled simulated),
flag dark vessels, count port activity. Output ONLY the files described in `contracts/`.
Use `uv` with Python 3.12 (`uv venv --python 3.12`); Python 3.14 lacks some ML wheels. Train in Colab if no GPU.
Do not touch `dashboard/` or `cad/`.

## v2 pipeline (3 Nov 2026) - read before changing anything
- `ml/run_all.sh` rebuilds `contracts/` from the four scenes: `cfar.py` (k=8, centre 54.86 24.91, 40 km) -> `build_catalog.py` (ids, radar features, classes, chips, port counts) -> `review_apply.py` (verdicts, `metrics_gulf.json`) -> `manifest.py` (hashes, catalogue ids) -> tests.
- No AIS is joined: `status = not_checked`, `dark = null`. `postprocess.py` is legacy simulation and refuses to run without `--legacy-simulated`. Never put simulated AIS in the headline contract.
- AIS plumbing: `ml/ais/match.py` (tested), `capture.py` (aisstream, needs `AISSTREAM_KEY`), `gfw.py` (Global Fishing Watch, needs `GFW_TOKEN`, response layout unverified until first call).
- `radar_class` rule lives in `features.py`; it was tuned on half of the 120-chip review and checked on the other half. If you change the rule, re-run `review_apply.py --halves` and say so in `VERIFICATION.md`.
