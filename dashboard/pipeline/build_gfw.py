"""Fetch real AIS context from Global Fishing Watch and write the dashboard's files.

Run from dashboard/pipeline, with GFW_TOKEN in ml/.env:
  uv run python build_gfw.py

Writes to ../derived/: gfw_checks.json, ship_movement.json and ship_history.json. The dashboard reads these files, so it
never needs the token. Responses are cached in data/gfw_cache for 12 hours; --refresh ignores that cache.
"""
import argparse
import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from gfw import Client, fetch_text, read_token
from gfw_logic import (
    add_nearest_ais,
    check_pass,
    group_fixes,
    identity_timeline,
    movement_payload,
    parse_ofac,
    parse_time,
    port_call,
    port_near,
    quiet_spells,
    rows_near_pass,
    ship_fields,
    ship_record,
)

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "contracts" / "detections.geojson"
OUTPUT = Path(__file__).resolve().parent.parent / "derived"
AREA = {"type": "Polygon", "coordinates": [[[54.45, 24.55], [55.30, 24.55], [55.30, 25.30], [54.45, 25.30], [54.45, 24.55]]]}
PRESENCE = "public-global-presence:latest"
SAR = "public-global-sar-presence:latest"
PORT_VISITS = "public-global-port-visits-events:latest"
LOITERING = "public-global-loitering-events:latest"
OFAC_URL = "https://www.treasury.gov/ofac/downloads/sdn.csv"
REPLAY_DAYS = 3
HISTORY_WINDOW_DAYS = 7
SEARCH_BACK_DAYS = 8
BATCH = 50
ATTRIBUTION = "Powered by Global Fishing Watch"
SOURCE_URL = "https://globalfishingwatch.org"


def day_text(day: datetime) -> str:
    return day.strftime("%Y-%m-%d")


def build_checks(client: Client, contract_bytes: bytes, now: datetime) -> dict:
    features = json.loads(contract_bytes)["features"]
    detections: dict[str, dict] = {}
    passes = []
    for scene_id in sorted({feature["properties"]["scene_id"] for feature in features}):
        ours = [
            {"id": feature["properties"]["id"], "lon": feature["geometry"]["coordinates"][0], "lat": feature["geometry"]["coordinates"][1]}
            for feature in features if feature["properties"]["scene_id"] == scene_id
        ]
        moment = parse_time(next(f["properties"]["timestamp"] for f in features if f["properties"]["scene_id"] == scene_id))
        start, end = day_text(moment), day_text(moment + timedelta(days=1))
        matched = rows_near_pass(client.report(SAR, start, end, AREA, "DAILY", True), moment)
        unmatched = rows_near_pass(client.report(SAR, start, end, AREA, "DAILY", False), moment)
        if not matched and not unmatched:
            for detection in ours:
                detections[detection["id"]] = {"check": "not_available"}
            passes.append({"scene_id": scene_id, "timestamp": moment.strftime("%Y-%m-%dT%H:%M:%SZ"), "available": False})
            print(f"{scene_id}: not published yet", flush=True)
            continue
        checks, extra, counts = check_pass(ours, matched, unmatched)
        add_nearest_ais(checks, ours, client.report(PRESENCE, start, end, AREA), moment)
        detections.update(checks)
        passes.append({"scene_id": scene_id, "timestamp": moment.strftime("%Y-%m-%dT%H:%M:%SZ"), "available": True, **counts, "gfw_only": extra})
        print(f"{scene_id}: {counts}", flush=True)
    return {
        "built_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "contract_sha256": hashlib.sha256(contract_bytes).hexdigest(),
        "attribution": ATTRIBUTION,
        "source_url": SOURCE_URL,
        "dataset": SAR,
        "passes": passes,
        "detections": detections,
    }


def fetch_presence(client: Client, now: datetime) -> tuple[list[dict], datetime]:
    """Find the newest day with data, since the feed runs a few days behind, and fetch the week up to it."""
    newest = None
    for back in range(SEARCH_BACK_DAYS):
        day = (now - timedelta(days=back)).replace(hour=0, minute=0, second=0, microsecond=0)
        rows = client.report(PRESENCE, day_text(day), day_text(day + timedelta(days=1)), AREA)
        if rows:
            newest = day
            break
    if newest is None:
        raise SystemExit("No AIS presence found in the last week.")
    all_rows = list(rows)
    for back in range(1, HISTORY_WINDOW_DAYS):
        day = newest - timedelta(days=back)
        all_rows.extend(client.report(PRESENCE, day_text(day), day_text(day + timedelta(days=1)), AREA))
    return all_rows, newest


