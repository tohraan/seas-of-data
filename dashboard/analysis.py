"""What the dashboard derives from the contract: location context, review ranking, pass dates and buoy siting."""
import json
import math
from datetime import timedelta

import numpy as np
import pandas as pd

# Centres of the OpenStreetMap port extents listed in ml/VERIFICATION.md.
PORT_POSITIONS = {"Jebel Ali": (24.98, 55.06), "Khalifa Port": (24.81, 54.65)}
SENTINEL1_REPEAT_DAYS = 12
KNOTS_TO_KMH = 1.852
SAME_SPOT_M = 150  # the persistence gate in contracts/manifest.json
MIN_SITE_FROM_LAND_M = 1000

CLASS_LABELS = {"ship": "Ship", "uncertain": "Uncertain", "likely_fixed": "Likely fixed"}
SIZE_LABELS = {"tiny": "Tiny", "small": "Small", "medium": "Medium", "large": "Large", "very_large": "Very large"}
SIZE_RANGES = {"tiny": "under 30 m", "small": "30-60 m", "medium": "60-120 m", "large": "120-200 m", "very_large": "over 200 m"}
REVIEW_LABELS = {"confirmed": "Looks like a ship", "rejected": "Not a ship", "unsure": "Unsure", "unreviewed": "Not reviewed"}
CHECK_LABELS = {"both": "Both", "cfar": "CFAR only", "yolo": "YOLO only"}
REAL_AIS_SOURCES = {"gfw", "aisstream"}


def haversine_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    h = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 6371 * 2 * np.arcsin(np.sqrt(h))


def possible_dark(frame: pd.DataFrame) -> pd.Series:
    """A detection may only be called possibly dark after a real AIS check. Simulated flags never count."""
    return (frame["status"] == "no_ais_match") & ~frame["ais_source"].isin(["simulated", "none"])


def _ais_label(status: str, source: object, mmsi: object) -> str:
    if status == "matched" and source != "simulated":
        return f"Matched, MMSI {mmsi}" if pd.notna(mmsi) else "Matched"
    if status == "no_ais_match" and source not in ("simulated", "none"):
        return "No AIS match"
    return "Not checked"


def enrich(detections: pd.DataFrame) -> pd.DataFrame:
    frame = detections.copy()
    if frame.empty:
        return frame.assign(**{
            column: pd.Series(dtype=object)
            for column in ("zone", "nearest_port", "nearest_port_km", "location", "class_label", "size_label",
                           "review_label", "ais_label", "check_label", "vh_label", "map_url")
        })
    lat = frame["lat"].to_numpy(float)
    lon = frame["lon"].to_numpy(float)
    names = list(PORT_POSITIONS)
    distances = np.column_stack([haversine_km(lat, lon, *PORT_POSITIONS[name]) for name in names])
    frame["nearest_port"] = [names[i] for i in distances.argmin(axis=1)]
    frame["nearest_port_km"] = distances.min(axis=1)
    frame["zone"] = frame["port"].where(frame["port"].notna(), "Open water").astype(object)
    frame["location"] = [
        f"{zone} area" if zone != "Open water" else f"Open water, {km:.0f} km from {port}"
        for zone, km, port in zip(frame["zone"], frame["nearest_port_km"], frame["nearest_port"])
    ]
    frame["class_label"] = frame["radar_class"].map(CLASS_LABELS).fillna("Unclassified")
    frame["size_label"] = frame["size_class"].map(SIZE_LABELS).fillna("Unknown")
    frame["review_label"] = frame["review"].map(REVIEW_LABELS).fillna("Not reviewed")
    frame["ais_label"] = [
        _ais_label(status, source, mmsi)
        for status, source, mmsi in zip(frame["status"], frame["ais_source"], frame["mmsi"])
    ]
    frame["check_label"] = frame["detector_check"].map(CHECK_LABELS).fillna("Not run").astype(object)
    frame["vh_label"] = [
        "Not measured" if pd.isna(value) else ("Yes" if value else "No") for value in frame["vh_confirmed"]
    ]
    frame["map_url"] = [
        f"https://www.openstreetmap.org/?mlat={la:.5f}&mlon={lo:.5f}#map=12/{la:.5f}/{lo:.5f}"
        for la, lo in zip(lat, lon)
    ]
    return frame


def sort_for_table(frame: pd.DataFrame) -> pd.DataFrame:
    order = {"ship": 0, "uncertain": 1, "likely_fixed": 2}
    ranked = frame.assign(_order=frame["radar_class"].map(order).fillna(3))
    return ranked.sort_values(["_order", "confidence"], ascending=[True, False]).drop(columns="_order")


def review_queue(frame: pd.DataFrame) -> pd.DataFrame:
    """Unreviewed detections, strongest evidence first: more independent signals, then a brighter return."""
    queue = frame[frame["review"] == "unreviewed"].copy()
    if queue.empty:
        return queue.assign(signals=pd.Series(dtype=int), why=pd.Series(dtype=object))
    both = queue["detector_check"].eq("both").to_numpy(bool)
    vh = queue["vh_confirmed"].eq(True).to_numpy(bool)
    ship = queue["radar_class"].eq("ship").to_numpy(bool)
    queue["signals"] = ship.astype(int) + both.astype(int) + vh.astype(int)
    queue["why"] = [
        "; ".join(text for flag, text in [
            (is_ship, "ship-class rule"), (is_both, "YOLO also found it"), (is_vh, "bright in VH"),
        ] if flag) or "faint or near land"
        for is_ship, is_both, is_vh in zip(ship, both, vh)
    ]
    return queue.sort_values(["signals", "contrast_db"], ascending=False, na_position="last")


