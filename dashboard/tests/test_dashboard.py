import json
import math
import shutil
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from analysis import (
    PORT_POSITIONS,
    enrich,
    health_checks,
    port_etas,
    reach_km,
    repeat_locations,
)
from data import (
    CONTRACTS_DIR,
    ContractError,
    load_detections,
    load_port_activity,
    summarise,
)

APP = Path(__file__).resolve().parent.parent / "app.py"


@pytest.fixture(autouse=True)
def contracts(tmp_path, monkeypatch):
    # Every test starts from the sample files, whatever real files are published in contracts/.
    for name in ("detections.schema.json", "sample_detections.geojson", "sample_port_activity.json"):
        shutil.copy(CONTRACTS_DIR / name, tmp_path)
    monkeypatch.setenv("SEAS_CONTRACTS_DIR", str(tmp_path))
    return tmp_path


def sample_document(contracts):
    return json.loads((contracts / "sample_detections.geojson").read_text())


def test_published_contract_files_are_valid():
    if (CONTRACTS_DIR / "detections.geojson").exists():
        assert not load_detections(CONTRACTS_DIR).is_sample
    if (CONTRACTS_DIR / "port_activity.json").exists():
        assert not load_port_activity(CONTRACTS_DIR).is_sample


def test_falls_back_to_sample_when_real_file_missing(contracts):
    loaded = load_detections(contracts)
    assert loaded.is_sample
    assert loaded.frame["id"].tolist() == ["d001", "d002", "d003", "d004", "d005"]
    assert load_port_activity(contracts).is_sample


def test_real_file_wins_over_sample(contracts):
    document = sample_document(contracts)
    document["features"] = document["features"][:1]
    (contracts / "detections.geojson").write_text(json.dumps(document))
    loaded = load_detections(contracts)
    assert not loaded.is_sample
    assert len(loaded.frame) == 1


def test_stats_on_sample(contracts):
    assert summarise(load_detections(contracts).frame) == {"total": 5, "dark": 2, "pct_dark": 40.0}


def test_empty_detections_do_not_divide_by_zero(contracts):
    (contracts / "detections.geojson").write_text('{"type":"FeatureCollection","features":[]}')
    assert summarise(load_detections(contracts).frame) == {"total": 0, "dark": 0, "pct_dark": 0.0}


@pytest.mark.parametrize(
    "mutate",
    [
        lambda f: f["properties"].pop("dark"),
        lambda f: f["properties"].update(confidence=1.5),
        lambda f: f["properties"].update(timestamp="yesterday"),
        lambda f: f["geometry"].update(coordinates=[25.0, 120.0]),
    ],
    ids=["missing-field", "bad-confidence", "bad-timestamp", "swapped-coordinates"],
)
def test_invalid_real_detections_are_rejected(contracts, mutate):
    document = sample_document(contracts)
    mutate(document["features"][0])
    (contracts / "detections.geojson").write_text(json.dumps(document))
    with pytest.raises(ContractError):
        load_detections(contracts)


def test_malformed_port_activity_is_rejected(contracts):
    (contracts / "port_activity.json").write_text('[{"port": "Jebel Ali"}]')
    with pytest.raises(ContractError):
        load_port_activity(contracts)


def run_app():
    return AppTest.from_file(str(APP), default_timeout=30).run()


def run_all_passes():
    app = run_app()
    choice = next(option for option in app.selectbox(key="pass_choice").options if option.startswith("All passes"))
    app.selectbox(key="pass_choice").select(choice).run()
    assert not app.exception
    return app


def detections_table(app):
    # The watchlist table comes first and holds the same columns, so the full table is the last match.
    return [df.value for df in app.dataframe if "priority_label" in df.value.columns][-1]


def test_map_payload_uses_literal_pixel_units_and_valid_json():
    app = run_all_passes()
    payload = app.get("deck_gl_json_chart")[0].proto.json
    layers = json.loads(payload, parse_constant=pytest.fail)["layers"]
    assert [len(layer["data"]) for layer in layers] == [3, 2]
    for layer in layers:
        assert layer["radiusUnits"] == "pixels"
        assert layer["lineWidthUnits"] == "pixels"


