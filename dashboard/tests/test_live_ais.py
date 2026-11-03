"""Live positions, tested on made-up reports in temporary folders. Nothing here ships to the dashboard."""
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from analysis import reach_km
from data import CONTRACTS_DIR
from live_ais import (
    ESTIMATE_LIMIT_S,
    SILENT_AFTER_S,
    feed_summary,
    key_present,
    last_write_age,
    project,
    read_reports,
    ship_states,
)

APP = Path(__file__).resolve().parent.parent / "app.py"
NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC).timestamp()


def report(mmsi="470000001", age=30, lat=25.0, lon=55.0, sog=12.0, cog=90.0, heading=90, name="TEST SHIP", now=NOW):
    return {"mmsi": mmsi, "lat": lat, "lon": lon, "sog": sog, "cog": cog, "heading": heading, "name": name, "t_recv": now - age, "t_msg": None}


def write_feed(folder: Path, reports: list[dict], now: float = NOW) -> None:
    folder.mkdir(exist_ok=True)
    day = datetime.fromtimestamp(now, UTC).strftime("%Y-%m-%d")
    with (folder / f"{day}.jsonl").open("a") as handle:
        for item in reports:
            handle.write(json.dumps(item) + "\n")


def states_for(tmp_path, reports):
    write_feed(tmp_path / "ais", reports)
    loaded = read_reports(tmp_path / "ais", NOW)
    return ship_states(loaded, NOW), loaded


def test_no_folder_means_no_ships(tmp_path):
    assert read_reports(tmp_path / "missing", NOW).empty


def test_old_reports_and_damaged_lines_are_ignored(tmp_path):
    folder = tmp_path / "ais"
    write_feed(folder, [report(age=30), report(mmsi="2", age=2 * 3600)])
    day = datetime.fromtimestamp(NOW, UTC).strftime("%Y-%m-%d")
    with (folder / f"{day}.jsonl").open("a") as handle:
        handle.write('{"mmsi": "3", "lat": 25.\n')
    assert read_reports(folder, NOW)["mmsi"].tolist() == ["470000001"]


def test_future_timestamps_are_ignored(tmp_path):
    write_feed(tmp_path / "ais", [report(age=-60)])
    assert read_reports(tmp_path / "ais", NOW).empty


def test_reports_from_yesterday_still_count_just_after_midnight(tmp_path):
    just_after_midnight = datetime(2026, 11, 3, 0, 1, tzinfo=UTC).timestamp()
    yesterday = datetime(2026, 11, 2, 23, 59, tzinfo=UTC).timestamp()
    write_feed(tmp_path / "ais", [report(now=yesterday, age=0)], now=yesterday)
    assert len(read_reports(tmp_path / "ais", just_after_midnight)) == 1


@pytest.mark.parametrize("bad", [{"lat": 91.0}, {"lon": 181.0}, {"lat": None}, {"mmsi": None}, {"mmsi": "None"}])
def test_ais_not_available_positions_are_dropped(tmp_path, bad):
    write_feed(tmp_path / "ais", [{**report(), **bad}])
    assert read_reports(tmp_path / "ais", NOW).empty


def test_ais_not_available_speed_and_course_become_unknown(tmp_path):
    states, _ = states_for(tmp_path, [report(sog=102.3, cog=360.0, heading=511)])
    row = states.iloc[0]
    assert pd.isna(row["sog"])
    assert row["status"] == "Stopped"
    assert not row["estimated"]


def test_projection_matches_distance_and_direction():
    lat, lon = project(25.0, 55.0, 10.0, 0.0, 3600)
    assert lat - 25.0 == pytest.approx(10 * 1852 / 110540, rel=1e-3)
    assert lon == pytest.approx(55.0)
    lat, lon = project(25.0, 55.0, 10.0, 90.0, 3600)
    assert lat == pytest.approx(25.0)
    assert lon > 55.0


def test_moving_ship_is_estimated_forward_from_its_last_report(tmp_path):
    states, _ = states_for(tmp_path, [report(age=60, sog=12.0, cog=90.0)])
    row = states.iloc[0]
    assert row["status"] == "Moving"
    assert row["estimated"]
    assert row["lon"] > row["reported_lon"]
    assert row["lat"] == pytest.approx(row["reported_lat"])
    assert pd.isna(row["reach_km"])


def test_stopped_ship_stays_where_it_reported(tmp_path):
    states, _ = states_for(tmp_path, [report(age=60, sog=0.1)])
    row = states.iloc[0]
    assert row["status"] == "Stopped"
    assert not row["estimated"]
    assert row["lon"] == row["reported_lon"]


def test_estimate_stops_after_the_limit_rather_than_running_away(tmp_path):
    states, _ = states_for(tmp_path, [report(age=ESTIMATE_LIMIT_S + 30)])
    row = states.iloc[0]
    assert not row["estimated"]
    assert row["lon"] == row["reported_lon"]


