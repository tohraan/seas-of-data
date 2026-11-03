from datetime import UTC, datetime

import pytest

from gfw_logic import (
    add_nearest_ais,
    believable_speed,
    check_pass,
    distance_km,
    group_fixes,
    identity_changes,
    identity_timeline,
    movement_payload,
    pair_targets,
    parse_ofac,
    port_call,
    port_near,
    quiet_spells,
    rows_near_pass,
    same_name,
    ship_reasons,
)


def fix(date, lat=25.0, lon=55.0, speed=10.0, vessel="v1", name="SHIP"):
    return {"date": date, "lat": lat, "lon": lon, "speed": speed, "vesselId": vessel, "shipName": name, "flag": "PAN", "vesselType": "CARGO", "imo": "1234567", "mmsi": "351000000"}


def test_distance_is_about_111_km_per_degree_of_latitude():
    assert distance_km(25, 55, 26, 55) == pytest.approx(110.54)


def test_pairing_is_closest_first_one_to_one_and_respects_the_gate():
    ours = [{"lat": 25.0, "lon": 55.0}, {"lat": 25.0, "lon": 55.002}, {"lat": 26.0, "lon": 55.0}]
    theirs = [{"lat": 25.0, "lon": 55.0015}]
    assert pair_targets(ours, theirs)[1][0] == 0
    assert 0 not in pair_targets(ours, theirs)
    assert 2 not in pair_targets(ours, theirs)
    assert pair_targets(ours, [{"lat": 25.0, "lon": 55.02}]) == {}


def test_pass_check_separates_ais_match_no_ais_and_no_detection():
    ours = [{"id": "a", "lat": 25.0, "lon": 55.0}, {"id": "b", "lat": 25.1, "lon": 55.0}, {"id": "c", "lat": 25.2, "lon": 55.0}]
    matched = [{"lat": 25.0, "lon": 55.001, "shipName": "LINDEN", "flag": "BHS", "vesselType": "CARGO", "imo": "9285354", "mmsi": "311", "vesselId": "x"}]
    unmatched = [{"lat": 25.1, "lon": 55.001}, {"lat": 24.7, "lon": 54.6}]
    checks, extra, counts = check_pass(ours, matched, unmatched)
    assert checks["a"]["check"] == "ais_match"
    assert checks["a"]["name"] == "LINDEN"
    assert checks["b"] == {"check": "no_ais", "offset_m": checks["b"]["offset_m"]}
    assert checks["c"] == {"check": "no_detection"}
    assert counts == {"gfw_total": 3, "gfw_matched": 1, "gfw_unmatched": 2, "paired": 2, "paired_matched": 1, "paired_unmatched": 1}
    assert extra == [{"lat": 24.7, "lon": 54.6, "matched": False}]


def test_only_targets_from_this_pass_count_when_a_day_has_two():
    moment = datetime(2026, 10, 24, 14, 23, 51, tzinfo=UTC)
    rows = [{"entryTimestamp": "2026-10-24T14:24:06Z"}, {"entryTimestamp": "2026-10-24T02:14:00Z"}]
    assert rows_near_pass(rows, moment) == [rows[0]]


def test_port_boxes():
    assert port_near(25.0, 55.06) == "Jebel Ali"
    assert port_near(24.81, 54.65) == "Khalifa Port"
    assert port_near(25.2, 54.7) is None


def test_fixes_are_grouped_sorted_and_one_per_hour_and_unknown_vessels_are_dropped():
    rows = [fix("2026-10-30 02:00"), fix("2026-10-30 01:00"), fix("2026-10-30 01:00", lat=26.0), {**fix("2026-10-30 01:00"), "vesselId": ""}]
    grouped = group_fixes(rows)
    assert list(grouped) == ["v1"]
    assert [f["date"] for f in grouped["v1"]] == ["2026-10-30 01:00", "2026-10-30 02:00"]
    assert grouped["v1"][0]["lat"] == 25.0


def test_quiet_spell_needs_a_long_gap_and_a_real_move():
    moved = [fix("2026-10-28 00:00"), fix("2026-10-28 20:00", lat=25.2)]
    spells = quiet_spells(moved)
    assert len(spells) == 1
    assert spells[0]["hours"] == 20
    assert spells[0]["km"] == pytest.approx(22.1, abs=0.2)
    assert spells[0]["speed_before"] == 10.0
    assert quiet_spells([fix("2026-10-28 00:00"), fix("2026-10-28 05:00", lat=25.2)]) == []
    assert quiet_spells([fix("2026-10-28 00:00"), fix("2026-10-28 20:00", lat=25.001)]) == []


