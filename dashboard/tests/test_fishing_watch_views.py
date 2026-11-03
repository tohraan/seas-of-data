"""The dashboard's use of Fishing Watch data, on small made-up files. Real data is covered at the end."""
import hashlib
import json
import re
import shutil
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from analysis import enrich, possible_dark
from components import reported, ship_type_label
from data import (
    CONTRACTS_DIR,
    attach_evidence,
    attach_gfw,
    load_detections,
    load_gfw_checks,
    load_ship_history,
)
from views.history import ships_frame
from views.movement import build_page, days_old

APP = Path(__file__).resolve().parent.parent / "app.py"
SHIPPED_CHECKS = Path(__file__).resolve().parent.parent / "derived" / "gfw_checks.json"


@pytest.fixture(autouse=True)
def folders(tmp_path, monkeypatch):
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    for name in ("detections.schema.json", "sample_detections.geojson", "sample_port_activity.json"):
        shutil.copy(CONTRACTS_DIR / name, contracts)
    derived = tmp_path / "derived"
    derived.mkdir()
    monkeypatch.setenv("SEAS_CONTRACTS_DIR", str(contracts))
    monkeypatch.setenv("SEAS_DERIVED_DIR", str(derived))
    monkeypatch.setenv("SEAS_AIS_DIR", str(tmp_path / "ais"))
    return contracts, derived


def write_checks(folders, detections, passes=None):
    contracts, derived = folders
    digest = hashlib.sha256((contracts / "sample_detections.geojson").read_bytes()).hexdigest()
    (derived / "gfw_checks.json").write_text(json.dumps({
        "contract_sha256": digest,
        "detections": detections,
        "passes": passes or [{"scene_id": "x", "timestamp": "2026-10-20T02:14:00Z", "available": True, "gfw_total": 3, "gfw_matched": 2, "gfw_unmatched": 1, "paired": 2, "paired_matched": 1, "paired_unmatched": 1, "gfw_only": [{"lat": 25.0, "lon": 55.0, "matched": True, "name": "ONLY THEM"}]}],
    }))


def checked_frame(folders, detections):
    write_checks(folders, detections)
    loaded = load_detections(folders[0])
    return enrich(attach_gfw(attach_evidence(loaded.frame, None), load_gfw_checks(loaded.path)))


def test_checks_built_from_another_detections_file_are_ignored(folders):
    write_checks(folders, {"d001": {"check": "no_ais"}})
    path = folders[0] / "sample_detections.geojson"
    assert load_gfw_checks(path) is not None
    path.write_text(path.read_text() + " ")
    assert load_gfw_checks(path) is None


def test_missing_checks_leave_every_detection_unchecked(folders):
    loaded = load_detections(folders[0])
    frame = enrich(attach_gfw(attach_evidence(loaded.frame, None), None))
    assert set(frame["ais_group"]) - {"Matched to a ship", "No AIS match"} <= {"Not checked"}
    assert frame["gfw_check"].isna().all()


def test_labels_for_every_check_result(folders):
    frame = checked_frame(folders, {
        "d001": {"check": "ais_match", "name": "LINDEN", "flag": "BHS", "type": "CARGO", "imo": "9285354"},
        "d002": {"check": "no_ais"},
        "d003": {"check": "no_detection"},
        "d004": {"check": "not_available"},
        "d005": {"check": "ais_match"},
    }).set_index("id")
    assert frame.loc["d001", "ais_label"] == "LINDEN (BHS)"
    assert frame.loc["d002", "ais_label"] == "No AIS match"
    assert frame.loc["d003", "ais_label"] == "Fishing Watch didn't detect it"
    assert frame.loc["d004", "ais_label"] == "Not published yet"
    assert frame.loc["d005", "ais_label"] == "name not reported"
    assert frame.loc["d001", "ais_group"] == "Matched to a ship"
    assert frame.loc["d004", "ais_group"] == "Not published yet"


def test_only_a_ship_class_target_with_no_ais_can_be_possibly_dark(folders):
    frame = checked_frame(folders, {"d001": {"check": "no_ais"}, "d002": {"check": "no_ais"}, "d003": {"check": "no_ais"}, "d004": {"check": "no_detection"}, "d005": {"check": "ais_match"}})
    frame["dark"] = None
    frame["status"] = "not_checked"
    frame["ais_source"] = "none"
    frame["radar_class"] = ["ship", "likely_fixed", "uncertain", "ship", "ship"]
    assert possible_dark(frame).tolist() == [True, False, False, False, False]


