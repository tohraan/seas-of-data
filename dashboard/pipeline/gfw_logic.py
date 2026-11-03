"""Turn Fishing Watch and sanctions data into the dashboard's files. No network here, so all of it can be tested.

Every reason attached to a ship is a checkable fact with its source. None of them says a ship did anything wrong.
"""
import csv
import io
import itertools
import math
import re
from collections import defaultdict
from datetime import UTC, datetime, timedelta

MATCH_GATE_M = 1000  # Fishing Watch rounds positions to 0.01 degrees, about 1 km
PASS_WINDOW = timedelta(minutes=30)
PORT_BOXES = {  # the same boxes as ml/postprocess.py: lon_min, lat_min, lon_max, lat_max
    "Jebel Ali": (54.95, 24.97, 55.12, 25.08),
    "Khalifa Port": (54.55, 24.76, 54.75, 24.90),
}
# Countries where a port call is worth noting because of broad sanctions on the country. Calling there isn't itself wrong.
LISTED_PORT_COUNTRIES = {"IRN": "Iran", "PRK": "North Korea", "SYR": "Syria"}
MIN_PORT_CONFIDENCE = 3  # 2 is low, 3 medium, 4 high
MAX_BELIEVABLE_KNOTS = 40  # a handful of AIS reports claim more, which would draw absurd reach rings
QUIET_MIN_HOURS = 12
QUIET_MIN_KM = 5.0
MOVING_KNOTS = 1.0
LONG_LOITER_HOURS = 24 * 14
QUIET_CHECK_MIN_LENGTH_M = 50  # small craft switch off and drift out of range all the time
MANY_FLAGS = 3
MAX_IDENTITIES_KEPT = 6
MAX_PORT_CALLS_KEPT = 12
LEVELS = {"strong": 0, "check": 1, "note": 2}


def believable_speed(speed: object) -> float:
    return float(speed) if speed and 0 <= float(speed) <= MAX_BELIEVABLE_KNOTS else 0.0


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dx = (lon2 - lon1) * 111.32 * math.cos(math.radians((lat1 + lat2) / 2))
    dy = (lat2 - lat1) * 110.54
    return math.hypot(dx, dy)


def parse_time(text: str) -> datetime:
    return datetime.fromisoformat(text)


def ship_fields(row: dict) -> dict:
    return {
        "name": row.get("shipName") or None,
        "flag": row.get("flag") or None,
        "type": row.get("vesselType") or None,
        "imo": row.get("imo") or None,
        "mmsi": row.get("mmsi") or None,
        "vessel_id": row.get("vesselId") or None,
    }


def rows_near_pass(rows: list[dict], moment: datetime) -> list[dict]:
    """A day can hold two passes, so keep only the targets from this one."""
    return [row for row in rows if abs(parse_time(row["entryTimestamp"]) - moment) <= PASS_WINDOW]


def pair_targets(ours: list[dict], theirs: list[dict], gate_m: float = MATCH_GATE_M) -> dict[int, tuple[int, float]]:
    """Pair our detections with Fishing Watch's one-to-one, closest first. Returns {our index: (their index, metres)}."""
    candidates = []
    for i, detection in enumerate(ours):
        for j, target in enumerate(theirs):
            metres = distance_km(detection["lat"], detection["lon"], target["lat"], target["lon"]) * 1000
            if metres <= gate_m:
                candidates.append((metres, i, j))
    pairs: dict[int, tuple[int, float]] = {}
    used: set[int] = set()
    for metres, i, j in sorted(candidates):
        if i not in pairs and j not in used:
            pairs[i] = (j, metres)
            used.add(j)
    return pairs


def add_nearest_ais(checks: dict[str, dict], ours: list[dict], fixes: list[dict], moment: datetime) -> None:
    """How far away the closest AIS ship was around the pass. A target with no AIS match but a ship right beside it deserves doubt."""
    hour = moment.replace(minute=0, second=0, microsecond=0)
    nearby = [
        fix for fix in fixes
        if fix.get("vesselId") and abs((parse_hour(fix["date"]) - hour).total_seconds()) <= 3600
    ]
    if not nearby:
        return
    for detection in ours:
        check = checks.get(detection["id"])
        if not check or check["check"] != "no_ais":
            continue
        closest = min(nearby, key=lambda fix: distance_km(detection["lat"], detection["lon"], fix["lat"], fix["lon"]))
        check["nearest_ais_km"] = round(distance_km(detection["lat"], detection["lon"], closest["lat"], closest["lon"]), 1)


