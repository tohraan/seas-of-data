# Seas of Data dashboard

Map of ship detections with dark vessels highlighted, a detections table, a port activity chart and summary stats.

## Run
Needs [uv](https://docs.astral.sh/uv/), which installs Python 3.12 and the dependencies on first run.

```bash
cd dashboard && uv run streamlit run app.py
```

Then open http://localhost:8501. The base map tiles come from CARTO, so the map background needs internet access.

## Data
Read fresh from `contracts/` on every page load:

| Shows | Real file | Used if the real file is missing |
|---|---|---|
| Map, table, stats | `detections.geojson` | `sample_detections.geojson` |
| Port chart | `port_activity.json` | `sample_port_activity.json` |

- A yellow banner appears whenever sample data is on screen.
- Detections are validated against `contracts/detections.schema.json`. Port activity is validated against the fields listed in `contracts/README.md`, because it has no schema file.
- If a real file exists but is invalid, the dashboard shows the error for that section. It does not fall back to sample data, so fake numbers can't pass as real ones.

To try the dashboard with files from another folder, without touching `contracts/`, set `SEAS_CONTRACTS_DIR`:
```bash
cd dashboard && SEAS_CONTRACTS_DIR=/path/to/contracts uv run streamlit run app.py
```

## Reading the numbers
- If detections have `ais_source: "simulated"`, the dark ship labels say so, and a banner explains that the dark share is a simulation parameter, not a finding.
- Port counts per pass are small, so the chart shows raw counts as bars, with the activity index beside them in the table. The index is not drawn as a trend.

## Test
```bash
cd dashboard && uv run pytest
```
