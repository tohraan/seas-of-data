# dashboard/ — owner: Aayush (dash-cad-agent)
Build a web dashboard: map of ship detections (dark vessels highlighted), port activity chart, summary stats.
Read data from `contracts/detections.geojson` and `contracts/port_activity.json` (fall back to `contracts/sample_*` until real
files exist). Copy or fetch them at build/run time; never edit `contracts/`. Suggested stack: Streamlit + pydeck/folium (fastest),
or a static Vite + Leaflet page. Keep it runnable with one command, and document that command in `dashboard/README.md`.
Do not touch `ml/` or `contracts/`.
