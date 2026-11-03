"""Everything the Ship tracker page draws, gathered into one payload.

Every position carries its source and time, so the page can say how old it is. Nothing is invented: with no live feed,
the newest positions are Global Fishing Watch's, a few days behind.
"""
import base64
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

from analysis import expected_next_passes, possible_dark
from components import ship_type_label
from data import derived_dir, ship_movement_text
from live_ais import ais_dir, feed_summary, key_present, read_reports, ship_states, water_lookup

TRAIL_HOURS = 24
# Fishing Watch rounds positions to about 1 km, so a heading from two fixes closer than that is noise.
COURSE_MIN_KM = 1.0
COURSE_MAX_GAP_HOURS = 3
WATER_STEP = 4  # 0.0005 degree cells grouped 4 by 4, about 200 m
# Assumed top speeds, in knots, for the outer reach band. Fishing Watch's types are broad, so these are generous.
TYPE_TOP_KNOTS = {
    "CARGO": 20,  # includes tankers and container ships
    "PASSENGER": 30,
    "BUNKER": 13,
    "OTHER_NON_FISHING": 25,  # tugs, pilots, service and pleasure craft
    "GEAR": 3,  # drifting fishing gear
    "INACTIVE": 20,
    "INSUFFICIENT_DATA": 25,
}
DEFAULT_TOP_KNOTS = 25
# Interferometric Wide swath, 29.1 to 46 degrees incidence from 693 km, is 344 to 617 km to the right of the ground track.
SWATH_KM = (344, 617)
AREA = {"lat": 24.925, "lon": 54.875}


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    a, b = math.radians(lat1), math.radians(lat2)
    delta = math.radians(lon2 - lon1)
    y = math.sin(delta) * math.cos(b)
    x = math.cos(a) * math.sin(b) - math.sin(a) * math.cos(b) * math.cos(delta)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def flat_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    return math.hypot((lon2 - lon1) * 111.32 * math.cos(math.radians((lat1 + lat2) / 2)), (lat2 - lat1) * 110.54)


def hour_ms(hour: str) -> int:
    return int(pd.Timestamp(hour, tz="UTC").timestamp() * 1000)


def trail_runs(fixes: list, max_gap_hours: int) -> list[list[list[float]]]:
    """The track as separate runs, broken at a silence or a jump, so no line is drawn across land or a gap in the data."""
    runs, path = [], []
    for k, fix in enumerate(fixes):
        point = [fix[3], fix[2]]
        # A moored ship repeats one position every hour, and that's a dot, not a trail.
        if not path or path[-1] != point:
            path.append(point)
        following = fixes[k + 1] if k + 1 < len(fixes) else None
        jumped = len(fix) > 5 and fix[5] == 1
        if following is None or following[1] - fix[1] > max_gap_hours or jumped:
            if len(path) > 1:
                runs.append(path)
            path = []
    return runs


def last_known(movement: dict) -> list[dict]:
    """One row per ship: its newest Fishing Watch fix, a heading where two recent fixes give one, and its last day of track."""
    hours = [hour_ms(hour) for hour in movement["hours"]]
    by_ship: dict[int, list] = {}
    for fix in movement["fixes"]:
        by_ship.setdefault(fix[0], []).append(fix)
    rows = []
    for index, ship in enumerate(movement["ships"]):
        fixes = sorted(by_ship.get(index, []), key=lambda fix: fix[1])
        if not fixes:
            continue
        last = fixes[-1]
        course = None
        if len(fixes) > 1:
            before = fixes[-2]
            jumped = len(before) > 5 and before[5] == 1
            if not jumped and last[1] - before[1] <= COURSE_MAX_GAP_HOURS and flat_km(before[2], before[3], last[2], last[3]) >= COURSE_MIN_KM:
                course = round(bearing_deg(before[2], before[3], last[2], last[3]), 1)
        trail = trail_runs([fix for fix in fixes if fix[1] >= last[1] - TRAIL_HOURS], movement.get("max_line_hours", COURSE_MAX_GAP_HOURS))
        rows.append({
            "name": ship.get("name"),
            "flag": ship.get("flag"),
            "type": ship.get("type"),
            "imo": ship.get("imo"),
            "mmsi": ship.get("mmsi"),
            "lat": last[2],
            "lon": last[3],
            "kn": last[4],
            "t": hours[last[1]],
            "course": course,
            "trail": trail or None,
            "source": "gfw",
        })
    return rows


