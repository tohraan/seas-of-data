"""The Ship tracker's data layer, tested on small made-up inputs, plus a smoke test of the tab."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

import tracker_data
from data import CONTRACTS_DIR
from tracker_data import bearing_deg, build_payload, downsample_water, last_known, load_tles, merge_live, tle_checksum_ok, trail_runs, water_grid

APP = Path(__file__).resolve().parent.parent / "app.py"
# Sentinel-1C-shaped lines; with_checksum gives them a valid last digit.
LINE1 = "1 62261U 24235A   26306.12345678  .00000000  00000-0  00000-0 0  9991"
LINE2 = "2 62261  98.1800 300.0000 0001000  90.0000 270.0000 14.59198000 10000"


def with_checksum(line: str) -> str:
    total = sum(int(c) if c.isdigit() else 1 if c == "-" else 0 for c in line[:68])
    return line[:68] + str(total % 10)


def movement(fixes, ships=None):
    return {
        "hours": [f"2026-10-30T{hour:02d}:00:00Z" for hour in range(24)],
        "ships": ships or [{"name": "ALPHA", "flag": "ARE", "type": "CARGO", "imo": "1", "mmsi": "470000001"}],
        "fixes": fixes,
        "max_line_hours": 3,
    }


def test_last_known_takes_the_newest_fix_and_its_heading():
    rows = last_known(movement([[0, 5, 25.00, 54.60, 10.0], [0, 2, 24.90, 54.50, 9.0], [0, 6, 25.05, 54.60, 11.0]]))
    assert len(rows) == 1
    ship = rows[0]
    assert (ship["lat"], ship["lon"], ship["kn"]) == (25.05, 54.60, 11.0)
    assert ship["t"] == int(pd.Timestamp("2026-10-30T06:00:00Z").timestamp() * 1000)
    assert ship["course"] == pytest.approx(0, abs=0.1)
    assert ship["source"] == "gfw"


def test_no_heading_from_fixes_too_close_far_apart_in_time_or_across_a_jump():
    near = last_known(movement([[0, 5, 25.000, 54.6, 0.0], [0, 6, 25.003, 54.6, 0.0]]))[0]
    late = last_known(movement([[0, 1, 24.9, 54.6, 9.0], [0, 6, 25.0, 54.6, 9.0]]))[0]
    jump = last_known(movement([[0, 5, 24.9, 54.6, 9.0, 1], [0, 6, 25.0, 54.6, 9.0]]))[0]
    assert near["course"] is None and late["course"] is None and jump["course"] is None


def test_bearing_on_known_pairs():
    assert bearing_deg(25, 55, 26, 55) == pytest.approx(0, abs=1e-6)
    assert bearing_deg(25, 55, 25, 56) == pytest.approx(89.79, abs=0.01)
    assert bearing_deg(25, 55, 24, 55) == pytest.approx(180, abs=1e-6)
    assert bearing_deg(25, 55, 25, 54) == pytest.approx(270.21, abs=0.01)


def test_trail_breaks_at_a_silence_and_drops_a_moored_ship():
    fixes = [[0, 0, 25.0, 54.0, 5], [0, 1, 25.1, 54.0, 5], [0, 9, 25.5, 54.0, 5], [0, 10, 25.6, 54.0, 5], [0, 11, 25.6, 54.0, 0]]
    assert trail_runs(fixes, 3) == [[[54.0, 25.0], [54.0, 25.1]], [[54.0, 25.5], [54.0, 25.6]]]
    assert trail_runs([[0, 0, 25.0, 54.0, 0], [0, 1, 25.0, 54.0, 0]], 3) == []


def test_downsampling_keeps_a_one_cell_channel_open():
    water = np.zeros((8, 8), dtype=bool)
    water[:, 5] = True  # a channel one fine cell wide
    coarse = downsample_water(water, 4)
    assert coarse.shape == (2, 2)
    assert coarse[:, 1].all() and not coarse[:, 0].any()


def test_water_grid_reports_cell_edges(tmp_path):
    water = np.ones((8, 8), dtype=bool)
    np.savez_compressed(tmp_path / "water.npz", bits=np.packbits(water), shape=water.shape, west=54.0, north=25.0, res=0.0005)
    grid = water_grid(tmp_path / "water.npz")
    assert (grid["rows"], grid["cols"]) == (2, 2)
    assert grid["west"] == pytest.approx(54.0 - 0.00025) and grid["north"] == pytest.approx(25.0 + 0.00025)
    assert grid["res"] == pytest.approx(0.002)
    assert water_grid(tmp_path / "missing.npz") is None


def test_tles_need_a_sentinel_name_and_good_checksums(tmp_path):
    line1, line2 = with_checksum(LINE1), with_checksum(LINE2)
    assert tle_checksum_ok(line1) and tle_checksum_ok(line2)
    broken = line1[:68] + str((int(line1[68]) + 1) % 10)
    path = tmp_path / "tle.json"
    path.write_text(json.dumps({"satellites": [
        {"id": "S1C", "name": "SENTINEL-1C", "line1": line1, "line2": line2},
        {"id": "X", "name": "ISS (ZARYA)", "line1": line1, "line2": line2},
        {"id": "S1D", "name": "SENTINEL-1D", "line1": broken, "line2": line2},
    ]}))
    satellites = load_tles(path)
    assert [s["id"] for s in satellites] == ["S1C"]
    # Day 306 of 2026 is 2 November.
    assert satellites[0]["epoch"] == pytest.approx((pd.Timestamp("2026-11-02", tz="UTC") + pd.Timedelta(days=0.12345678)).timestamp() * 1000, abs=1)
    assert load_tles(tmp_path / "missing.json") == []


def test_a_newer_live_report_replaces_the_fishing_watch_fix():
    ships = [{"name": "ALPHA", "flag": "ARE", "type": "CARGO", "imo": "1", "mmsi": "1", "lat": 25.0, "lon": 54.0, "kn": 5, "t": 1000, "course": None, "trail": None, "source": "gfw"}]
    live = [
        {"mmsi": "1", "name": None, "lat": 25.2, "lon": 54.2, "kn": 9, "course": 45.0, "t": 2000, "trail": None, "source": "live"},
        {"mmsi": "2", "name": "BRAVO", "lat": 25.3, "lon": 54.3, "kn": 3, "course": None, "t": 2000, "trail": None, "source": "live"},
    ]
    merged = merge_live(ships, live)
    assert len(merged) == 2
    assert (merged[0]["lat"], merged[0]["source"], merged[0]["name"], merged[0]["type"]) == (25.2, "live", "ALPHA", "CARGO")
    assert merged[1]["name"] == "BRAVO"
    assert merge_live(ships, [{**live[0], "t": 500}])[0]["source"] == "gfw"


def test_payload_cannot_close_its_script_block(monkeypatch):
    ship = {"name": "</script><b>", "flag": None, "type": "CARGO", "imo": None, "mmsi": "1", "lat": 25.0, "lon": 54.0, "kn": 5, "t": 0, "course": None, "trail": None, "source": "gfw"}
    monkeypatch.setattr(tracker_data, "static_parts", lambda *stamps: {"ships": [ship], "gfw_as_of": 0, "gfw_built_at": None, "water": None, "tles": []})
    monkeypatch.setattr(tracker_data, "live_parts", lambda now: ([], {"key": False, "ships": 0, "newest_age_s": None}))
    frame = pd.DataFrame([{
        "id": "d1", "scene_id": "S1", "timestamp": pd.Timestamp("2026-11-02T02:14:00Z"), "lon": 54.1, "lat": 25.1,
        "radar_class": "ship", "class_label": "Ship", "ais_label": "None", "status": "no_ais_match", "ais_source": "none",
    }])
    text = build_payload(frame, pd.Timestamp("2026-11-03T12:00:00Z"))
    assert "</" not in text
    payload = json.loads(text)
    assert payload["ships"][0]["name"] == "</script><b>"
    assert payload["detections"][0]["lead"] is False
    assert len(payload["expected"]) == 4 and payload["feed"]["passes"] == 1


@pytest.fixture
def empty_env(tmp_path, monkeypatch):
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    for name in ("detections.schema.json", "sample_detections.geojson", "sample_port_activity.json"):
        (contracts / name).write_bytes((CONTRACTS_DIR / name).read_bytes())
    monkeypatch.setenv("SEAS_CONTRACTS_DIR", str(contracts))
    monkeypatch.setenv("SEAS_DERIVED_DIR", str(tmp_path / "derived"))
    monkeypatch.setenv("SEAS_AIS_DIR", str(tmp_path / "ais"))
    return tmp_path


def test_tracker_tab_renders_with_shipped_data():
    app = AppTest.from_file(str(APP), default_timeout=60).run()
    assert not app.exception
    assert any(tab.label.endswith("Ship tracker") for tab in app.tabs)
    assert any(item.value == "Ship tracker" for item in app.subheader)


def test_tracker_tab_renders_with_no_derived_files(empty_env):
    app = AppTest.from_file(str(APP), default_timeout=60).run()
    assert not app.exception
    assert any(item.value == "Ship tracker" for item in app.subheader)
