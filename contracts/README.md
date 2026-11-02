# Contracts (owner: Tohraan / ML agent)

The ONLY interface between `ml/` and `dashboard/`.

- `detections.geojson` — FeatureCollection of ship detections, validated by `detections.schema.json`. Coordinates are [lon, lat].
- `port_activity.json` — list of {port, date, vessel_count, berth_occupancy_pct, activity_index}.

`sample_*` files are fake data so the dashboard can be built before the model exists. The ML agent will publish real files as
`contracts/detections.geojson` and `contracts/port_activity.json`. The dashboard should load the real file if present, else the sample.

Need a field changed or added? Open a GitHub issue labelled `contract-change`; do not edit these files if you are not the owner.