def test_map_view_frames_every_detection():
    app = run_all_passes()
    deck = json.loads(app.get("deck_gl_json_chart")[0].proto.json)
    view = deck["initialViewState"]
    scale = 512 * 2 ** view["zoom"] / 360

    def mercator_y(lat):
        return math.degrees(math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)))

    for layer in deck["layers"]:
        for point in layer["data"]:
            assert abs(point["lon"] - view["longitude"]) * scale < 230
            assert abs(mercator_y(point["lat"]) - mercator_y(view["latitude"])) * scale < 230


def test_default_view_is_the_latest_pass_not_a_multi_pass_total():
    app = run_app()
    assert not app.exception
    assert [m.label for m in app.metric][:4] == ["Detections", "Dark", "Dark share", "High priority"]
    assert app.metric[0].value == "1"
    assert run_all_passes().metric[0].value == "5"


def test_dark_only_toggle_keeps_stats():
    app = run_all_passes()
    app.toggle(key="dark_only").set_value(True).run()
    assert not app.exception
    assert [m.value for m in app.metric][:3] == ["5", "2", "40.0%"]
    layers = json.loads(app.get("deck_gl_json_chart")[0].proto.json)["layers"]
    assert [len(layer["data"]) for layer in layers] == [0, 2]


def test_density_layer_can_be_turned_on():
    app = run_all_passes()
    app.toggle(key="density").set_value(True).run()
    assert not app.exception
    layers = json.loads(app.get("deck_gl_json_chart")[0].proto.json)["layers"]
    assert layers[0]["@@type"] == "HeatmapLayer"


def test_table_filters_and_search():
    app = run_all_passes()
    app.selectbox(key="table_show").select("Dark only").run()
    assert not app.exception
    assert set(detections_table(app)["id"]) == {"d002", "d004"}
    app.selectbox(key="table_show").select("All").run()
    app.text_input(key="table_search").set_value("636000002").run()
    assert set(detections_table(app)["id"]) == {"d003"}


def test_table_has_no_blank_mmsi_or_port_labels():
    table = detections_table(run_all_passes())
    assert table["ais_label"].notna().all()
    assert table["location"].notna().all()
    assert set(table.loc[table["dark"], "ais_label"]) == {"No AIS"}


def test_simulated_ais_is_labelled(contracts, monkeypatch):
    document = sample_document(contracts)
    for feature in document["features"]:
        feature["properties"]["ais_source"] = "simulated"
    (contracts / "detections.geojson").write_text(json.dumps(document))
    monkeypatch.setenv("SEAS_CONTRACTS_DIR", str(contracts))
    app = run_all_passes()
    assert [m.label for m in app.metric][:3] == ["Detections", "Dark (AIS simulated)", "Dark share (AIS simulated)"]
    assert any("AIS is simulated" in info.value for info in app.info)
    table = detections_table(app)
    assert set(table["status"]) == {"🔴 Dark", "🔵 Matched"}
    assert any("(simulated)" in label for label in table["ais_label"])


def test_real_ais_has_no_simulation_label():
    app = run_all_passes()
    assert [m.label for m in app.metric][:3] == ["Detections", "Dark", "Dark share"]
    assert not any("AIS is simulated" in info.value for info in app.info)


def test_port_section_shows_counts_beside_index_without_a_trend_line():
    app = run_app()
    port_chart_spec = next(
        spec for spec in (json.loads(c.proto.spec) for c in app.get("plotly_chart"))
        if spec["layout"]["barmode"] == "group"
    )
    assert {trace["type"] for trace in port_chart_spec["data"]} == {"bar"}
    port_table = next(df.value for df in app.dataframe if "activity_index" in df.value.columns)
    assert len(port_table) == 3


def test_reach_tab_scales_with_speed_and_time():
    app = run_all_passes()
    app.slider(key="reach_speed").set_value(10).run()
    app.slider(key="reach_hours").set_value(2).run()
    assert not app.exception
    assert any(m.value == "37 km away" for m in app.metric)
    circle = json.loads(app.get("deck_gl_json_chart")[1].proto.json)["layers"][0]
    assert circle["getRadius"] == pytest.approx(37040)


