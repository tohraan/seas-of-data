import base64
import hashlib
import io
import json
import math
import re
import shutil
from pathlib import Path

import pandas as pd
import pytest
from PIL import Image
from streamlit.testing.v1 import AppTest

from analysis import (
    PORT_POSITIONS,
    enrich,
    expected_next_passes,
    possible_dark,
    radio_horizon_km,
    rank_sites,
    reach_km,
    review_queue,
    same_spot,
    to_csv,
    to_geojson,
    unique_spots,
)
from data import (
    CONTRACTS_DIR,
    ContractError,
    attach_evidence,
    load_detections,
    load_evidence,
    load_port_activity,
    resolve_chip,
    size_class,
    summarise,
    thumbnail_uri,
)
from views.playback import build_page

APP = Path(__file__).resolve().parent.parent / "app.py"
HAS_REAL_CONTRACT = (CONTRACTS_DIR / "manifest.json").exists()
needs_real_contract = pytest.mark.skipif(not HAS_REAL_CONTRACT, reason="contract v2 isn't on this branch")


@pytest.fixture(autouse=True)
def contracts(tmp_path, monkeypatch):
    # Every test starts from the sample files and no evidence, whatever is published in contracts/ and derived/.
    folder = tmp_path / "contracts"
    folder.mkdir()
    for name in ("detections.schema.json", "sample_detections.geojson", "sample_port_activity.json"):
        shutil.copy(CONTRACTS_DIR / name, folder)
    monkeypatch.setenv("SEAS_CONTRACTS_DIR", str(folder))
    monkeypatch.setenv("SEAS_DERIVED_DIR", str(tmp_path / "derived"))
    return folder


@pytest.fixture
def real_contract(monkeypatch):
    if not HAS_REAL_CONTRACT:
        pytest.skip("contract v2 isn't on this branch")
    monkeypatch.setenv("SEAS_CONTRACTS_DIR", str(CONTRACTS_DIR))
    return CONTRACTS_DIR


def sample_document(contracts):
    return json.loads((contracts / "sample_detections.geojson").read_text())


def write_v2(contracts, status="not_checked", source="none", dark=None):
    document = sample_document(contracts)
    for feature in document["features"]:
        feature["properties"].update(status=status, ais_source=source, dark=dark, mmsi=None, ais_matched=False, radar_class="ship")
    (contracts / "detections.geojson").write_text(json.dumps(document))


def run_app():
    return AppTest.from_file(str(APP), default_timeout=60).run()


def choose_all_passes(app):
    choice = next(option for option in app.selectbox(key="pass_choice").options if option.startswith("All passes"))
    app.selectbox(key="pass_choice").select(choice).run()
    assert not app.exception
    return app


def run_all_passes():
    return choose_all_passes(run_app())


def explorer_table(app):
    return next(df.value for df in app.dataframe if "class_label" in df.value.columns and "seen" in df.value.columns)


def decks(app):
    return [json.loads(chart.proto.json) for chart in app.get("deck_gl_json_chart")]


# Loading


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


def test_published_contract_files_are_valid():
    if (CONTRACTS_DIR / "detections.geojson").exists():
        assert not load_detections(CONTRACTS_DIR).is_sample
    if (CONTRACTS_DIR / "port_activity.json").exists():
        assert not load_port_activity(CONTRACTS_DIR).is_sample


@pytest.mark.parametrize(
    "mutate",
    [
        lambda f: f["properties"].pop("id"),
        lambda f: f["properties"].update(confidence=1.5),
        lambda f: f["properties"].update(timestamp="yesterday"),
        lambda f: f["geometry"].update(coordinates=[25.0, 120.0]),
        lambda f: f["properties"].update(radar_class="submarine"),
    ],
    ids=["missing-field", "bad-confidence", "bad-timestamp", "swapped-coordinates", "unknown-class"],
)
def test_invalid_real_detections_are_rejected(contracts, mutate):
    document = sample_document(contracts)
    mutate(document["features"][0])
    (contracts / "detections.geojson").write_text(json.dumps(document))
    with pytest.raises(ContractError):
        load_detections(contracts)


