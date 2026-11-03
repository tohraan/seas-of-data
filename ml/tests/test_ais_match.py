import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ais.match import Report, match, position_at, gate_m

T = 1_000_000.0
BOX = (54.0, 24.0, 55.5, 25.5)


def fleet(n=12, lat0=24.8):   # enough vessels that coverage_ok is True
    return [Report(f"4000000{i:02d}", T, 54.5 + i * 0.01, lat0, 0.0, 0.0) for i in range(n)]


def test_interpolates_between_reports():
    lon, lat, dt = position_at([Report("1", T - 60, 54.0, 25.0), Report("1", T + 60, 54.002, 25.0)], T)
    assert abs(lon - 54.001) < 1e-9 and dt == 60


def test_dead_reckons_from_one_sided_report():
    lon, lat, _ = position_at([Report("1", T - 300, 54.0, 25.0, sog=10, cog=90)], T)   # 10 kn east for 5 min = 1.54 km
    assert 54.0149 < lon < 54.0153 and abs(lat - 25.0) < 1e-6


def test_outside_window_is_ignored():
    assert position_at([Report("1", T - 3600, 54.0, 25.0)], T) is None


def test_match_and_dark_when_coverage_is_good():
    reps = fleet()
    dets = [{"id": "a", "lon": 54.5, "lat": 24.8, "length_m": 100}, {"id": "b", "lon": 55.2, "lat": 25.2, "length_m": 100}]
    res, info = match(dets, reps, T, BOX)
    assert res["a"]["status"] == "matched" and res["a"]["mmsi"] == "400000000"
    assert res["b"]["status"] == "no_ais_match" and info["coverage_ok"]


def test_not_checked_when_feed_is_thin():
    res, info = match([{"id": "a", "lon": 55.2, "lat": 25.2, "length_m": 100}], fleet(3), T, BOX)
    assert res["a"]["status"] == "not_checked" and not info["coverage_ok"]


def test_one_to_one_assignment():
    reps = fleet() + [Report("999", T, 54.5003, 24.8, 0.0, 0.0)]
    dets = [{"id": "a", "lon": 54.5, "lat": 24.8, "length_m": 100}, {"id": "b", "lon": 54.5001, "lat": 24.8, "length_m": 100}]
    res, _ = match(dets, reps, T, BOX)
    assert {res["a"]["mmsi"], res["b"]["mmsi"]} == {"400000000", "999"}


def test_gate_grows_with_speed_and_gap():
    assert gate_m(100, 0, 0) == 250 and gate_m(100, 20, 300) > gate_m(100, 20, 0) and gate_m(300, 40, 600) == 1500