def test_quiet_moving_ship_gets_a_reach_from_its_real_speed(tmp_path):
    age = SILENT_AFTER_S + 300
    states, _ = states_for(tmp_path, [report(age=age, sog=10.0)])
    row = states.iloc[0]
    assert row["status"] == "Not heard"
    assert row["reach_km"] == pytest.approx(reach_km(10.0, age / 3600), rel=1e-2)


def test_quiet_stopped_ship_gets_no_reach(tmp_path):
    states, _ = states_for(tmp_path, [report(age=SILENT_AFTER_S + 300, sog=0.0)])
    assert states.iloc[0]["status"] == "Not heard"
    assert pd.isna(states.iloc[0]["reach_km"])


def test_one_row_per_ship_using_its_latest_report_and_track(tmp_path):
    states, reports = states_for(tmp_path, [
        report(age=300, lon=55.00, sog=0.0), report(age=200, lon=55.01, sog=0.0), report(age=100, lon=55.02, sog=0.0),
        report(mmsi="2", age=50, name=None, sog=0.0),
    ])
    assert len(states) == 2
    first = states[states["mmsi"] == "470000001"].iloc[0]
    assert first["reported_lon"] == 55.02
    assert len(first["track"]) == 3
    assert states[states["mmsi"] == "2"].iloc[0]["track"] is None
    summary = feed_summary(states, reports, NOW)
    assert summary["ships"] == 2
    assert summary["stopped"] == 2
    assert summary["newest_age_s"] == pytest.approx(50)


def test_key_check_needs_a_real_value_and_a_missing_file_is_fine(tmp_path):
    env = tmp_path / ".env"
    assert not key_present(env)
    env.write_text("GFW_TOKEN=abc\nAISSTREAM_KEY=\n")
    assert not key_present(env)
    env.write_text("# comment\nAISSTREAM_KEY=abc123\n")
    assert key_present(env)


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    for name in ("detections.schema.json", "sample_detections.geojson", "sample_port_activity.json"):
        (contracts / name).write_bytes((CONTRACTS_DIR / name).read_bytes())
    monkeypatch.setenv("SEAS_CONTRACTS_DIR", str(contracts))
    monkeypatch.setenv("SEAS_DERIVED_DIR", str(tmp_path / "derived"))
    monkeypatch.setenv("SEAS_AIS_DIR", str(tmp_path / "ais"))
    return tmp_path


def test_app_shows_no_ships_and_says_why_without_a_feed(app_env):
    app = AppTest.from_file(str(APP), default_timeout=60).run()
    assert not app.exception
    assert any("No live data is connected" in item.value or "nothing is collecting" in item.value for item in app.info)
    assert not any(metric.label == "Ships in the last hour" for metric in app.metric)


def test_last_write_age_uses_the_newest_file(tmp_path):
    assert last_write_age(tmp_path / "missing", NOW) is None
    assert last_write_age(tmp_path, NOW) is None
    older, newer = tmp_path / "2026-11-02.jsonl", tmp_path / "2026-11-03.jsonl"
    older.write_text("")
    newer.write_text("")
    os.utime(older, (NOW - 7200, NOW - 7200))
    os.utime(newer, (NOW - 600, NOW - 600))
    assert last_write_age(tmp_path, NOW) == pytest.approx(600)


def test_a_quiet_feed_is_not_reported_as_nothing_connected(app_env):
    now = datetime.now(UTC).timestamp()
    write_feed(app_env / "ais", [report(age=7200, now=now)], now=now)
    day_file = next((app_env / "ais").glob("*.jsonl"))
    os.utime(day_file, (now - 7200, now - 7200))
    app = AppTest.from_file(str(APP), default_timeout=60).run()
    assert not app.exception
    messages = [item.value for item in app.info]
    assert any("No ships heard here in the last hour" in message and "2.0 h ago" in message for message in messages)
    assert not any("nothing is collecting" in message or "No live data is connected" in message for message in messages)
    assert not any(metric.label == "Ships in the last hour" for metric in app.metric)


def test_app_shows_real_counts_with_a_feed(app_env):
    now = datetime.now(UTC).timestamp()
    write_feed(app_env / "ais", [
        report(mmsi="1", age=30, sog=12.0, now=now),
        report(mmsi="2", age=20, sog=0.0, now=now),
        report(mmsi="3", age=SILENT_AFTER_S + 60, sog=8.0, now=now),
    ], now=now)
    app = AppTest.from_file(str(APP), default_timeout=60).run()
    assert not app.exception
    tiles = {metric.label: metric.value for metric in app.metric}
    assert tiles["Ships in the last hour"] == "3"
    assert tiles["Moving"] == "1"
    assert tiles["Stopped"] == "1"
    assert tiles["Not heard lately"] == "1"
