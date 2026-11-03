"""Global Fishing Watch 4Wings client: SAR vessel detections, split by whether GFW matched them to AIS.

Usage: .venv/bin/python -m ais.gfw --date 2026-10-24 [--matched false|true]     (needs GFW_TOKEN in ml/.env)
Saves the rows to ml/data/gfw/ and prints the row count. Verified 2026-11-03: the date range must end the day after
(`day,day+1`; `day,day` returns nothing), `group-by=VESSEL_ID` gives one row per target with lat/lon/entryTimestamp, and a
User-Agent is sent because the gateway sits behind Cloudflare. Positions are rounded to 0.01 degrees (about 1 km).
Use is non-commercial only (GFW terms); credit "Powered by Global Fishing Watch".
"""
import argparse
import json
import os
import time
from datetime import date, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

API = "https://gateway.api.globalfishingwatch.org/v3/4wings/report"
DATASET = "public-global-sar-presence:latest"
USER_AGENT = "seas-of-data-ml/0.3"
OUT = Path(__file__).resolve().parent.parent / "data" / "gfw"
# polygon around Jebel Ali + Khalifa Port + approaches (lon, lat), same area as the sea mask
AREA = {"type": "Polygon", "coordinates": [[[54.45, 24.55], [55.30, 24.55], [55.30, 25.30], [54.45, 25.30], [54.45, 24.55]]]}


def token():
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    tok = os.getenv("GFW_TOKEN")
    if not tok:
        raise SystemExit("Put GFW_TOKEN=... in ml/.env first (free token at globalfishingwatch.org/our-apis/tokens).")
    return tok


def report(token, day, matched=None, retries=4):
    """SAR targets GFW detected on one UTC day, one row per target. matched=True/False keeps AIS-matched/unmatched only."""
    nxt = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
    params = {"spatial-resolution": "HIGH", "temporal-resolution": "DAILY", "datasets[0]": DATASET,
              "date-range": f"{day},{nxt}", "format": "JSON", "group-by": "VESSEL_ID"}
    if matched is not None:
        params["filters[0]"] = f"matched='{str(matched).lower()}'"
    headers = {"Authorization": f"Bearer {token}", "User-Agent": USER_AGENT, "Accept": "application/json"}
    for attempt in range(retries):
        r = requests.post(API, params=params, json={"geojson": AREA}, headers=headers, timeout=180)
        if r.status_code in (429, 502, 503, 524) and attempt < retries - 1:
            time.sleep(20)
            continue
        r.raise_for_status()
        return [row for block in r.json().get("entries", []) for rows in block.values() for row in (rows or [])]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--matched", choices=["true", "false"])
    a = ap.parse_args()
    rows = report(token(), a.date, None if a.matched is None else a.matched == "true")
    OUT.mkdir(parents=True, exist_ok=True)
    f = OUT / f"sar_{a.date}_{a.matched or 'all'}.json"
    f.write_text(json.dumps(rows, indent=1))
    print("saved", f, "|", len(rows), "rows", "| keys:", sorted(rows[0]) if rows else [])