def test_movement_file_is_compact_and_keeps_identity():
    payload = movement_payload({"v1": [fix("2026-10-30 01:00"), fix("2026-10-30 03:00", lat=25.1)], "v2": [fix("2026-10-30 02:00", name=None, vessel="v2")]}, {})
    assert payload["hours"] == ["2026-10-30 01:00", "2026-10-30 02:00", "2026-10-30 03:00"]
    assert payload["ships"][0]["name"] == "SHIP"
    assert payload["fixes"][0] == [0, 0, 25.0, 55.0, 10.0]
    assert payload["fixes"][1] == [0, 2, 25.1, 55.0, 10.0]
    assert payload["fixes"][2] == [1, 1, 25.0, 55.0, 10.0]


def test_ofac_parser_reads_vessels_only():
    text = (
        '4238,"MAR AZUL","vessel","CUBA","-0- ","CL2192","Tug","-0- ","212","Cuba","Owner","Vessel Registration Identification IMO 9187629; MMSI 271000835."\n'
        '100,"SOMEONE","individual","SDGT","-0- ","-0- ","-0- ","-0- ","-0- ","-0- ","-0- ","IMO 1111111"\n'
    )
    by_imo, by_mmsi = parse_ofac(text)
    assert set(by_imo) == {"9187629"}
    assert by_imo["9187629"]["name"] == "MAR AZUL"
    assert by_imo["9187629"]["program"] == "CUBA"
    assert by_imo["9187629"]["listed_type"] == "Tug"
    assert by_imo["9187629"]["listed_flag"] == "Cuba"
    assert set(by_mmsi) == {"271000835"}


def test_port_call_handles_missing_names_and_positions():
    event = {"start": "2026-09-01T00:00:00.000Z", "end": "2026-09-02T00:00:00.000Z", "port_visit": {"confidence": "4", "durationHrs": 24.0, "startAnchorage": {"flag": "SAU", "lat": 26.1234, "lon": 50.2, "name": None, "topDestination": "DAMMAM"}}}
    call = port_call(event)
    assert call["port"] == "DAMMAM"
    assert call["confidence"] == 4
    assert call["country"] == "SAU"
    assert port_call({"start": "x", "end": "y", "port_visit": {}}) is None


def test_identity_timeline_joins_every_search_entry_newest_first():
    entries = [
        {"selfReportedInfo": [{"shipname": "BELLAGIO", "flag": "LBR", "ssvid": "1", "transmissionDateFrom": "2024-07-01", "transmissionDateTo": "2026-04-01"}]},
        {"selfReportedInfo": [{"shipname": "BELLAGIO", "flag": "HKG", "ssvid": "2", "transmissionDateFrom": "2026-04-01", "transmissionDateTo": "2026-10-01"}]},
        {"selfReportedInfo": [{"shipname": "MAERSK BELFAST", "flag": "SGP", "ssvid": "3", "transmissionDateFrom": "2012-05-01", "transmissionDateTo": "2024-07-01"}]},
    ]
    timeline = identity_timeline(entries)
    assert [(item["name"], item["flag"]) for item in timeline] == [("BELLAGIO", "HKG"), ("BELLAGIO", "LBR"), ("MAERSK BELFAST", "SGP")]
    assert identity_changes(timeline, 2024) == {"flags": ["HKG", "LBR", "SGP"], "names": ["BELLAGIO", "MAERSK BELFAST"]}
    assert identity_changes(timeline, 2025) == {"flags": ["HKG", "LBR"], "names": ["BELLAGIO"]}
    assert identity_changes([], 2024) == {"flags": [], "names": []}


def test_names_match_despite_prefixes_and_punctuation():
    assert same_name("NIRVANA", "MY NIRVANA")
    assert same_name("MADAME GU", "MADAMEGU")
    assert not same_name("BELLAGIO", "PAOLA")
    assert not same_name(None, "PAOLA")


def test_nearest_ais_is_added_only_to_no_ais_targets_and_only_near_the_pass_hour():
    moment = datetime(2026, 10, 27, 2, 14, tzinfo=UTC)
    ours = [{"id": "a", "lat": 25.0, "lon": 55.0}, {"id": "b", "lat": 25.0, "lon": 55.0}]
    checks = {"a": {"check": "no_ais"}, "b": {"check": "ais_match"}}
    fixes = [
        fix("2026-10-27 02:00", lat=25.05),
        fix("2026-10-27 09:00", lat=25.001),
        {**fix("2026-10-27 02:00", lat=25.0001), "vesselId": ""},
    ]
    add_nearest_ais(checks, ours, fixes, moment)
    assert checks["a"]["nearest_ais_km"] == pytest.approx(5.5, abs=0.1)
    assert "nearest_ais_km" not in checks["b"]
    empty = {"a": {"check": "no_ais"}}
    add_nearest_ais(empty, ours, [], moment)
    assert "nearest_ais_km" not in empty["a"]