def check_pass(ours: list[dict], matched: list[dict], unmatched: list[dict]) -> tuple[dict[str, dict], list[dict], dict]:
    """Compare one pass. Returns (a check per detection, Fishing Watch targets we have no partner for, counts)."""
    theirs = [{**row, "matched": True} for row in matched] + [{**row, "matched": False} for row in unmatched]
    pairs = pair_targets(ours, theirs)
    checks: dict[str, dict] = {}
    for i, detection in enumerate(ours):
        if i not in pairs:
            checks[detection["id"]] = {"check": "no_detection"}
            continue
        j, metres = pairs[i]
        target = theirs[j]
        check = {"check": "ais_match" if target["matched"] else "no_ais", "offset_m": round(metres)}
        if target["matched"]:
            check.update(ship_fields(target))
        checks[detection["id"]] = check
    partnered = {j for j, _ in pairs.values()}
    extra = [
        {"lat": target["lat"], "lon": target["lon"], "matched": target["matched"], **(ship_fields(target) if target["matched"] else {})}
        for j, target in enumerate(theirs) if j not in partnered
    ]
    counts = {
        "gfw_total": len(theirs),
        "gfw_matched": len(matched),
        "gfw_unmatched": len(unmatched),
        "paired": len(pairs),
        "paired_matched": sum(theirs[j]["matched"] for j, _ in pairs.values()),
        "paired_unmatched": sum(not theirs[j]["matched"] for j, _ in pairs.values()),
    }
    return checks, extra, counts


def port_near(lat: float, lon: float) -> str | None:
    for name, (lon_min, lat_min, lon_max, lat_max) in PORT_BOXES.items():
        if lon_min <= lon <= lon_max and lat_min <= lat <= lat_max:
            return name
    return None


def group_fixes(rows: list[dict]) -> dict[str, list[dict]]:
    """One position per vessel per hour, in time order. Rows with no vessel ID have no identity to follow."""
    by_vessel: dict[str, dict[str, dict]] = defaultdict(dict)
    for row in rows:
        vessel_id = row.get("vesselId")
        if vessel_id:
            by_vessel[vessel_id].setdefault(row["date"], row)
    return {vessel_id: [hours[key] for key in sorted(hours)] for vessel_id, hours in by_vessel.items()}


def parse_hour(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=UTC)


def quiet_spells(fixes: list[dict], min_hours: float = QUIET_MIN_HOURS, min_km: float = QUIET_MIN_KM) -> list[dict]:
    """Times a ship stopped appearing while inside the area, then came back somewhere else.

    A ship that leaves the area isn't counted, because both ends of the spell are inside it. A ship that sits still with
    patchy reception isn't either, because it has to reappear a real distance away.
    """
    spells = []
    for before, after in itertools.pairwise(fixes):
        hours = (parse_hour(after["date"]) - parse_hour(before["date"])).total_seconds() / 3600
        if hours < min_hours:
            continue
        km = distance_km(before["lat"], before["lon"], after["lat"], after["lon"])
        if km < min_km:
            continue
        spells.append({
            "from": before["date"],
            "to": after["date"],
            "hours": round(hours),
            "km": round(km, 1),
            "from_lat": before["lat"],
            "from_lon": before["lon"],
            "to_lat": after["lat"],
            "to_lon": after["lon"],
            "speed_before": round(believable_speed(before.get("speed")), 1),
        })
    return spells


