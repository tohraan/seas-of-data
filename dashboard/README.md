# Seas of Data dashboard

A directory of real ship detections from Sentinel-1 radar over Jebel Ali, Khalifa Port and their approaches.

## Run
From the repo root. [uv](https://docs.astral.sh/uv/) installs Python 3.12 and the dependencies on first run.

```bash
uv run --project dashboard streamlit run dashboard/app.py
```

Then open http://localhost:8501. The base maps, Ship movement and Radar playback need internet access.

To deploy on Streamlit Community Cloud, set the main file to `dashboard/app.py` and Python to 3.12. Dependencies are in `dashboard/requirements.txt`.

## Views
| Tab | For | What it does |
|---|---|---|
| Explorer | Analysts, journalists | Map on the real radar image, a table with a radar picture and AIS check per detection, filters, one detection's evidence, a link per detection, and CSV and GeoJSON downloads |
| Ship movement | Anyone | Replays real hourly AIS positions, about 3-4 days behind. Pick a ship that went quiet to see its reach ring. Below it, whatever the live feed is hearing now |
| Ship history | Analysts, port security | Every ship near the ports, ranked by checkable reasons to look closer, with its port calls, route and past identities |
| Radar playback | Anyone | Plays the real radar passes in order. Click a ship for a ring showing how far it could have gone at a speed you set |
| Port watch | Port operations | Ship-class counts by size at each pass, the last pass and the next expected pass |
| Review queue | Reviewers | Which detections to check next, and the verdicts so far. Read-only |
| Buoy siting | Planners | Where one to three buoys would cover the most detections |
| Methods and data | Judges, researchers | Data sources, processing steps, measured quality, limits, the YOLO and VH second opinion, and how to rebuild it |

A link such as `?id=s1d-20261102-a6757c` opens that detection directly.

## Data
| Source | Used for |
|---|---|
| `contracts/` | Detections, radar pictures, port counts, data sources and review results. Owned by the ML side |
| `derived/` | Radar map images, the second opinion, AIS checks, ship movement, ship history and the map of navigable water, all built by `pipeline/`. Evidence and AIS checks are used only if built from the current `contracts/detections.geojson` |
| `../cad/buoy/specs.json` | Buoy antenna height and camera range, for Buoy siting |
| `../ml/data/ais/` | AIS reports collected by `ml/ais/capture.py`, for Live ships. Local only, and never committed |

- Files are read fresh on every page load. If `detections.geojson` is missing, sample data is shown with a warning. If a real file is invalid, the page shows the error and doesn't fall back to samples, so fake numbers can't pass as real ones.
- To try other files without touching `contracts/`, set `SEAS_CONTRACTS_DIR` to another folder.

## Ship movement and live AIS
The replay uses Global Fishing Watch's hourly AIS, so it's real but about 3-4 days behind. Rebuild it with `pipeline/build_gfw.py`; the dashboard itself never needs the token.

The live section needs a free key from [aisstream.io](https://aisstream.io), saved in `ml/.env` as `AISSTREAM_KEY=...`, and a collector left running on a computer that stays awake. That free feed has very few receivers on this coast: in testing it heard a handful of ships here, against thousands in Northern Europe.

```bash
cd ml
uv run --no-project --python 3.12 --with websockets --with python-dotenv python -m ais.capture --hours 48
```

A hosted copy of the dashboard shows no live ships unless a collector runs alongside it. Set `SEAS_AIS_DIR` to read reports from another folder.

## Reading the numbers
- **Nothing is called dark without a real AIS check.** A detection counts as possibly dark only if it's in the ship class and Global Fishing Watch's radar and AIS matching found no match, or if the contract says `no_ais_match` from a real source. Simulated flags are ignored, and a likely fixed structure is never called dark.
- **The AIS check runs about 5 days behind**, so the newest pass may show "Not published yet". Positions are paired within 1 km, because Fishing Watch rounds them to about 1 km.
- **Ship history gives reasons to look closer, not accusations.** Each reason is a checkable fact with its source. A blank record doesn't clear a ship, and only ships broadcasting AIS can appear.
- **Fishing Watch's AIS-off events returned nothing for this region**, so quiet spells are worked out from the hourly positions: at least 12 hours unheard, inside the area, and reappearing at least 5 km away. Those thresholds, and which ships get flagged for what, are our own starting rules.
- **Boats shown inside Dubai really are there**, on the Dubai Canal and Creek. Fishing Watch rounds positions to 0.01 degrees, so a boat in a canal or at a quay can appear up to about 750 m away, on land. The replay moves those to the nearest navigable water from OpenStreetMap. In the replay's 26,906 positions, all but 5 were within that rounding of water, and those 5 are left out. Where a straight line between two hours would cross land, the ship follows the shortest way over water instead. Neither line is its exact path.
- **The default view is the latest pass.** Across all passes, one ship can be counted several times.
- **Radar class comes from the ML side.** On a review of 120 chips, not ground truth, the ship class was about 94% ship-like.
- **Radar dots don't move between passes**, because radar has no speed or heading. Playback's rings are estimates at a speed you set.
- **Reach rings only appear for ships you choose**, because a few hours at speed makes a ring wider than the map, and many together hide everything else.
- **Live positions are real AIS reports.** Between reports, a moving ship is projected from its last speed and course for up to 10 minutes, and that's marked as an estimate. A quiet ship may just be out of receiver range.
- **The next pass is projected** from the 12-day repeat of the passes so far, not from a published schedule.
- **Buoy sites are a starting point.** Water depth, shipping lanes and permits aren't checked.

## Licences
- Global Fishing Watch data is for non-commercial use only, under CC BY-NC 4.0, and pages using it must credit them. A commercial product would need a separate licence.
- The sanctions list comes from the US Treasury's OFAC.
- Radar images contain modified Copernicus Sentinel data.
- The map of navigable water is built from OpenStreetMap data, © OpenStreetMap contributors, under the Open Database License.
- Base maps are © OpenStreetMap contributors, © CARTO. CARTO now asks for a free API key: its raster tiles already show an "API key required" watermark without one. The vector tiles used here still work without a key as of 3 Nov 2026, but [its key page](https://carto.com/basemaps/apikey) says the key covers them too.

## Test
```bash
cd dashboard && uv run pytest
```