def build_history(client: Client, fixes_by_vessel: dict[str, list[dict]], spells_by_vessel: dict[str, list[dict]], now: datetime) -> dict:
    since = now - timedelta(days=365)
    start, end = day_text(since), day_text(now + timedelta(days=1))
    since_year = now.year - 2
    vessel_ids = list(fixes_by_vessel)
    calls_by_vessel: dict[str, list[dict]] = defaultdict(list)
    loiter_by_vessel: dict[str, list[dict]] = defaultdict(list)
    identity_by_vessel: dict[str, dict] = {}
    timeline_by_imo: dict[str, list[dict]] = {}
    imos = sorted({fixes[-1]["imo"] for fixes in fixes_by_vessel.values() if fixes[-1].get("imo")})
    for number, imo in enumerate(imos, 1):
        timeline_by_imo[imo] = identity_timeline(client.search_by_imo(imo))
        if number % 50 == 0:
            print(f"identity history {number} of {len(imos)}", flush=True)
    batches = [vessel_ids[i : i + BATCH] for i in range(0, len(vessel_ids), BATCH)]
    for number, batch in enumerate(batches, 1):
        for event in client.events(PORT_VISITS, start, end, vessels=batch):
            call = port_call(event)
            # Events that merely overlap the window can have started years ago.
            if call and call["end"] >= start:
                calls_by_vessel[event["vessel"]["id"]].append(call)
        for event in client.events(LOITERING, start, end, vessels=batch):
            loiter_by_vessel[event["vessel"]["id"]].append(event)
        for entry in client.identities(batch):
            for record in entry.get("selfReportedInfo") or []:
                identity_by_vessel[record.get("id")] = entry
        print(f"history batch {number} of {len(batches)}, {client.calls} calls so far", flush=True)

    by_imo, by_mmsi = parse_ofac(fetch_text(OFAC_URL))
    print(f"OFAC list: {len(by_imo)} vessels by IMO, {len(by_mmsi)} by MMSI", flush=True)
    ships = []
    for vessel_id, fixes in fixes_by_vessel.items():
        near = sorted({port for port in (port_near(fix["lat"], fix["lon"]) for fix in fixes) if port})
        ships.append(ship_record(
            {**ship_fields(fixes[-1]), "vessel_id": vessel_id, "last_seen": fixes[-1]["date"], "lat": fixes[-1]["lat"], "lon": fixes[-1]["lon"]},
            near,
            calls_by_vessel.get(vessel_id, []),
            loiter_by_vessel.get(vessel_id, []),
            spells_by_vessel.get(vessel_id, []),
            identity_by_vessel.get(vessel_id),
            timeline_by_imo.get(fixes[-1].get("imo") or "", []),
            by_imo,
            by_mmsi,
            since_year,
        ))
    return {
        "built_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "attribution": ATTRIBUTION,
        "source_url": SOURCE_URL,
        "window_days": HISTORY_WINDOW_DAYS,
        "history_from": start,
        "sanctions_list_size": len(by_imo),
        "ships": ships,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="ignore the 12-hour response cache")
    parser.add_argument("--out", type=Path, default=OUTPUT)
    args = parser.parse_args()
    now = datetime.now(UTC)
    client = Client(read_token(), refresh=args.refresh)
    args.out.mkdir(parents=True, exist_ok=True)

    checks = build_checks(client, CONTRACT.read_bytes(), now)
    (args.out / "gfw_checks.json").write_text(json.dumps(checks, separators=(",", ":")))

    rows, newest = fetch_presence(client, now)
    fixes_by_vessel = group_fixes(rows)
    spells_by_vessel = {vessel_id: quiet_spells(fixes) for vessel_id, fixes in fixes_by_vessel.items()}
    print(f"AIS presence: {len(rows)} rows, {len(fixes_by_vessel)} ships, newest day {day_text(newest)}, quiet spells {sum(map(len, spells_by_vessel.values()))}", flush=True)
    replay_from = (newest - timedelta(days=REPLAY_DAYS - 1)).strftime("%Y-%m-%d")
    recent = {vessel_id: [fix for fix in fixes if fix["date"] >= replay_from] for vessel_id, fixes in fixes_by_vessel.items()}
    recent = {vessel_id: fixes for vessel_id, fixes in recent.items() if fixes}
    recent_spells = {vessel_id: [spell for spell in spells_by_vessel.get(vessel_id, []) if spell["from"] >= replay_from] for vessel_id in recent}
    movement = {
        "built_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "attribution": ATTRIBUTION,
        "source_url": SOURCE_URL,
        "dataset": PRESENCE,
        **movement_payload(recent, recent_spells),
    }
    (args.out / "ship_movement.json").write_text(json.dumps(movement, separators=(",", ":")))

    history = build_history(client, fixes_by_vessel, spells_by_vessel, now)
    (args.out / "ship_history.json").write_text(json.dumps(history, separators=(",", ":")))

    for name in ("gfw_checks.json", "ship_movement.json", "ship_history.json"):
        print(f"{name}: {(args.out / name).stat().st_size / 1e6:.2f} MB", flush=True)
    print(f"done in {client.calls} API calls", flush=True)


if __name__ == "__main__":
    main()
