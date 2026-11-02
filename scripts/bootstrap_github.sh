#!/usr/bin/env bash
# Run ONCE by Tohraan after the GitHub repo exists and `origin` is set. Creates labels, branches and the starter issues.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
git push -u origin main
for b in tohraan aayush; do git branch -f "$b" main && git push -u origin "$b"; done
for l in "for:ml-agent|1d76db" "for:dash-cad-agent|0e8a16" "contract-change|fbca04" "blocked|d93f0b"; do
  gh label create "${l%%|*}" --color "${l##*|}" --force
done
gh issue create --title "ML: ship detector (pretrained YOLO fine-tuned on SAR ships)" --label for:ml-agent \
  --body "Owner: Tohraan. Get Sentinel-1 + SSDD/HRSID/xView3, fine-tune, run on Gulf scenes. Output contracts/detections.geojson. Branch: tohraan."
gh issue create --title "ML: dark-vessel matching + port activity index" --label for:ml-agent \
  --body "Match detections with AIS (real sample or labelled simulation), flag dark vessels, produce contracts/port_activity.json."
gh issue create --title "Dashboard: map of detections, dark vessels, port activity" --label for:dash-cad-agent \
  --body "Owner: Aayush. Build in dashboard/ using contracts/sample_*.json until real files land. One-command run documented in dashboard/README.md. Branch: aayush."
gh issue create --title "CAD: parametric monitoring buoy in FreeCAD + Blender renders" --label for:dash-cad-agent \
  --body "Owner: Aayush. See cad/CLAUDE.md. Deliver cad/buoy/buoy.step (+FCStd, STL), build_buoy.py, render_buoy.py, renders/*.png."
echo "Done. Add Aayush as collaborator: gh api -X PUT repos/<owner>/<repo>/collaborators/<aayush-username>"