def test_impossible_speeds_are_ignored():
    assert believable_speed(14.0) == 14.0
    assert believable_speed(75.6) == 0.0
    assert believable_speed(None) == 0.0
    assert quiet_spells([fix("2026-10-28 00:00", speed=75.6), fix("2026-10-28 20:00", lat=25.2)])[0]["speed_before"] == 0.0


def reasons(ship=None, calls=(), loiter=0.0, spells=(), changes=None, length=None, by_imo=None, by_mmsi=None):
    base = {"imo": "1234567", "mmsi": "351000000", "flag": "PAN"}
    return ship_reasons({**base, **(ship or {})}, list(calls), loiter, list(spells), changes or {"flags": [], "names": []}, length, by_imo or {}, by_mmsi or {}, 2024)


def call(country, start="2026-09-01T00:00", confidence=4, port="BANDAR ABBAS"):
    return {"country": country, "start": start, "confidence": confidence, "port": port}


def test_clean_ship_has_no_reasons():
    assert reasons(calls=[call("ARE"), call("SAU")]) == []


def test_imo_sanctions_match_is_strong_and_comes_first():
    listing = {"name": "SHIP", "program": "IRAN", "listed_type": "Tanker", "listed_flag": "Liberia"}
    result = reasons(ship={"name": "MY SHIP"}, by_imo={"1234567": listing}, calls=[call("IRN")], length=50)
    assert result[0]["level"] == "strong"
    assert "name both match" in result[0]["text"]
    assert result[1]["kind"] == "port_country"


def test_imo_match_with_a_different_name_is_only_a_check():
    listing = {"name": "OTHER", "program": "IRAN", "listed_type": "Tanker", "listed_flag": "Liberia"}
    result = reasons(ship={"name": "SHIP"}, by_imo={"1234567": listing})
    assert result[0]["level"] == "check"
    assert "names differ" in result[0]["text"]


def test_imo_match_counts_as_strong_if_the_listed_name_is_a_former_name():
    listing = {"name": "OLD NAME", "program": "IRAN", "listed_type": "Tanker", "listed_flag": "Liberia"}
    result = reasons(ship={"name": "NEW NAME"}, by_imo={"1234567": listing}, changes={"flags": [], "names": ["NEW NAME", "OLD NAME"]})
    assert result[0]["level"] == "strong"


def test_mmsi_only_sanctions_match_is_weaker_and_says_why():
    result = reasons(by_mmsi={"351000000": {"name": "OTHER", "program": "X"}})
    assert result[0]["level"] == "check"
    assert "reused" in result[0]["text"]


def test_listed_port_needs_reasonable_confidence_and_names_the_latest_call():
    assert reasons(calls=[call("IRN", confidence=2)]) == []
    result = reasons(calls=[call("IRN", "2026-08-01T00:00", port="OLD"), call("IRN", "2026-09-01T00:00", port="NEW")])
    assert "2 port calls in Iran" in result[0]["text"]
    assert "NEW" in result[0]["text"]


def test_identity_gaps_and_changes_are_notes():
    kinds = [r["kind"] for r in reasons(ship={"imo": None, "flag": None}, length=150, changes={"flags": ["PAN", "LBR"], "names": ["A", "B"]})]
    assert set(kinds) == {"flags", "names", "no_imo", "no_flag"}
    assert not [r for r in reasons(ship={"imo": None}, length=40) if r["kind"] == "no_imo"]


def test_quiet_spell_and_long_loitering_are_reported():
    spell = {"hours": 20, "from": "2026-10-28 00:00", "km": 22.1}
    result = reasons(spells=[spell], loiter=24.0 * 20, length=120)
    assert [r["kind"] for r in result] == ["quiet", "loitering"]
    assert result[0]["level"] == "check"
    assert not reasons(loiter=24.0)


def test_small_or_unknown_craft_going_quiet_is_only_a_note():
    spell = {"hours": 20, "from": "2026-10-28 00:00", "km": 22.1}
    assert reasons(spells=[spell], length=20)[0]["level"] == "note"
    assert reasons(spells=[spell], length=None)[0]["level"] == "note"


def test_several_flags_are_a_note_and_many_are_a_check():
    assert reasons(changes={"flags": ["PAN", "LBR"], "names": []})[0]["level"] == "note"
    assert reasons(changes={"flags": ["PAN", "LBR", "HKG"], "names": []})[0]["level"] == "check"