def movement_payload(fixes_by_vessel: dict[str, list[dict]], spells_by_vessel: dict[str, list[dict]]) -> dict:
    """A compact file for the replay map: a ship table, the hours, and [ship, hour, lat, lon, speed] rows."""
    hours = sorted({fix["date"] for fixes in fixes_by_vessel.values() for fix in fixes})
    hour_index = {hour: index for index, hour in enumerate(hours)}
    ships, rows = [], []
    for vessel_id, fixes in fixes_by_vessel.items():
        index = len(ships)
        ships.append({**ship_fields(fixes[-1]), "vessel_id": vessel_id})
        rows.extend(
            [index, hour_index[fix["date"]], round(fix["lat"], 3), round(fix["lon"], 3), round(believable_speed(fix.get("speed")), 1)]
            for fix in fixes
        )
    spells = [
        {**spell, "ship": index, "name": ship["name"], "flag": ship["flag"], "type": ship["type"]}
        for index, ship in enumerate(ships)
        for spell in spells_by_vessel.get(ship["vessel_id"], [])
    ]
    return {"hours": hours, "ships": ships, "fixes": rows, "quiet_spells": spells}


def parse_ofac(text: str) -> tuple[dict[str, dict], dict[str, dict]]:
    """Vessels on the OFAC SDN list, indexed by IMO and by MMSI."""
    by_imo: dict[str, dict] = {}
    by_mmsi: dict[str, dict] = {}
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 12 or row[2].strip().lower() != "vessel":
            continue
        entry = {
            "name": row[1].strip(),
            "program": row[3].strip().replace("] [", ", "),
            "listed_type": row[6].strip(),
            "listed_flag": row[9].strip(),
        }
        remarks = row[-1]
        for imo in re.findall(r"IMO (\d{7})", remarks):
            by_imo[imo] = entry
        for mmsi in re.findall(r"MMSI (\d{9})", remarks):
            by_mmsi[mmsi] = entry
    return by_imo, by_mmsi


def port_call(event: dict) -> dict | None:
    visit = event.get("port_visit") or {}
    anchorage = visit.get("startAnchorage") or {}
    if not anchorage.get("lat"):
        return None
    return {
        "port": anchorage.get("name") or anchorage.get("topDestination") or "Unnamed anchorage",
        "country": anchorage.get("flag"),
        "lat": round(anchorage["lat"], 3),
        "lon": round(anchorage["lon"], 3),
        "start": event["start"][:16],
        "end": event["end"][:16],
        "hours": round(float(visit.get("durationHrs") or 0), 1),
        "confidence": int(visit.get("confidence") or 0),
    }


def identity_timeline(entries: list[dict]) -> list[dict]:
    """Every name and flag a hull has reported, newest first, from a search by IMO."""
    seen = {}
    for entry in entries:
        for record in entry.get("selfReportedInfo") or []:
            key = (record.get("shipname"), record.get("flag"), record.get("ssvid"))
            seen[key] = {
                "name": record.get("shipname"),
                "flag": record.get("flag"),
                "from": (record.get("transmissionDateFrom") or "")[:7],
                "to": (record.get("transmissionDateTo") or "")[:7],
            }
    return sorted(seen.values(), key=lambda item: item["to"], reverse=True)


def identity_changes(timeline: list[dict], since_year: int) -> dict:
    """Flags and names reported in recent years."""
    flags, names = [], []
    for record in timeline:
        if record["to"][:4] >= str(since_year):
            if record["flag"] and record["flag"] not in flags:
                flags.append(record["flag"])
            if record["name"] and record["name"] not in names:
                names.append(record["name"])
    return {"flags": flags, "names": names}


def same_name(first: str | None, second: str | None) -> bool:
    """Lists and AIS write names differently, such as NIRVANA and MY NIRVANA."""
    clean = lambda text: re.sub(r"[^A-Z0-9]", "", (text or "").upper())
    a, b = clean(first), clean(second)
    return bool(a and b and (a in b or b in a))


def length_m(entry: dict | None) -> float | None:
    sources = ((entry or {}).get("combinedSourcesInfo") or [{}])[0].get("bestLengthM") or []
    return round(sources[0]["value"]) if sources and sources[0].get("value") else None


