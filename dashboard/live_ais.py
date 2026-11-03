"""Live ship positions from the AIS reports that ml/ais/capture.py collects.

Nothing here is invented. With no reports there are no ships. Between reports, a moving ship's position is projected from
its last reported speed and course for a few minutes, and is marked as an estimate.
"""
import json
import math
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

AIS_DIR = Path(__file__).resolve().parent.parent / "ml" / "data" / "ais"
ENV_FILE = Path(__file__).resolve().parent.parent / "ml" / ".env"
WINDOW_MINUTES = 60
SILENT_AFTER_S = 15 * 60  # moving ships report every few seconds and anchored ones every few minutes
ESTIMATE_LIMIT_S = 10 * 60
MOVING_KNOTS = 1.0
FEED_STALE_S = 5 * 60
TAIL_BYTES = 64 * 1024 * 1024  # the files grow all day, and only the latest hour is needed
MAX_TRACK_POINTS = 60
KNOT_M_S = 0.514444
REPORT_COLUMNS = ["mmsi", "t", "lat", "lon", "sog", "cog", "heading", "name"]


def ais_dir() -> Path:
    return Path(os.environ.get("SEAS_AIS_DIR") or AIS_DIR)


def key_present(path: Path = ENV_FILE) -> bool:
    """Whether a live AIS key has been saved. The key itself is never read into the app."""
    try:
        return any(line.startswith("AISSTREAM_KEY=") and line.split("=", 1)[1].strip() for line in path.read_text().splitlines())
    except OSError:
        return False


def _clean(report: dict) -> dict | None:
    """Keep one report if it has a usable position. AIS uses out-of-range values to mean 'not available'."""
    lat, lon, moment = report.get("lat"), report.get("lon"), report.get("t_recv")
    if lat is None or lon is None or moment is None or not (-90 <= lat <= 90 and -180 <= lon <= 180) or report.get("mmsi") in (None, "None"):
        return None
    sog, cog, heading = report.get("sog"), report.get("cog"), report.get("heading")
    return {
        "mmsi": str(report["mmsi"]),
        "t": float(moment),
        "lat": float(lat),
        "lon": float(lon),
        "sog": float(sog) if sog is not None and 0 <= sog < 102.3 else None,
        "cog": float(cog) if cog is not None and 0 <= cog < 360 else None,
        "heading": float(heading) if heading is not None and 0 <= heading < 360 else None,
        "name": report.get("name"),
    }


def read_reports(directory: Path, now: float) -> pd.DataFrame:
    """Reports from the last hour. A line still being written, or otherwise damaged, is skipped."""
    today = datetime.fromtimestamp(now, UTC)
    oldest = now - WINDOW_MINUTES * 60
    rows = []
    for day in (today - timedelta(days=1), today):
        path = directory / f"{day:%Y-%m-%d}.jsonl"
        try:
            size = path.stat().st_size
            with path.open("rb") as handle:
                handle.seek(max(0, size - TAIL_BYTES))
                raw = handle.read()
        except OSError:
            continue
        lines = raw.decode("utf-8", "ignore").splitlines()
        for line in lines[1:] if size > TAIL_BYTES else lines:
            try:
                report = _clean(json.loads(line))
            except (ValueError, TypeError, AttributeError):
                continue
            if report and oldest <= report["t"] <= now:
                rows.append(report)
    return pd.DataFrame(rows, columns=REPORT_COLUMNS).sort_values("t")


def project(lat: float, lon: float, sog: float, cog: float, seconds: float) -> tuple[float, float]:
    metres = sog * KNOT_M_S * seconds
    bearing = math.radians(cog)
    return (
        lat + metres * math.cos(bearing) / 110540,
        lon + metres * math.sin(bearing) / (111320 * math.cos(math.radians(lat))),
    )


def ship_states(reports: pd.DataFrame, now: float) -> pd.DataFrame:
    """One row per ship: where it was last heard, where it probably is now, and how far it could have gone if it's gone quiet."""
    rows = []
    for mmsi, group in reports.groupby("mmsi", sort=False):
        last = group.iloc[-1]
        age = now - last["t"]
        sog, cog = last["sog"], last["cog"]
        known_motion = pd.notna(sog) and pd.notna(cog)
        moving = pd.notna(sog) and sog >= MOVING_KNOTS
        lat, lon = last["lat"], last["lon"]
        estimated = bool(known_motion and moving and 0 < age <= ESTIMATE_LIMIT_S)
        if estimated:
            lat, lon = project(lat, lon, sog, cog, age)
        silent = age > SILENT_AFTER_S
        names = group["name"].dropna()
        path = group[["lon", "lat"]].drop_duplicates().tail(MAX_TRACK_POINTS).to_numpy().tolist()
        rows.append({
            "mmsi": mmsi,
            "name": names.iloc[-1] if not names.empty else None,
            "status": "Not heard" if silent else ("Moving" if moving else "Stopped"),
            "lat": float(lat),
            "lon": float(lon),
            "reported_lat": float(last["lat"]),
            "reported_lon": float(last["lon"]),
            "sog": None if pd.isna(sog) else float(sog),
            "cog": None if pd.isna(cog) else float(cog),
            "age_s": float(age),
            "estimated": estimated,
            "reach_km": float(sog) * KNOT_M_S * age / 1000 if silent and moving else None,
            "track": path if len(path) > 1 else None,
        })
    columns = ["mmsi", "name", "status", "lat", "lon", "reported_lat", "reported_lon", "sog", "cog", "age_s", "estimated", "reach_km", "track"]
    return pd.DataFrame(rows, columns=columns)


def feed_summary(states: pd.DataFrame, reports: pd.DataFrame, now: float) -> dict:
    status = states["status"] if not states.empty else pd.Series(dtype=object)
    return {
        "ships": len(states),
        "moving": int((status == "Moving").sum()),
        "stopped": int((status == "Stopped").sum()),
        "not_heard": int((status == "Not heard").sum()),
        "newest_age_s": float(now - reports["t"].max()) if not reports.empty else None,
    }
