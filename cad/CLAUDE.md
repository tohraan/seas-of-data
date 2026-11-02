# cad/ — owner: Aayush (dash-cad-agent)
Design a maritime monitoring buoy ("Seas of Data" CAD deliverable) in FreeCAD, scripted so it is reproducible, then render it with Blender.
Concept: floating solar-powered buoy that verifies satellite detections on site: AIS receiver antenna, camera/radar reflector mast,
oil-sheen sensor on the underside, solar panels, mooring eye, sealed electronics bay. Explain each part in `cad/buoy/README.md`.

Files (all inside `cad/`):
- `buoy/build_buoy.py` — FreeCAD Python script that builds the model parametrically and exports files
- `buoy/buoy.FCStd`, `buoy/buoy.step`, `buoy/buoy.stl` — the CAD file to submit (STEP is the main one)
- `render_buoy.py` — Blender script: imports the STL, adds water, sky, lighting, renders PNGs
- `renders/` — output images (and optionally a short turntable)
Run FreeCAD headless: `FreeCADCmd cad/buoy/build_buoy.py`. Render: `blender -b -P cad/render_buoy.py`.
Do not touch `ml/` or `contracts/`.