def test_port_activity_no_longer_needs_berth_occupancy(contracts):
    (contracts / "port_activity.json").write_text(json.dumps([{"port": "Jebel Ali", "date": "2026-10-24", "vessel_count": 3, "activity_index": 150.0}]))
    assert not load_port_activity(contracts).is_sample


def test_malformed_port_activity_is_rejected(contracts):
    (contracts / "port_activity.json").write_text('[{"port": "Jebel Ali"}]')
    with pytest.raises(ContractError):
        load_port_activity(contracts)


def test_summary_counts_radar_classes():
    frame = pd.DataFrame({"radar_class": ["ship", "ship", "uncertain", "likely_fixed"]})
    assert summarise(frame) == {"total": 4, "ship": 2, "uncertain": 1, "likely_fixed": 1}


def test_size_bands_match_the_contract():
    assert [size_class(v) for v in (29.9, 30, 59, 60, 119, 120, 199, 200, 300)] == [
        "tiny", "small", "small", "medium", "medium", "large", "large", "very_large", "very_large",
    ]
    assert size_class(None) is None


# Honest AIS labels


def test_null_dark_stays_not_checked_and_never_becomes_false(contracts):
    write_v2(contracts)
    frame = enrich(attach_evidence(load_detections(contracts).frame, None))
    assert frame["dark"].isna().all()
    assert set(frame["ais_label"]) == {"Not checked"}
    assert not possible_dark(frame).any()


def test_simulated_flags_are_never_called_dark(contracts):
    write_v2(contracts, status="no_ais_match", source="simulated", dark=True)
    frame = enrich(attach_evidence(load_detections(contracts).frame, None))
    assert not possible_dark(frame).any()
    assert set(frame["ais_label"]) == {"Not checked"}


def test_real_ais_check_can_call_a_ship_possibly_dark(contracts):
    write_v2(contracts, status="no_ais_match", source="gfw", dark=True)
    frame = enrich(attach_evidence(load_detections(contracts).frame, None))
    assert possible_dark(frame).all()
    assert set(frame["ais_label"]) == {"No AIS match"}


@needs_real_contract
def test_published_contract_says_nothing_is_dark(real_contract):
    frame = enrich(attach_evidence(load_detections(real_contract).frame, None))
    assert len(frame) == 250
    assert not possible_dark(frame).any()
    assert frame["dark"].isna().all()


# Radar images


def test_chip_paths_cannot_leave_the_contracts_folder(contracts, tmp_path):
    (tmp_path / "secret.png").write_bytes(b"x")
    chips = contracts / "chips"
    chips.mkdir()
    Image.new("L", (128, 128), 90).save(chips / "a.png")
    assert resolve_chip("chips/a.png", contracts) == (chips / "a.png").resolve()
    assert resolve_chip("../secret.png", contracts) is None
    assert resolve_chip("chips/missing.png", contracts) is None
    assert resolve_chip(None, contracts) is None
    assert resolve_chip(float("nan"), contracts) is None


def test_thumbnail_is_small_and_valid(contracts):
    chips = contracts / "chips"
    chips.mkdir()
    Image.new("L", (128, 128), 90).save(chips / "a.png")
    uri = thumbnail_uri("chips/a.png", size=72, directory=contracts)
    assert uri.startswith("data:image/jpeg;base64,")
    assert Image.open(io.BytesIO(base64.b64decode(uri.split(",", 1)[1]))).size == (72, 72)
    assert thumbnail_uri("chips/missing.png", directory=contracts) is None


# Evidence


def write_evidence(tmp_path, contract_path, targets=None):
    derived = tmp_path / "derived"
    derived.mkdir(exist_ok=True)
    targets = targets if targets is not None else [
        {"id": "d002", "scene_id": "x", "detector": "both", "yolo_only": False, "yolo_confidence": 0.8, "vh_confirmed": True, "axis_deg": 40.0, "chip_vh": None},
        {"id": "y0001", "scene_id": "x", "detector": "yolo", "yolo_only": True, "yolo_confidence": 0.5, "vh_confirmed": False, "axis_deg": None, "chip_vh": None},
    ]
    (derived / "evidence.json").write_text(json.dumps({
        "contract_sha256": hashlib.sha256(contract_path.read_bytes()).hexdigest(),
        "passes": [], "targets": targets, "model": {}, "settings": {}, "source": "test", "built_at": "2026-11-03T00:00:00Z",
    }))
    return derived


