"""Checks on the real files the dashboard ships with. A failure here usually means a file needs rebuilding, not a code bug."""
import hashlib
import itertools
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from PIL import Image

from data import CONTRACTS_DIR, DERIVED_DIR, load_detections
from live_ais import ENV_FILE, water_lookup

CONTRACT = CONTRACTS_DIR / "detections.geojson"
BUOY = Path(__file__).resolve().parents[2] / "cad" / "buoy"
JSON_FILES = ("evidence.json", "gfw_checks.json", "model_metrics.json", "ship_history.json", "ship_movement.json", "waterways.json", "wide_radar.json")
pytestmark = pytest.mark.skipif(not CONTRACT.exists() or not (DERIVED_DIR / "ship_history.json").exists(), reason="The real data isn't here.")


def read(name: str) -> dict:
    def refuse(value: str) -> None:
        raise ValueError(f"{name} contains {value}, which isn't valid JSON")

    return json.loads((DERIVED_DIR / name).read_text(), parse_constant=refuse)


@pytest.fixture(scope="module")
def detections():
    loaded = load_detections(CONTRACTS_DIR)
    assert loaded.path == CONTRACT
    return loaded.frame


@pytest.fixture(scope="module")
def movement() -> dict:
    return read("ship_movement.json")


@pytest.fixture(scope="module")
def history() -> dict:
    return read("ship_history.json")


@pytest.fixture(scope="module")
def checks() -> dict:
    return read("gfw_checks.json")


@pytest.mark.parametrize("name", JSON_FILES)
def test_every_data_file_is_valid_json(name):
    assert read(name)


def test_detections_are_complete_and_inside_the_study_area(detections):
    assert len(detections) > 0
    assert detections["id"].is_unique
    assert set(detections["radar_class"]) <= {"ship", "uncertain", "likely_fixed"}
    assert detections["lon"].between(54.45, 55.30).all()
    assert detections["lat"].between(24.55, 25.30).all()
    assert detections["timestamp"].notna().all()
    assert detections["length_m"].dropna().gt(0).all()


def test_every_detection_has_a_radar_picture(detections):
    missing = [chip for chip in detections["chip"] if not (CONTRACTS_DIR / chip).exists()]
    assert missing == []


@pytest.mark.parametrize("name", ["evidence.json", "gfw_checks.json"])
def test_derived_files_were_built_from_this_detections_file(name):
    assert read(name)["contract_sha256"] == hashlib.sha256(CONTRACT.read_bytes()).hexdigest()


def test_every_detection_has_an_ais_check(detections, checks):
    assert set(checks["detections"]) == set(detections["id"])
    assert {item["check"] for item in checks["detections"].values()} <= {"ais_match", "no_ais", "no_detection", "not_available"}


def test_ais_check_counts_add_up(detections, checks):
    by_scene = detections.set_index("id")["scene_id"]
    for item in checks["passes"]:
        results = [check["check"] for key, check in checks["detections"].items() if by_scene[key] == item["scene_id"]]
        if not item["available"]:
            assert set(results) == {"not_available"}
            continue
        assert item["gfw_total"] == item["gfw_matched"] + item["gfw_unmatched"]
        assert item["paired"] == item["paired_matched"] + item["paired_unmatched"]
        assert results.count("ais_match") == item["paired_matched"]
        assert results.count("no_ais") == item["paired_unmatched"]


def test_only_checked_targets_with_no_ais_have_a_nearest_ship_distance(checks):
    for item in checks["detections"].values():
        if "nearest_ais_km" in item:
            assert item["check"] == "no_ais"
            assert item["nearest_ais_km"] >= 0


def test_every_radar_image_opens():
    images = [item["image"] for item in read("evidence.json")["passes"]]
    images += [item["image"] for item in read("wide_radar.json")["scenes"].values()]
    assert len(images) >= 8
    for image in images:
        with Image.open(DERIVED_DIR / image) as opened:
            opened.verify()


def test_movement_hours_run_without_a_gap(movement):
    hours = [datetime.strptime(hour, "%Y-%m-%d %H:%M") for hour in movement["hours"]]
    assert all(after - before == timedelta(hours=1) for before, after in itertools.pairwise(hours))


def test_movement_rows_match_the_ship_table(movement):
    ships = movement["ships"]
    assert len({ship["vessel_id"] for ship in ships}) == len(ships)
    rows = movement["fixes"]
    assert {row[0] for row in rows} == set(range(len(ships)))
    assert all(len(row) == 5 or (len(row) == 6 and row[5] == 1) for row in rows)
    assert all(0 <= row[4] <= 40 for row in rows)
    assert sum(float(row[1]).is_integer() for row in rows) >= movement["position_checks"]["positions"]


def test_quiet_spells_meet_the_rule_and_name_a_real_ship(movement):
    assert movement["quiet_spells"]
    for spell in movement["quiet_spells"]:
        assert 0 <= spell["ship"] < len(movement["ships"])
        assert spell["hours"] >= 12
        assert spell["km"] >= 5


def test_every_history_ship_has_what_the_page_needs(history):
    ships = history["ships"]
    assert len({ship["vessel_id"] for ship in ships}) == len(ships)
    levels = {"strong": 0, "check": 1, "note": 2}
    for ship in ships:
        for key in ("last_seen", "lat", "lon", "near", "port_calls_12m", "recent_calls", "identities", "reasons"):
            assert key in ship, (ship["vessel_id"], key)
        order = [levels[reason["level"]] for reason in ship["reasons"]]
        assert order == sorted(order)
        for reason in ship["reasons"]:
            assert reason["text"] and reason["source"]
            assert "(s)" not in reason["text"]
            assert reason["level"] != "strong" or reason["kind"] == "sanctions"


def test_history_positions_are_on_navigable_water(history):
    on_water = water_lookup(DERIVED_DIR / "water_mask.npz")
    assert [ship["name"] for ship in history["ships"] if not on_water(ship["lat"], ship["lon"])] == []


def test_the_water_map_knows_sea_from_land():
    on_water = water_lookup(DERIVED_DIR / "water_mask.npz")
    assert on_water(25.2, 54.7), "open Gulf"
    assert on_water(25.08, 55.14), "Dubai Marina"
    assert not on_water(24.95, 55.25), "desert"
    assert not on_water(24.7, 55.2), "further inland"


def test_no_api_key_reached_the_shipped_files():
    if not ENV_FILE.exists():
        pytest.skip("No keys on this machine.")
    values = [line.split("=", 1)[1].strip() for line in ENV_FILE.read_text().splitlines() if "=" in line and not line.lstrip().startswith("#")]
    values = [value.encode() for value in values if value]
    shipped = [path for path in DERIVED_DIR.iterdir() if path.is_file()]
    assert [path.name for path in shipped if any(value in path.read_bytes() for value in values)] == []


def test_buoy_files_are_all_there():
    specs = json.loads((BUOY / "specs.json").read_text())
    assert specs["total_mass_kg"] > 0
    assert json.loads((BUOY / "geometry.json").read_text())
    for name in ("buoy.step", "buoy.stl", "buoy.FCStd", "DATASHEET.md"):
        assert (BUOY / name).stat().st_size > 0, name
