import sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ais.gfw_join import check_pass, near_pass, pair, target

PASS = datetime(2026, 10, 24, 14, 23, 51, tzinfo=timezone.utc)
ROW = {"lon": 54.86, "lat": 24.91, "entryTimestamp": "2026-10-24T14:24:00Z", "shipName": "TEST", "flag": "PAN",
       "vesselType": "CARGO", "imo": "1", "mmsi": "2", "vesselId": "v"}


def test_pairs_one_to_one_closest_first_within_gate():
    ours = [{"id": "a", "lon": 54.860, "lat": 24.910}, {"id": "b", "lon": 54.861, "lat": 24.910}]   # b is 101 m from a
    theirs = [{"lon": 54.8612, "lat": 24.910}]
    assert pair(ours, theirs) == {1: (0, pair(ours[1:], theirs)[0][1])}   # the closer detection wins the only target
    assert pair([{"lon": 54.90, "lat": 24.91}], theirs) == {}               # about 3.9 km away: outside the 1 km gate


def test_checks_and_totals():
    ours = [{"id": "m", "lon": 54.860, "lat": 24.910}, {"id": "u", "lon": 54.700, "lat": 24.800}, {"id": "x", "lon": 55.0, "lat": 25.0}]
    theirs = [target(ROW, True), target({**ROW, "lon": 54.701, "lat": 24.800}, False), target({**ROW, "lon": 54.95, "lat": 24.70}, False)]
    checks, t = check_pass(ours, theirs)
    assert checks["m"]["check"] == "ais_match" and checks["m"]["name"] == "TEST" and checks["m"]["offset_m"] == 0
    assert checks["u"] == {"check": "no_ais", "offset_m": 101}                # no identity is attached to an unmatched target
    assert checks["x"] == {"check": "no_gfw_target"}
    assert (t["paired"], t["paired_ais_match"], t["paired_no_ais"]) == (2, 1, 1)
    assert t["gfw_targets_in_circle"] == 3 and t["found_in_circle"] == 2


def test_keeps_only_targets_near_this_pass():
    rows = [ROW, {**ROW, "entryTimestamp": "2026-10-24T02:14:00Z"}]           # the same day's other pass is 12 h away
    assert near_pass(rows, PASS) == [ROW]
