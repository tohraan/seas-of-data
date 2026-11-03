"""Join radar detections to REAL AIS reports. Pure functions, no network.

A detection may be called `no_ais_match` (possibly dark) only if the AIS feed demonstrably covered the scene at the
overpass time: at least MIN_VESSELS distinct vessels reported inside the scene box within +/- WINDOW_S. Otherwise the
honest label is `not_checked`: an empty AIS feed would otherwise make every ship look dark.
"""
import math
from dataclasses import dataclass

WINDOW_S = 600          # AIS reports within +/- 10 min of the overpass are usable
MIN_VESSELS = 10        # coverage test: distinct MMSIs seen in the box inside the window
KNOT = 0.514444


def metres(lon1, lat1, lon2, lat2):
    return math.hypot((lon1 - lon2) * 111320 * math.cos(math.radians(lat1)), (lat1 - lat2) * 110540)


@dataclass
class Report:
    mmsi: str
    t: float            # unix seconds
    lon: float
    lat: float
    sog: float | None = None   # knots
    cog: float | None = None   # degrees


def position_at(reports, t):
    """Position of one vessel at time t from its reports: interpolate between neighbours, or dead-reckon from the
    nearest one (needs sog and cog). Returns (lon, lat, seconds_to_nearest_report) or None outside the window."""
    rs = sorted(reports, key=lambda r: r.t)
    before = [r for r in rs if r.t <= t]
    after = [r for r in rs if r.t >= t]
    b, a = (before[-1] if before else None), (after[0] if after else None)
    if b and a and a.t > b.t:
        if min(t - b.t, a.t - t) > WINDOW_S:
            return None
        f = (t - b.t) / (a.t - b.t)
        return b.lon + f * (a.lon - b.lon), b.lat + f * (a.lat - b.lat), min(t - b.t, a.t - t)
    near = b or a
    if near is None or abs(t - near.t) > WINDOW_S:
        return None
    dt = t - near.t
    if near.sog is None or near.cog is None:
        return near.lon, near.lat, abs(dt)
    d = near.sog * KNOT * dt
    brg = math.radians(near.cog)
    return (near.lon + d * math.sin(brg) / (111320 * math.cos(math.radians(near.lat))),
            near.lat + d * math.cos(brg) / 110540, abs(dt))


def gate_m(length_m, sog, dt):
    """Allowed distance: geolocation and bounding-box slack, half the hull, plus how far it moves in the time gap."""
    return min(1500.0, 200.0 + 0.5 * (length_m or 0) + (sog or 0) * KNOT * dt)


def match(dets, reports, t_overpass, box):
    """dets: dicts with id, lon, lat, length_m. box: (lon_min, lat_min, lon_max, lat_max) of the scene area searched.
    Returns (results, info). results[id] = {"status", "mmsi", "distance_m"}; info has coverage and unmatched AIS."""
    by = {}
    for r in reports:
        by.setdefault(r.mmsi, []).append(r)
    pos = {}
    for mmsi, rs in by.items():
        p = position_at(rs, t_overpass)
        if p and box[0] <= p[0] <= box[2] and box[1] <= p[1] <= box[3]:
            pos[mmsi] = (p, max((r.sog or 0) for r in rs if abs(r.t - t_overpass) <= WINDOW_S) if any(abs(r.t - t_overpass) <= WINDOW_S for r in rs) else 0)
    covered = len(pos) >= MIN_VESSELS
    pairs = []
    for d in dets:
        for mmsi, ((lon, lat, dt), sog) in pos.items():
            dist = metres(d["lon"], d["lat"], lon, lat)
            if dist <= gate_m(d.get("length_m"), sog, dt):
                pairs.append((dist, d["id"], mmsi))
    pairs.sort()
    used_d, used_m, out = set(), set(), {}
    for dist, did, mmsi in pairs:
        if did in used_d or mmsi in used_m:
            continue
        used_d.add(did); used_m.add(mmsi)
        out[did] = {"status": "matched", "mmsi": mmsi, "distance_m": round(dist)}
    for d in dets:
        out.setdefault(d["id"], {"status": "no_ais_match" if covered else "not_checked", "mmsi": None, "distance_m": None})
    return out, {"vessels_in_window": len(pos), "coverage_ok": covered,
                 "ais_without_radar": sorted(set(pos) - used_m)}
