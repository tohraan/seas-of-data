"""Signals derived from the detections: location context, repeat sightings, watchlist priority and reach zones."""
import numpy as np
import pandas as pd

# Centres of the OpenStreetMap port extents listed in ml/VERIFICATION.md.
PORT_POSITIONS = {"Jebel Ali": (24.98, 55.06), "Khalifa Port": (24.81, 54.65)}

# Assumption: an anchored ship swings on its chain, so sightings this close count as the same spot.
REPEAT_RADIUS_KM = 0.3
STATIONARY_PASSES = 3
HIGH_CONFIDENCE = 0.7
FLAG_CONFIDENCE = 0.6
FLAG_LENGTH_M = 50
KNOTS_TO_KMH = 1.852

PRIORITY_ORDER = {"High": 0, "Medium": 1, "Low": 2, "Not flagged": 3}
DERIVED_COLUMNS = [
    "zone", "nearest_port", "nearest_port_km", "location", "size_class", "confidence_band",
    "location_id", "passes_seen", "ais_label", "priority", "reason", "map_url",
]


def haversine_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    h = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 6371 * 2 * np.arcsin(np.sqrt(h))


def _location_ids(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    """Group detections into spots: linked if within REPEAT_RADIUS_KM of each other, directly or through a chain."""
    near = haversine_km(lat[:, None], lon[:, None], lat[None, :], lon[None, :]) < REPEAT_RADIUS_KM
    ids = np.full(len(lat), -1)
    next_id = 0
    for start in range(len(lat)):
        if ids[start] >= 0:
            continue
        stack = [start]
        while stack:
            current = stack.pop()
            if ids[current] < 0:
                ids[current] = next_id
                stack.extend(np.flatnonzero(near[current] & (ids < 0)))
        next_id += 1
    return ids


def _size_class(length) -> str:
    if pd.isna(length):
        return "Unknown"
    if length < FLAG_LENGTH_M:
        return "Small"
    return "Medium" if length < 150 else "Large"


def _confidence_band(confidence: float) -> str:
    if confidence >= HIGH_CONFIDENCE:
        return "High"
    return "Medium" if confidence >= 0.5 else "Low"


def _priority(row: dict) -> tuple[str, str]:
    if not row["dark"]:
        return "Not flagged", "Matched to an AIS report"
    reasons = ["No AIS match"]
    level = 0
    if row["confidence"] >= FLAG_CONFIDENCE:
        level += 1
        reasons.append(f"strong radar return ({row['confidence']:.2f})")
    if pd.notna(row["length_m"]) and row["length_m"] >= FLAG_LENGTH_M:
        level += 1
        reasons.append(f"{row['length_m']:.0f} m long")
    if row["zone"] != "Open water":
        level = max(level, 1)
        reasons.append(f"inside the {row['zone']} area")
    if row["passes_seen"] >= STATIONARY_PASSES:
        level -= 1
        reasons.append(f"same spot in {row['passes_seen']} passes, may be anchored or a fixed structure")
    return ["Low", "Medium", "High"][max(level, 0)], "; ".join(reasons)


def enrich(detections: pd.DataFrame) -> pd.DataFrame:
    frame = detections.copy()
    if frame.empty:
        return frame.assign(**{column: pd.Series(dtype=object) for column in DERIVED_COLUMNS})

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
    frame["size_class"] = pd.to_numeric(frame["length_m"]).map(_size_class)
    frame["confidence_band"] = frame["confidence"].map(_confidence_band)
    frame["location_id"] = _location_ids(lat, lon)
    frame["passes_seen"] = frame.groupby("location_id")["scene_id"].transform("nunique")

    simulated = frame["ais_source"] == "simulated"
    frame["ais_label"] = [
        "No AIS" if dark else f"MMSI {mmsi}" + (" (simulated)" if is_simulated else "")
        for dark, mmsi, is_simulated in zip(frame["dark"], frame["mmsi"], simulated)
    ]
    priorities = [_priority(row) for row in frame.to_dict("records")]
    frame["priority"] = [priority for priority, _ in priorities]
    frame["reason"] = [reason for _, reason in priorities]
    frame["map_url"] = [
        f"https://www.openstreetmap.org/?mlat={la:.5f}&mlon={lo:.5f}#map=12/{la:.5f}/{lo:.5f}"
        for la, lo in zip(lat, lon)
    ]
    return frame


def by_priority(frame: pd.DataFrame) -> pd.DataFrame:
    order = frame["priority"].map(PRIORITY_ORDER)
    return frame.assign(_order=order).sort_values(["_order", "confidence"], ascending=[True, False]).drop(columns="_order")


def repeat_locations(frame: pd.DataFrame) -> pd.DataFrame:
    """Spots seen in more than one pass, most often seen first."""
    repeats = frame[frame["passes_seen"] >= 2]
    if repeats.empty:
        return pd.DataFrame(columns=["passes", "detections", "times_dark", "shortest_m", "longest_m", "lat", "lon", "location"])
    grouped = repeats.groupby("location_id").agg(
        passes=("scene_id", "nunique"),
        detections=("id", "size"),
        times_dark=("dark", "sum"),
        shortest_m=("length_m", "min"),
        longest_m=("length_m", "max"),
        lat=("lat", "mean"),
        lon=("lon", "mean"),
        location=("location", "first"),
    )
    return grouped.sort_values(["passes", "detections"], ascending=False).reset_index(drop=True)


def reach_km(speed_knots: float, hours: float) -> float:
    return speed_knots * KNOTS_TO_KMH * hours


def port_etas(lat: float, lon: float, speed_knots: float) -> pd.DataFrame:
    rows = []
    for port, (port_lat, port_lon) in PORT_POSITIONS.items():
        km = float(haversine_km(lat, lon, port_lat, port_lon))
        rows.append({"port": port, "km": km, "hours": km / (speed_knots * KNOTS_TO_KMH)})
    return pd.DataFrame(rows).sort_values("km")


def pass_summary(frame: pd.DataFrame) -> pd.DataFrame:
    return (
        frame.groupby("scene_id")
        .agg(time=("timestamp", "first"), detections=("id", "size"), dark=("dark", "sum"))
        .sort_values("time")
        .reset_index()
    )


def health_checks(frame: pd.DataFrame, now: pd.Timestamp) -> pd.DataFrame:
    total = len(frame)
    passes = pass_summary(frame)
    gaps = passes["time"].diff().dt.total_seconds().dropna() / 3600
    age_hours = (now - passes["time"].iloc[-1]).total_seconds() / 3600
    weak = int((frame["confidence"] < 0.5).sum())
    tiny = int((pd.to_numeric(frame["length_m"]) <= 30).sum())
    repeated = int((frame["passes_seen"] >= 2).sum())
    simulated = bool((frame["ais_source"] == "simulated").any())
    gap_text = f"{gaps.min():.0f}-{gaps.max():.0f} hours apart" if len(gaps) else "only one pass"

    rows = [
        ("Latest data", f"{age_hours:.0f} hours old", "Nothing is updating this on its own. New data needs the ML pipeline to be run again."),
        ("Satellite passes", f"{len(passes)} passes, {gap_text}", "A moving ship leaves the area between passes, so moving ships can't be followed from pass to pass."),
        ("AIS source", "Simulated" if simulated else "Real", "With simulated AIS, MMSIs are random numbers and dark flags are a simulation setting." if simulated else "Dark flags come from real AIS reports."),
        ("Weak detections", f"{weak} of {total} under 0.50 confidence", "Some are likely false alarms. The score is a detector output, not a probability."),
        ("Very small targets", f"{tiny} of {total} at 30 m or less", "At 10 m pixels that is about 3 pixels, so length and even existence are uncertain."),
        ("Repeat sightings", f"{repeated} of {total} at a spot seen in another pass", "Counting all passes together overcounts ships. These may be anchored ships or fixed structures."),
        ("Not in the data", "Heading, speed, AIS report time, vessel name, type and flag", "Without these, no real route or heading-based projection is possible."),
        ("Not in the data", "AIS reports with no radar match", "These are needed to spot AIS spoofing. The pipeline drops them today."),
    ]
    return pd.DataFrame(rows, columns=["Check", "Result", "Why it matters"])
