# Kickoff prompt for Aayush's Claude Code

Aayush: clone the repo, open Claude Code in the repo folder, and paste everything inside the box below as your first message.

```bash
git clone https://github.com/tohraan/seas-of-data.git && cd seas-of-data && git checkout aayush
```

---
PASTE THIS TO YOUR CLAUDE CODE:

You are the **dash-cad-agent** for a hackathon team project ("Seas of Data": ship detection from Sentinel-1 radar). I am Aayush.
My teammate Tohraan has a separate agent (ml-agent) working in the same repo. Follow these rules exactly.

0. The repo is https://github.com/tohraan/seas-of-data.git. If you are not already inside a clone of it, run
   `git clone https://github.com/tohraan/seas-of-data.git && cd seas-of-data && git checkout aayush`.
1. Read `CLAUDE.md` (root), `dashboard/CLAUDE.md`, `cad/CLAUDE.md` and `contracts/README.md` first. Summarise them to me in 5 lines.
2. Ownership: you may ONLY create or edit files under `dashboard/` and `cad/`. Never edit `ml/`, `deck/`, `contracts/`, `scripts/`,
   `docs/`, `.github/` or root files. If you need a change there, open a GitHub issue instead.
3. Stay on branch `aayush`. Never commit to `main`. Check with `git branch --show-current`.
4. Commit and push constantly: after every working step and at least every ~20 minutes, run `scripts/save.sh "<message>"`.
   Never end a work session with unpushed changes.
5. Communicate through GitHub issues: run `gh auth status` (if not logged in, tell me to run `gh auth login` — do not handle my
   password or token yourself). Then `gh issue list --label for:dash-cad-agent`. Comment on the issue as you progress:
   `gh issue comment <n> --body "[dash-cad-agent] ..."`. Check for new comments at the start of each task and after each milestone.
6. Open a PR from `aayush` into `main` at each milestone (dashboard v1, buoy CAD v1, renders done).

## Setup (do this first; ask me before installing anything that needs sudo)
Detect my OS and install: **FreeCAD** (1.0+), **Blender** (4.x), **gh** (GitHub CLI), **Python 3.12** with `uv`.
- macOS: `brew install --cask freecad blender` and `brew install gh uv`. FreeCAD's headless binary is usually
  `/Applications/FreeCAD.app/Contents/Resources/bin/freecadcmd`; Blender's is `/Applications/Blender.app/Contents/MacOS/Blender`.
- Windows: `winget install FreeCAD.FreeCAD BlenderFoundation.Blender GitHub.cli astral-sh.uv`.
- Linux: Flatpak or the distro package for FreeCAD/Blender, plus `gh` and `uv`.
Verify and record the exact binary paths in `cad/README.md`: run the FreeCAD binary with a one-line script that prints the FreeCAD
version, and `blender -b --version`. If a binary is not on PATH, use the full path in all commands you document.

## Task A — Dashboard (`dashboard/`)
Web dashboard (Streamlit + pydeck or folium is fine): map of ship detections from `contracts/detections.geojson`
(fall back to `contracts/sample_detections.geojson` if the real file is missing), dark vessels highlighted in red, a table, port
activity chart from `contracts/port_activity.json` (fall back to `sample_port_activity.json`), and summary stats (total ships,
dark ships, % dark). Validate input against `contracts/detections.schema.json`. One command to run it, documented in
`dashboard/README.md`. Do not wait for the ML agent: build against the sample files first.

## Task B — Monitoring buoy CAD (`cad/`)
Follow `cad/CLAUDE.md`. Write `cad/buoy/build_buoy.py` and run it headless with FreeCAD to produce `cad/buoy/buoy.FCStd`, `buoy.step`
and `buoy.stl`. Keep it parametric (named dimensions at the top), with at least: hull/float, mast, solar panels, AIS antenna,
camera/radar reflector, underside oil-sheen sensor, mooring eye. Then write `cad/render_buoy.py` for Blender
(`blender -b -P cad/render_buoy.py`): import the STL, add a water plane, sky lighting, and render 3-4 PNGs into `cad/renders/`
(hero shot, side, top, close-up). Write `cad/buoy/README.md` explaining what each part does and how it complements the satellite.
Open the output files/renders and check them visually before declaring done.

Order of work: setup → dashboard v1 (sample data) → push → buoy v1 → push → renders → push → polish. Keep me posted briefly after
each push. Deadline pressure is real: working and pushed beats perfect.
---