def test_invalid_real_file_shows_error_not_samples(contracts, monkeypatch):
    (contracts / "detections.geojson").write_text('{"type":"FeatureCollection","features":[{"type":"Feature"}]}')
    monkeypatch.setenv("SEAS_CONTRACTS_DIR", str(contracts))
    app = run_app()
    assert not app.exception
    assert "rejected" in app.error[0].value
    assert not app.metric


def test_empty_detections_file_renders(contracts, monkeypatch):
    (contracts / "detections.geojson").write_text('{"type":"FeatureCollection","features":[]}')
    monkeypatch.setenv("SEAS_CONTRACTS_DIR", str(contracts))
    app = run_app()
    assert not app.exception
    assert "no detections" in app.info[0].value


def make_frame(rows):
    base = {"scene_id": "A", "timestamp": pd.Timestamp("2026-11-02", tz="UTC"), "confidence": 0.8, "length_m": 100.0,
            "ais_matched": False, "dark": True, "mmsi": None, "port": None, "ais_source": None, "lat": 25.0, "lon": 54.7}
    return pd.DataFrame([{**base, "id": f"x{i}", **row} for i, row in enumerate(rows)])


def test_priority_rules():
    frame = enrich(make_frame([
        {},
        {"lat": 25.2, "confidence": 0.8, "length_m": 20.0},
        {"lat": 25.4, "confidence": 0.4, "length_m": 20.0},
        {"lat": 25.6, "confidence": 0.4, "length_m": 20.0, "port": "Jebel Ali"},
        {"lat": 25.8, "dark": False, "mmsi": "1"},
        {"lat": 26.0, "length_m": None},
    ]))
    assert frame["priority"].tolist() == ["High", "Medium", "Low", "Medium", "Not flagged", "Medium"]
    assert frame["size_class"].tolist() == ["Medium", "Small", "Small", "Small", "Medium", "Unknown"]


def test_same_spot_across_three_passes_is_marked_and_demoted():
    frame = enrich(make_frame([
        {"scene_id": "A"},
        {"scene_id": "B", "lon": 54.701},
        {"scene_id": "C", "lon": 54.702},
        {"scene_id": "A", "lat": 26.0},
    ]))
    assert frame["passes_seen"].tolist() == [3, 3, 3, 1]
    assert frame["priority"].tolist() == ["Medium", "Medium", "Medium", "High"]
    repeats = repeat_locations(frame)
    assert repeats[["passes", "detections", "times_dark"]].values.tolist() == [[3, 3, 3]]


def test_location_label_explains_missing_port():
    frame = enrich(make_frame([{"lat": 24.81, "lon": 54.75}, {"port": "Khalifa Port", "lat": 24.81, "lon": 54.65}]))
    assert frame["location"].iloc[0].startswith("Open water, 10 km from Khalifa Port")
    assert frame["location"].iloc[1] == "Khalifa Port area"


def test_reach_and_port_eta_arithmetic():
    assert reach_km(10, 2) == pytest.approx(37.04)
    etas = port_etas(*PORT_POSITIONS["Jebel Ali"], speed_knots=10)
    assert etas.iloc[0]["port"] == "Jebel Ali"
    assert etas.iloc[0]["hours"] == 0


def test_health_checks_count_weak_and_small_targets():
    frame = enrich(make_frame([{"confidence": 0.4, "length_m": 20.0}, {"lat": 26.0, "scene_id": "B", "timestamp": pd.Timestamp("2026-11-04", tz="UTC")}]))
    checks = health_checks(frame, pd.Timestamp("2026-11-04 10:00", tz="UTC")).set_index("Check")["Result"]
    assert checks["Latest data"] == "10 hours old"
    assert checks["Satellite passes"] == "2 passes, 48-48 hours apart"
    assert checks["Weak detections"] == "1 of 2 under 0.50 confidence"
    assert checks["Very small targets"] == "1 of 2 at 30 m or less"