def test_evidence_is_missing_then_used_then_stale_when_the_contract_changes(contracts, tmp_path):
    path = contracts / "sample_detections.geojson"
    assert load_evidence(path) == (None, "missing")
    write_evidence(tmp_path, path)
    evidence, state = load_evidence(path)
    assert state == "ok"
    path.write_text(path.read_text() + " ")
    assert load_evidence(path) == (None, "stale")
    assert evidence is not None


def test_evidence_that_is_not_a_valid_file_is_ignored(contracts, tmp_path):
    derived = tmp_path / "derived"
    derived.mkdir()
    (derived / "evidence.json").write_text('{"targets": []}')
    assert load_evidence(contracts / "sample_detections.geojson") == (None, "invalid")


def test_attach_evidence_joins_by_id_and_leaves_yolo_only_rows_out(contracts, tmp_path):
    loaded = load_detections(contracts)
    write_evidence(tmp_path, loaded.path)
    evidence, _ = load_evidence(loaded.path)
    frame = enrich(attach_evidence(loaded.frame, evidence))
    assert len(frame) == 5
    row = frame[frame["id"] == "d002"].iloc[0]
    assert row["check_label"] == "Both"
    assert row["vh_label"] == "Yes"
    other = frame[frame["id"] == "d001"].iloc[0]
    assert other["check_label"] == "Not run"
    assert other["vh_label"] == "Not measured"


# Analysis


def make_frame(rows):
    base = {
        "id": "x", "scene_id": "A", "timestamp": pd.Timestamp("2026-11-02", tz="UTC"), "product": None, "confidence": 0.8,
        "snr_z": 12.0, "contrast_db": 30.0, "land_distance_m": 5000.0, "length_m": 100.0, "size_class": "medium", "persistence": 1,
        "radar_class": "ship", "status": "not_checked", "review": "unreviewed", "detector": "cfar-v1", "ais_matched": False,
        "dark": None, "mmsi": None, "port": None, "ais_source": "none", "chip": None, "chip_context": None, "lat": 25.0, "lon": 54.7,
    }
    frame = pd.DataFrame([{**base, "id": f"x{i}", **row} for i, row in enumerate(rows)])
    return enrich(attach_evidence(frame, None))


def test_location_label_explains_a_missing_port():
    frame = make_frame([{"lat": 24.81, "lon": 54.75}, {"port": "Khalifa Port", "lat": 24.81, "lon": 54.65}])
    assert frame["location"].iloc[0].startswith("Open water, 10 km from Khalifa Port")
    assert frame["location"].iloc[1] == "Khalifa Port area"


def test_review_queue_ranks_more_signals_first_then_brightness():
    frame = make_frame([
        {"contrast_db": 40.0, "radar_class": "uncertain"},
        {"contrast_db": 20.0},
        {"contrast_db": 25.0},
        {"contrast_db": 50.0, "review": "confirmed"},
        {"contrast_db": 10.0},
    ])
    frame["detector_check"] = frame["detector_check"].astype(object)
    frame["vh_confirmed"] = frame["vh_confirmed"].astype(object)
    frame.loc[frame["id"] == "x4", "detector_check"] = "both"
    frame.loc[frame["id"] == "x4", "vh_confirmed"] = True
    queue = review_queue(frame)
    assert queue["id"].tolist() == ["x4", "x2", "x1", "x0"]
    assert queue["signals"].tolist() == [3, 1, 1, 0]
    assert "YOLO also found it" in queue.iloc[0]["why"]
    assert queue.iloc[-1]["why"] == "faint or near land"


def test_same_spot_finds_other_passes_only():
    frame = make_frame([
        {"scene_id": "A"},
        {"scene_id": "B", "lon": 54.7005},
        {"scene_id": "A", "lon": 54.7001},
        {"scene_id": "C", "lon": 54.71},
    ])
    assert same_spot(frame, frame.iloc[0])["id"].tolist() == ["x1"]


def test_next_passes_follow_the_twelve_day_repeat():
    times = pd.Series(pd.to_datetime(["2026-10-24T14:23:51Z", "2026-10-27T02:14:40Z"], utc=True))
    upcoming = expected_next_passes(times, pd.Timestamp("2026-11-03T12:00:00Z"))
    assert upcoming[:2] == [pd.Timestamp("2026-11-05T14:23:51Z"), pd.Timestamp("2026-11-08T02:14:40Z")]
    assert len(upcoming) == 3