def test_blank_fields_are_said_in_plain_words():
    assert reported(pd.Series(["PAN", None, ""])).tolist() == ["PAN", "Not reported", "Not reported"]
    assert reported(pd.Series([None, None]), "Name not reported").tolist() == ["Name not reported", "Name not reported"]


def test_ship_type_labels_are_plain_words():
    assert ship_type_label("OTHER_NON_FISHING") == "Other non fishing"
    assert ship_type_label("CARGO") == "Cargo"
    assert ship_type_label("INSUFFICIENT_DATA") == "Unknown"
    assert ship_type_label(None) == "Unknown"
    assert ship_type_label("") == "Unknown"


def run_app():
    return AppTest.from_file(str(APP), default_timeout=60).run()


def explorer_table(app):
    return next(df.value for df in app.dataframe if "class_label" in df.value.columns and "seen" in df.value.columns)


def choose_all_passes(app):
    choice = next(option for option in app.selectbox(key="pass_choice").options if option.startswith("All passes"))
    app.selectbox(key="pass_choice").select(choice).run()
    assert not app.exception
    return app


def test_app_shows_the_ais_check_and_the_filter_works(folders):
    write_checks(folders, {"d001": {"check": "ais_match", "name": "LINDEN", "flag": "BHS"}, "d003": {"check": "no_detection"}})
    app = choose_all_passes(run_app())
    assert any("Global Fishing Watch" in info.value for info in app.info)
    assert "LINDEN (BHS)" in set(explorer_table(app)["ais_label"])
    app.multiselect(key="ex_ais").set_value(["Fishing Watch didn't detect it"]).run()
    assert not app.exception
    assert set(explorer_table(app)["id"]) == {"d003"}


def test_a_pass_not_published_yet_says_so(folders):
    detections = load_detections(folders[0]).frame
    write_checks(folders, {identifier: {"check": "not_available"} for identifier in detections["id"]})
    app = run_app()
    assert not app.exception
    assert next(metric.value for metric in app.metric if metric.label == "AIS check") == "Pending"


def test_fishing_watch_only_targets_stay_off_the_map_until_asked_for(folders):
    write_checks(folders, {"d001": {"check": "no_detection"}})
    app = choose_all_passes(run_app())
    count = lambda: sum(len(layer.get("data") or []) for layer in json.loads(app.get("deck_gl_json_chart")[0].proto.json)["layers"])
    before = count()
    app.toggle(key="ex_extra").set_value(True).run()
    assert not app.exception
    assert count() == before + 1


def test_methods_page_reports_the_outside_check(folders):
    write_checks(folders, {"d001": {"check": "ais_match", "name": "A"}, "d002": {"check": "no_detection"}})
    app = run_app()
    assert not app.exception
    assert any(header.value == "Checked against Global Fishing Watch" for header in app.subheader)


# Movement


MOVEMENT = {
    "hours": ["2026-10-30 00:00", "2026-10-30 01:00"],
    "ships": [{"name": "</script><b>", "flag": "PAN", "type": "CARGO", "imo": "1", "mmsi": "2", "vessel_id": "v"}],
    "fixes": [[0, 0, 25.0, 55.0, 10.0], [0, 1, 25.1, 55.0, 10.0]],
    "quiet_spells": [{"ship": 0, "name": "QUIET ONE", "flag": "PAN", "type": "CARGO", "from": "2026-10-28 00:00", "to": "2026-10-28 20:00", "hours": 20, "km": 22.1, "speed_before": 10.0}],
}


def test_replay_page_cannot_be_broken_by_a_ship_name():
    page = build_page(json.dumps(MOVEMENT), "1.0 days old.")
    assert "</script><b>" not in page
    assert re.findall(r"__[A-Z_]+__", page) == []
    assert "Powered by Global Fishing Watch" in page


def test_replay_page_carries_the_fix_that_lets_its_base_map_load():
    page = build_page(json.dumps(MOVEMENT), "1.0 days old.")
    assert page.index("Worker.prototype.postMessage") < page.index("new deck.DeckGL")