def ship_reasons(ship: dict, calls: list[dict], loiter_hours: float, spells: list[dict], changes: dict, length: float | None, by_imo: dict, by_mmsi: dict, since_year: int) -> list[dict]:
    """The checkable facts worth a closer look, strongest first."""
    reasons = []

    def add(level: str, kind: str, text: str, source: str) -> None:
        reasons.append({"level": level, "kind": kind, "text": text, "source": source})

    sanction = by_imo.get(ship.get("imo") or "")
    if sanction:
        listed = f"listed as {sanction['listed_type'].lower()}, {sanction['listed_flag']}, under {sanction['program']}".replace("-0- ", "").replace("-0-", "")
        if same_name(sanction["name"], ship.get("name")) or any(same_name(sanction["name"], name) for name in changes["names"]):
            add("strong", "sanctions", f"On the US OFAC sanctions list as {sanction['name']}: its IMO number and name both match ({listed}).", "OFAC SDN list")
        else:
            add("check", "sanctions", f"Its IMO number is on the US OFAC sanctions list under the name {sanction['name']} ({listed}). The names differ, so this could be a renamed ship or a wrongly reported number.", "OFAC SDN list")
    elif by_mmsi.get(ship.get("mmsi") or ""):
        add("check", "sanctions", f"Its MMSI is on the US OFAC sanctions list under {by_mmsi[ship['mmsi']]['name']}. MMSI numbers get reused, so this needs confirming.", "OFAC SDN list")

    for code, country in LISTED_PORT_COUNTRIES.items():
        here = [call for call in calls if call["country"] == code and call["confidence"] >= MIN_PORT_CONFIDENCE]
        if here:
            latest = max(here, key=lambda call: call["start"])
            add("check", "port_country", f"{len(here)} port call(s) in {country} in the last 12 months, most recently {latest['port']} on {latest['start'][:10]}.", "Fishing Watch port visits")

    quiet_level = "check" if length and length >= QUIET_CHECK_MIN_LENGTH_M else "note"
    for spell in spells:
        add(quiet_level, "quiet", f"Not heard for {spell['hours']} hours from {spell['from'][:16]} UTC, then reappeared {spell['km']:.0f} km away, still in this area.", "Fishing Watch hourly AIS")

    if len(changes["flags"]) > 1:
        add("check" if len(changes["flags"]) >= MANY_FLAGS else "note", "flags", f"Has reported {len(changes['flags'])} flags since {since_year}: {', '.join(changes['flags'])}.", "Fishing Watch identity")
    if len(changes["names"]) > 1:
        add("note", "names", f"Has reported {len(changes['names'])} names since {since_year}: {', '.join(changes['names'][:4])}.", "Fishing Watch identity")
    if not ship.get("imo") and length and length >= 100:
        add("note", "no_imo", f"About {length:.0f} m long but reports no IMO number.", "Fishing Watch identity")
    if not ship.get("flag"):
        add("note", "no_flag", "Reports no flag.", "Fishing Watch identity")
    if loiter_hours >= LONG_LOITER_HOURS:
        add("note", "loitering", f"About {loiter_hours / 24:.0f} days loitering at sea in the last 12 months, moving under 2 knots far from shore.", "Fishing Watch loitering events")
    return sorted(reasons, key=lambda reason: LEVELS[reason["level"]])


def ship_record(ship: dict, ports_near: list[str], calls: list[dict], loiter_events: list[dict], spells: list[dict], identity: dict | None, timeline: list[dict], by_imo: dict, by_mmsi: dict, since_year: int) -> dict:
    calls = sorted(calls, key=lambda call: call["start"])
    loiter_hours = sum(float((event.get("loitering") or {}).get("totalTimeHours") or 0) for event in loiter_events)
    changes = identity_changes(timeline, since_year)
    length = length_m(identity)
    countries = sorted({call["country"] for call in calls if call["country"]})
    return {
        **ship,
        "length_m": length,
        "near": ports_near,
        "port_calls_12m": len(calls),
        "countries": countries,
        "recent_calls": calls[-MAX_PORT_CALLS_KEPT:],
        "loitering_hours_12m": round(loiter_hours),
        "identities": timeline[:MAX_IDENTITIES_KEPT],
        "reasons": ship_reasons(ship, calls, loiter_hours, spells, changes, length, by_imo, by_mmsi, since_year),
    }
