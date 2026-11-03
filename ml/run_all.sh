#!/usr/bin/env bash
# Rebuild contracts/ from the four Sentinel-1 scenes. Uses ml/data/scenes/*.tiff if present, otherwise reads the same
# scenes from the public Planetary Computer mirror (no login). Run from anywhere:  ml/run_all.sh [--no-chips]
set -euo pipefail
cd "$(dirname "$0")"
PY=.venv/bin/python
[ -x "$PY" ] || PY=python3
SCENES="S1C_20261024T142351 S1C_20261027T021440 S1D_20261030T142416 S1D_20261102T021455"
mkdir -p runs
for s in $SCENES; do
  ts=${s#*_}
  local_tiff=$(ls data/scenes/*"$ts"*_vv.tiff 2>/dev/null | head -1 || true)
  src=${local_tiff:-$($PY fetch_pc.py "$s")}
  $PY cfar.py "$src" --out "runs/cfar_$ts.json" --center 54.86 24.91 --radius-km 40 --k 8 --scene-id "$s"
done
$PY build_catalog.py runs/cfar_2026*T*.json "$@"
$PY review_apply.py > /dev/null     # re-stamps review verdicts and re-computes contracts/metrics_gulf.json
$PY manifest.py ${OFFLINE:+--offline}
$PY -m pytest -q tests
