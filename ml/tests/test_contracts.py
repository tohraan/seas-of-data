import csv, json
from pathlib import Path
import jsonschema

C = Path(__file__).resolve().parents[2] / "contracts"
fc = json.loads((C / "detections.geojson").read_text())
props = [f["properties"] for f in fc["features"]]


def test_schema_valid():
    jsonschema.validate(fc, json.loads((C / "detections.schema.json").read_text()))


def test_nothing_simulated_in_headline():
    assert all(p["ais_source"] != "simulated" for p in props)


def test_not_checked_means_no_dark_claim():
    for p in props:
        if p["status"] == "not_checked":
            assert p["dark"] is None and p["mmsi"] is None and p["ais_matched"] is False


def test_ids_unique_and_chips_exist():
    assert len({p["id"] for p in props}) == len(props)
    for p in props:
        assert (C / p["chip"]).exists() and (C / p["chip_context"]).exists()


def test_manifest_matches_features():
    m = json.loads((C / "manifest.json").read_text())
    assert m["totals"]["detections"] == len(props)
    assert sum(s["detections"]["n"] for s in m["scenes"]) == len(props)
    for s in m["scenes"]:
        assert len(s["sha256"]) == 64 and s["cfar"]["stages"]["after_merge"] == s["detections"]["n"]


def test_labels_agree_with_review_field():
    by = {p["id"]: p["review"] for p in props}
    for row in csv.DictReader(open(C / "labels.csv")):
        assert by[row["id"]] == row["verdict"]


def test_port_rows_have_no_assumed_capacity():
    rows = json.loads((C / "port_activity.json").read_text())
    assert all("berth_occupancy_pct" not in r for r in rows)


def test_metrics_present():
    m = json.loads((C / "metrics_gulf.json").read_text())
    assert m["sample"]["n"] >= 100 and 0 < m["by_radar_class"]["ship"]["precision_strict"]["estimate"] <= 1