def test_reach_and_radio_horizon_arithmetic():
    assert reach_km(12, 24) == pytest.approx(533.4, abs=0.1)
    assert radio_horizon_km(4, 16) == pytest.approx(24.72)


def test_unique_spots_counts_a_repeat_once():
    frame = make_frame([{"scene_id": "A"}, {"scene_id": "B", "lon": 54.7005}, {"scene_id": "C", "lon": 54.8}])
    assert unique_spots(frame)["id"].tolist() == ["x0", "x2"]


def test_buoy_site_covers_the_most_spots_and_avoids_the_shore():
    frame = make_frame([
        {"lat": 25.0, "lon": 54.700},
        {"lat": 25.0, "lon": 54.705},
        {"lat": 25.0, "lon": 54.710, "land_distance_m": 200.0},
        {"lat": 25.5, "lon": 55.100},
    ])
    site = rank_sites(frame, primary_km=3.0, secondary_km=1.0, count=1)[0]
    assert site["primary_total"] == 3
    assert site["lat"] == 25.0
    assert site["lon"] != 54.710


def test_balanced_site_gives_up_some_ais_range_for_camera_coverage():
    # Five spots tightly clustered, and a sixth site between them and a far group that reaches more of everything by AIS.
    frame = make_frame([
        {"lat": 25.0, "lon": 54.700 + i * 0.002} for i in range(5)
    ] + [
        {"lat": 25.0, "lon": 54.760},
        {"lat": 25.0, "lon": 54.800},
    ])
    most = rank_sites(frame, primary_km=7.0, secondary_km=1.0, count=1, primary_share=1.0)[0]
    balanced = rank_sites(frame, primary_km=7.0, secondary_km=1.0, count=1, primary_share=0.5)[0]
    assert most["primary_total"] >= balanced["primary_total"]
    assert balanced["secondary_total"] > most["secondary_total"]


def test_second_buoy_only_counts_new_spots():
    frame = make_frame([{"lat": 25.0, "lon": 54.700}, {"lat": 25.0, "lon": 54.705}, {"lat": 25.5, "lon": 55.100}])
    first, second = rank_sites(frame, primary_km=3.0, secondary_km=1.0, count=2)
    assert first["new_primary"] == 2
    assert second["new_primary"] == 1
    assert second["primary_total"] == 3


def test_downloads_are_valid_and_nulls_stay_null():
    frame = make_frame([{"length_m": None, "size_class": None}])
    document = json.loads(to_geojson(frame))
    feature = document["features"][0]
    assert feature["geometry"]["coordinates"] == [54.7, 25.0]
    assert feature["properties"]["length_m"] is None
    assert feature["properties"]["timestamp"] == "2026-11-02T00:00:00Z"
    assert to_csv(frame).splitlines()[0].startswith("id,radar_class")


def test_playback_page_cannot_be_broken_by_its_data():
    page = build_page(json.dumps([{"id": "</script><b>"}]), json.dumps([]))
    assert "</script><b>" not in page
    assert re.findall(r"__[A-Z_]+__", page) == []
    assert "esc(object.id)" in page
    # Without this the base map stays blank, because the page is embedded through srcdoc.
    assert page.index("Worker.prototype.postMessage") < page.index("new deck.DeckGL")


# The running app


def test_default_view_is_the_latest_pass_not_a_multi_pass_total():
    app = run_app()
    assert not app.exception
    assert [m.label for m in app.metric][:5] == ["Detections", "Ship class", "Uncertain", "Likely fixed", "Possibly dark"]
    assert app.metric[0].value == "1"
    assert run_all_passes().metric[0].value == "5"


def test_no_ais_means_no_dark_tile(contracts):
    write_v2(contracts)
    app = run_app()
    assert not app.exception
    labels = [m.label for m in app.metric][:5]
    assert labels[4] == "AIS check"
    assert app.metric[4].value == "Not yet"
    assert any("haven't been checked against AIS" in info.value for info in app.info)


