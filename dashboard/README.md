# Seas of Data dashboard

A directory of real ship detections from Sentinel-1 radar over Jebel Ali, Khalifa Port and their approaches.

## Run
From the repo root. [uv](https://docs.astral.sh/uv/) installs Python 3.12 and the dependencies on first run.

```bash
uv run --project dashboard streamlit run dashboard/app.py
```

Then open http://localhost:8501. The map backgrounds and Playback need internet access.

To deploy on Streamlit Community Cloud, set the main file to `dashboard/app.py` and Python to 3.12. Dependencies are in `dashboard/requirements.txt`.

## Views
| Tab | For | What it does |
|---|---|---|
| Explorer | Analysts, journalists | Map on the real radar image, a table with a radar picture per detection, filters, one detection's evidence, a link per detection, and CSV and GeoJSON downloads |
| Playback | Anyone | Plays the real passes in order, with a ring for how far a ship could have gone at a speed you set |
| Port watch | Port operations | Ship-class counts by size at each pass, the last pass and the next expected pass |
| Review queue | Reviewers | Which detections to check next, and the verdicts so far. Read-only |
| Buoy siting | Planners | Where one to three buoys would cover the most detections |
| Methods and data | Judges, researchers | Data sources, processing steps, measured quality, limits, the YOLO and VH second opinion, and how to rebuild it |

A link such as `?id=s1d-20261102-a6757c` opens that detection directly.

## Data
| Source | Used for |
|---|---|
| `contracts/` | Detections, radar pictures, port counts, data sources and review results. Owned by the ML side |
| `derived/` | The radar map images and second opinion, built by `pipeline/`. Used only if built from the current `contracts/detections.geojson` |
| `../cad/buoy/specs.json` | Buoy antenna height and camera range, for Buoy siting |

- Files are read fresh on every page load. If `detections.geojson` is missing, sample data is shown with a warning. If a real file is invalid, the page shows the error and doesn't fall back to samples, so fake numbers can't pass as real ones.
- To try other files without touching `contracts/`, set `SEAS_CONTRACTS_DIR` to another folder.

## Reading the numbers
- **Nothing is called dark without a real AIS check.** A detection counts as possibly dark only if `status` is `no_ais_match` from a real source. Simulated flags are ignored.
- **The default view is the latest pass.** Across all passes, one ship can be counted several times.
- **Radar class comes from the ML side.** On a review of 120 chips, not ground truth, the ship class was about 94% ship-like.
- **Dots don't move between passes**, because radar has no speed or heading. Playback's rings are estimates at a speed you set.
- **The next pass is projected** from the 12-day repeat of the passes so far, not from a published schedule.
- **Buoy sites are a starting point.** Water depth, shipping lanes and permits aren't checked.

## Test
```bash
cd dashboard && uv run pytest
```
