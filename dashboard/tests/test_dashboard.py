import json
import math
import shutil
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from data import CONTRACTS_DIR, ContractError, load_detections, load_port_activity, summarise

APP = Path(__file__).resolve().parent.parent / "app.py"


@pytest.fixture
def contracts(tmp_path):
    for name in ("detections.schema.json", "sample_detections.geojson", "sample_port_activity.json"):
        shutil.copy(CONTRACTS_DIR / name, tmp_path)
    return tmp_path


def sample_document(contracts):
    return json.loads((contracts / "sample_detections.geojson").read_text())


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


def test_map_payload_uses_literal_pixel_units_and_valid_json():
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    payload = app.get("deck_gl_json_chart")[0].proto.json
    layers = json.loads(payload, parse_constant=pytest.fail)["layers"]
    assert [len(layer["data"]) for layer in layers] == [3, 2]
    for layer in layers:
        assert layer["radiusUnits"] == "pixels"
        assert layer["lineWidthUnits"] == "pixels"


def test_map_view_frames_every_detection():
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    deck = json.loads(app.get("deck_gl_json_chart")[0].proto.json)
    view = deck["initialViewState"]
    scale = 512 * 2 ** view["zoom"] / 360

    def mercator_y(lat):
        return math.degrees(math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)))

    for layer in deck["layers"]:
        for point in layer["data"]:
            assert abs(point["lon"] - view["longitude"]) * scale < 230
            assert abs(mercator_y(point["lat"]) - mercator_y(view["latitude"])) * scale < 230


def test_app_renders_sample_data():
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    assert not app.exception
    assert [m.value for m in app.metric] == ["5", "2", "40.0%"]


def test_dark_only_toggle_keeps_stats_and_filters_table():
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    app.toggle[0].set_value(True).run()
    assert not app.exception
    assert [m.value for m in app.metric] == ["5", "2", "40.0%"]
    assert set(app.dataframe[0].value["status"]) == {"Dark vessel"}