def downsample_water(water: np.ndarray, step: int = WATER_STEP) -> np.ndarray:
    """A coarse cell is water if any of its fine cells is, so a narrow channel stays open and a reach area errs large."""
    rows, columns = water.shape[0] // step * step, water.shape[1] // step * step
    return water[:rows, :columns].reshape(rows // step, step, columns // step, step).any(axis=(1, 3))


def water_grid(path: Path) -> dict | None:
    try:
        with np.load(path) as saved:
            rows, columns = (int(size) for size in saved["shape"])
            water = np.unpackbits(saved["bits"])[: rows * columns].reshape(rows, columns).astype(bool)
            west, north, res = float(saved["west"]), float(saved["north"]), float(saved["res"])
    except (OSError, KeyError, ValueError):
        return None
    coarse = downsample_water(water)
    # The saved west and north are the centre of the first fine cell (see water_lookup), and the page wants cell edges.
    return {
        "rows": coarse.shape[0],
        "cols": coarse.shape[1],
        "west": west - res / 2,
        "north": north + res / 2,
        "res": res * WATER_STEP,
        "bits": base64.b64encode(np.packbits(coarse.ravel())).decode("ascii"),
    }


def tle_checksum_ok(line: str) -> bool:
    if len(line) != 69:
        return False
    total = sum(int(c) if c.isdigit() else 1 if c == "-" else 0 for c in line[:68])
    return line[68].isdigit() and total % 10 == int(line[68])


def tle_epoch_ms(line1: str) -> int:
    year, day = int(line1[18:20]), float(line1[20:32])
    start = pd.Timestamp(year=2000 + year if year < 57 else 1900 + year, month=1, day=1, tz="UTC")
    return int((start + pd.Timedelta(days=day - 1)).timestamp() * 1000)


def load_tles(path: Path) -> list[dict]:
    """The orbits fetch_tle.py saved, keeping only well-formed Sentinel-1 ones."""
    try:
        document = json.loads(path.read_text())
    except (OSError, ValueError):
        return []
    satellites = []
    for item in document.get("satellites", []) if isinstance(document, dict) else []:
        line1, line2, name = item.get("line1", ""), item.get("line2", ""), item.get("name", "")
        if not str(name).startswith("SENTINEL-1") or not (tle_checksum_ok(line1) and tle_checksum_ok(line2)):
            continue
        if not (line1.startswith("1 ") and line2.startswith("2 ") and line1[2:7] == line2[2:7]):
            continue
        satellites.append({"id": item.get("id") or name, "name": name, "line1": line1, "line2": line2, "epoch": tle_epoch_ms(line1)})
    return satellites


def detections_rows(frame: pd.DataFrame) -> list[dict]:
    dark = possible_dark(frame)
    rows = []
    for (_, row), lead in zip(frame.iterrows(), dark):
        rows.append({
            "id": row["id"],
            "lon": float(row["lon"]),
            "lat": float(row["lat"]),
            "t": int(pd.Timestamp(row["timestamp"]).timestamp() * 1000),
            "cls": row.get("radar_class"),
            "label": row.get("class_label"),
            "ais": row.get("ais_label"),
            "lead": bool(lead),
        })
    return rows


def _file_stamp(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


@st.cache_data(show_spinner=False)
def static_parts(movement_stamp: float, water_stamp: float, tle_stamp: float) -> dict:
    """The parts that change only when a pipeline rebuilds them. The stamps are there to bust the cache."""
    text = ship_movement_text()
    movement = json.loads(text) if text else None
    return {
        "ships": last_known(movement) if movement else [],
        "gfw_as_of": hour_ms(movement["hours"][-1]) if movement else None,
        "gfw_built_at": movement.get("built_at") if movement else None,
        "water": water_grid(derived_dir() / "water_mask.npz"),
        "tles": load_tles(derived_dir() / "sentinel1_tle.json"),
    }


def live_parts(now: float) -> tuple[list[dict], dict]:
    """Ships the live AIS collector heard in the last hour, if it's running."""
    reports = read_reports(ais_dir(), now)
    if reports.empty:
        return [], {"key": key_present(), "ships": 0, "newest_age_s": None}
    states = ship_states(reports, now, water_lookup(derived_dir() / "water_mask.npz"))
    summary = feed_summary(states, reports, now)
    rows = [{
        "mmsi": state["mmsi"],
        "name": state["name"],
        "lat": state["reported_lat"],
        "lon": state["reported_lon"],
        "kn": state["sog"],
        "course": state["cog"],
        "t": int((now - state["age_s"]) * 1000),
        "trail": state["track"],
        "source": "live",
    } for state in states.to_dict("records")]
    return rows, {"key": key_present(), "ships": summary["ships"], "newest_age_s": summary["newest_age_s"]}


def merge_live(ships: list[dict], live: list[dict]) -> list[dict]:
    """A live report replaces the same ship's older Fishing Watch fix. Ships only the live feed heard are added."""
    by_mmsi = {ship["mmsi"]: index for index, ship in enumerate(ships) if ship.get("mmsi")}
    merged = [dict(ship) for ship in ships]
    for report in live:
        index = by_mmsi.get(report["mmsi"])
        if index is None:
            merged.append({"name": report["name"], "flag": None, "type": None, "imo": None, **report})
        elif report["t"] > merged[index]["t"]:
            known = merged[index]
            merged[index] = {**known, **{key: value for key, value in report.items() if value is not None}, "name": known["name"] or report["name"]}
    return merged


def build_payload(frame: pd.DataFrame, now: pd.Timestamp) -> str:
    derived = derived_dir()
    static = static_parts(
        _file_stamp(derived / "ship_movement.json"), _file_stamp(derived / "water_mask.npz"), _file_stamp(derived / "sentinel1_tle.json")
    )
    live, feed = live_parts(now.timestamp())
    acquisitions = frame.groupby("scene_id")["timestamp"].first().sort_values()
    payload = {
        "now": int(now.timestamp() * 1000),
        "ships": merge_live(static["ships"], live),
        "detections": detections_rows(frame),
        "water": static["water"],
        "type_labels": {kind: ship_type_label(kind) for kind in {ship.get("type") for ship in static["ships"]} if kind},
        "top_knots": TYPE_TOP_KNOTS,
        "default_top_knots": DEFAULT_TOP_KNOTS,
        "tles": static["tles"],
        "swath_km": SWATH_KM,
        "area": AREA,
        "acquisitions": [{"scene": scene, "t": int(moment.timestamp() * 1000)} for scene, moment in acquisitions.items()],
        "expected": [int(moment.timestamp() * 1000) for moment in expected_next_passes(acquisitions, now, count=4)],
        "feed": {
            "passes": len(acquisitions),
            "detections": len(frame),
            "gfw_as_of": static["gfw_as_of"],
            "live": feed,
        },
    }
    # Inside a <script> block, so "</" must not end it early.
    return json.dumps(payload, separators=(",", ":"), default=str).replace("</", "<\\/")