def test_replay_page_escapes_ship_data_before_showing_it():
    page = build_page(json.dumps(MOVEMENT), "1.0 days old.")
    assert 'esc(ship.name || "Name not reported")' in page
    assert 'esc(object.ship.name || "Name not reported")' in page


def test_age_of_the_newest_data():
    now = pd.Timestamp("2026-11-03 12:00", tz="UTC").to_pydatetime()
    assert days_old("2026-10-30 12:00", now) == pytest.approx(4.0)


def test_movement_tab_shows_ships_quiet_spells_and_credit(folders):
    (folders[1] / "ship_movement.json").write_text(json.dumps(MOVEMENT))
    app = run_app()
    assert not app.exception
    assert any("Recent movement" in header.value for header in app.subheader)
    quiet = next(df.value for df in app.dataframe if "speed_before" in df.value.columns)
    assert quiet["name"].tolist() == ["QUIET ONE"]
    assert not any(column.isna().any() for column in (quiet["name"], quiet["flag"]))
    assert any("Powered by Global Fishing Watch" in item.value for item in app.markdown)


def test_movement_tab_without_data_says_so(folders):
    app = run_app()
    assert not app.exception
    assert any("recent-movement data hasn't been built" in item.value for item in app.info)


# History


def ship(name="A", reasons=(), near=("Jebel Ali",), imo="1234567", calls=()):
    return {
        "name": name, "flag": "PAN", "type": "CARGO", "imo": imo, "mmsi": "351", "vessel_id": name, "last_seen": "2026-10-30 12:00", "lat": 25.0, "lon": 55.0,
        "length_m": 100, "near": list(near), "port_calls_12m": len(calls), "countries": ["ARE"], "recent_calls": list(calls), "loitering_hours_12m": 0, "reasons": list(reasons), "identities": [],
    }


STRONG = {"level": "strong", "kind": "sanctions", "text": "On the list.", "source": "OFAC SDN list"}
CHECK = {"level": "check", "kind": "port_country", "text": "Called at a port.", "source": "Fishing Watch port visits"}
NOTE = {"level": "note", "kind": "no_flag", "text": "Reports no flag.", "source": "Fishing Watch identity"}


def write_history(folders, ships):
    (folders[1] / "ship_history.json").write_text(json.dumps({"built_at": "2026-11-03T00:00:00Z", "window_days": 7, "history_from": "2025-11-03", "sanctions_list_size": 1551, "ships": ships}))


def history_table(app):
    return next(df.value for df in app.dataframe if "top_reason" in df.value.columns)


def test_history_is_ranked_strongest_first():
    frame = ships_frame({"ships": [ship("C", [NOTE]), ship("A", [STRONG]), ship("D"), ship("B", [CHECK])]})
    assert frame["name"].tolist() == ["A", "B", "C", "D"]
    assert frame["level"].tolist() == ["strong", "check", "note", "none"]


def test_history_tab_filters_and_warns_these_are_not_accusations(folders):
    write_history(folders, [ship("A", [STRONG]), ship("B", [CHECK], near=("Khalifa Port",)), ship("C", [NOTE]), ship("D")])
    app = run_app()
    assert not app.exception
    assert any("not accusations" in warning.value for warning in app.warning)
    tiles = {metric.label: metric.value for metric in app.metric}
    assert tiles["Ships here in the last 7 days"] == "4"
    assert tiles["Strong reason to check"] == "1"
    assert tiles["Other reasons to check"] == "1"
    assert tiles["Sanctions list matches"] == "1"
    assert set(history_table(app)["name"]) == {"A", "B"}
    app.radio(key="hist_show").set_value("All ships").run()
    assert set(history_table(app)["name"]) == {"A", "B", "C", "D"}
    app.multiselect(key="hist_near").set_value(["Khalifa Port"]).run()
    assert set(history_table(app)["name"]) == {"B"}
    app.multiselect(key="hist_near").set_value([]).run()
    app.text_input(key="hist_search").set_value("c").run()
    assert not app.exception
    assert set(history_table(app)["name"]) == {"C"}


def test_history_tab_without_data_says_so(folders):
    app = run_app()
    assert any("ship history hasn't been built" in item.value for item in app.info)


def test_history_loader_ignores_an_empty_file(folders):
    write_history(folders, [])
    assert load_ship_history() is None