def test_map_payload_uses_literal_pixel_units_and_valid_json(contracts):
    write_v2(contracts)
    layers = json.loads(run_all_passes().get("deck_gl_json_chart")[0].proto.json, parse_constant=pytest.fail)["layers"]
    assert sum(len(layer["data"]) for layer in layers) == 5
    for layer in layers:
        assert layer["radiusUnits"] == "pixels"
        assert layer["lineWidthUnits"] == "pixels"


def test_map_view_frames_every_detection(contracts):
    write_v2(contracts)
    deck = decks(run_all_passes())[0]
    view = deck["initialViewState"]
    scale = 512 * 2 ** view["zoom"] / 360

    def mercator_y(lat):
        return math.degrees(math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)))

    for layer in deck["layers"]:
        for point in layer["data"]:
            assert abs(point["lon"] - view["longitude"]) * scale < 250
            assert abs(mercator_y(point["lat"]) - mercator_y(view["latitude"])) * scale < 250


def test_explorer_filters_and_search(contracts):
    document = sample_document(contracts)
    document["features"][1]["properties"]["radar_class"] = "uncertain"
    (contracts / "detections.geojson").write_text(json.dumps(document))
    app = run_all_passes()
    assert "d002" not in set(explorer_table(app)["id"])
    app.multiselect(key="ex_class").select("Uncertain").run()
    assert not app.exception
    assert "d002" in set(explorer_table(app)["id"])
    app.text_input(key="ex_search").set_value("D003").run()
    assert not app.exception
    assert set(explorer_table(app)["id"]) == {"d003"}


def test_invalid_real_file_shows_error_not_samples(contracts):
    (contracts / "detections.geojson").write_text('{"type":"FeatureCollection","features":[{"type":"Feature"}]}')
    app = run_app()
    assert not app.exception
    assert "rejected" in app.error[0].value
    assert not app.metric


def test_empty_detections_file_renders(contracts):
    (contracts / "detections.geojson").write_text('{"type":"FeatureCollection","features":[]}')
    app = run_app()
    assert not app.exception
    assert "no detections" in app.info[0].value


def test_stale_evidence_warns_only_for_real_data(contracts, tmp_path):
    derived = tmp_path / "derived"
    derived.mkdir()
    (derived / "evidence.json").write_text(json.dumps({
        "contract_sha256": "old", "passes": [], "targets": [], "model": {}, "settings": {}, "source": "t", "built_at": "2026",
    }))
    assert not any("older data release" in w.value for w in run_app().warning)
    write_v2(contracts)
    assert any("older data release" in w.value for w in run_app().warning)


@needs_real_contract
def test_real_contract_renders_every_view(real_contract):
    app = run_app()
    assert not app.exception
    assert not app.error
    assert not any(m.label == "Possibly dark" for m in app.metric)
    choose_all_passes(app)
    assert app.metric[0].value == "250"
    assert app.metric[1].value == "120"
    table = explorer_table(app)
    assert set(table["class_label"]) == {"Ship"}
    assert table["thumb"].notna().all()
    assert table["thumb"].iloc[0].startswith("data:image/jpeg")
    app.multiselect(key="ex_class").set_value(["Ship", "Uncertain", "Likely fixed"]).run()
    assert not app.exception
    assert len(explorer_table(app)) == 250


@needs_real_contract
def test_permalink_opens_a_detection(real_contract):
    frame = load_detections(real_contract).frame
    target = frame["id"].iloc[3]
    app = AppTest.from_file(str(APP), default_timeout=60)
    app.query_params["id"] = target
    app.run()
    assert not app.exception
    assert any(target in header.value for header in app.subheader)


@needs_real_contract
def test_buoy_siting_counts_each_spot_once(real_contract):
    app = run_app()
    assert not app.exception
    tile = next(m for m in app.metric if m.label == "In AIS range")
    covered, total = tile.value.split(" of ")
    assert int(covered) <= int(total.split()[0]) < 120
    app.slider(key="site_buoys").set_value(2).run()
    assert not app.exception
    assert int(next(m for m in app.metric if m.label == "In AIS range").value.split(" of ")[0]) > int(covered)


def test_port_positions_are_inside_the_study_area():
    for lat, lon in PORT_POSITIONS.values():
        assert 24.55 <= lat <= 25.30
        assert 54.45 <= lon <= 55.30