def same_spot(frame: pd.DataFrame, row: pd.Series, gate_m: float = SAME_SPOT_M) -> pd.DataFrame:
    """Detections from other passes at this spot."""
    others = frame[frame["scene_id"] != row["scene_id"]]
    if others.empty:
        return others
    distances = haversine_km(others["lat"].to_numpy(float), others["lon"].to_numpy(float), row["lat"], row["lon"]) * 1000
    return others[distances <= gate_m].sort_values("timestamp")


def reach_km(speed_knots: float, hours: float) -> float:
    return speed_knots * KNOTS_TO_KMH * hours


def expected_next_passes(timestamps: pd.Series, now: pd.Timestamp, count: int = 3) -> list[pd.Timestamp]:
    """Project known acquisitions forward by the repeat cycle. An expectation, not a published schedule."""
    upcoming = set()
    for moment in pd.to_datetime(timestamps, utc=True).unique():
        future = pd.Timestamp(moment)
        while future <= now:
            future += timedelta(days=SENTINEL1_REPEAT_DAYS)
        for step in range(count):
            upcoming.add(future + timedelta(days=SENTINEL1_REPEAT_DAYS * step))
    return sorted(upcoming)[:count]


def to_geojson(frame: pd.DataFrame) -> str:
    columns = [
        "id", "scene_id", "timestamp", "product", "confidence", "snr_z", "contrast_db", "length_m", "size_class",
        "radar_class", "persistence", "review", "status", "ais_source", "port", "land_distance_m", "chip", "chip_context",
    ]
    features = []
    for row in frame.to_dict("records"):
        properties = {}
        for column in columns:
            value = row.get(column)
            if isinstance(value, pd.Timestamp):
                value = value.strftime("%Y-%m-%dT%H:%M:%SZ")
            elif not isinstance(value, (list, dict)) and pd.isna(value):
                value = None
            elif isinstance(value, np.generic):
                value = value.item()
            properties[column] = value
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [row["lon"], row["lat"]]},
            "properties": properties,
        })
    return json.dumps({"type": "FeatureCollection", "features": features})


def to_csv(frame: pd.DataFrame) -> str:
    columns = [
        "id", "radar_class", "size_class", "length_m", "contrast_db", "snr_z", "confidence", "persistence", "review",
        "status", "ais_source", "port", "location", "lat", "lon", "timestamp", "scene_id", "product",
        "detector_check", "yolo_confidence", "vh_confirmed",
    ]
    return frame[columns].to_csv(index=False)


def radio_horizon_km(height_a_m: float, height_b_m: float) -> float:
    """VHF radio horizon between two antennas over the sea, using the standard 4/3 earth approximation."""
    return 4.12 * (math.sqrt(height_a_m) + math.sqrt(height_b_m))


def unique_spots(frame: pd.DataFrame, gate_m: float = SAME_SPOT_M) -> pd.DataFrame:
    """One row per spot, so a ship seen in four passes doesn't count four times when siting a buoy."""
    kept: list[int] = []
    lat = frame["lat"].to_numpy(float)
    lon = frame["lon"].to_numpy(float)
    for index in range(len(frame)):
        if not kept or (haversine_km(lat[kept], lon[kept], lat[index], lon[index]) * 1000).min() > gate_m:
            kept.append(index)
    return frame.iloc[kept]


def rank_sites(spots: pd.DataFrame, primary_km: float, secondary_km: float, count: int = 1, primary_share: float = 1.0) -> list[dict]:
    """Pick buoy sites one at a time: the most spots newly in secondary range, among sites close to the best for primary range.

    primary_share is how close: 1.0 always takes the best primary coverage, and 0.8 accepts 80% of it to gain secondary coverage.
    Candidates are the detected spots themselves, because those are known to be water, kept away from the shore.
    Water depth isn't known here, so a real site would still need checking against a chart.
    """
    if spots.empty:
        return []
    lat = spots["lat"].to_numpy(float)
    lon = spots["lon"].to_numpy(float)
    offshore = spots["land_distance_m"].to_numpy(float)
    candidates = np.flatnonzero(~(offshore < MIN_SITE_FROM_LAND_M))
    if candidates.size == 0:
        candidates = np.arange(len(spots))
    distances = haversine_km(lat[candidates][:, None], lon[candidates][:, None], lat[None, :], lon[None, :])
    in_primary = distances <= primary_km
    in_secondary = distances <= secondary_km
    covered = np.zeros(len(spots), bool)
    covered_close = np.zeros(len(spots), bool)
    sites = []
    for _ in range(count):
        gain = (in_primary & ~covered).sum(axis=1)
        gain_close = (in_secondary & ~covered_close).sum(axis=1)
        eligible = np.flatnonzero(gain >= primary_share * gain.max())
        best = int(eligible[np.lexsort((-gain[eligible], -gain_close[eligible]))[0]])
        covered |= in_primary[best]
        covered_close |= in_secondary[best]
        sites.append({
            "lat": float(lat[candidates[best]]),
            "lon": float(lon[candidates[best]]),
            "new_primary": int(gain[best]),
            "new_secondary": int(gain_close[best]),
            "primary_total": int(covered.sum()),
            "secondary_total": int(covered_close.sum()),
        })
    return sites
