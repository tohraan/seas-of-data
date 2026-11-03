"""Global Fishing Watch 4Wings client: SAR vessel detections, split by whether GFW matched them to AIS.

Usage: .venv/bin/python -m ais.gfw --date 2026-10-24 [--matched false|true]     (needs GFW_TOKEN in ml/.env)
Saves the raw JSON to ml/data/gfw/ and prints its shape. NOT YET RUN: the endpoint, dataset id and the `matched` filter come
from GFW's public docs (report examples), but the response layout, resolution and publication lag are unverified until the first
call with a token. Use is non-commercial only (GFW terms); credit Global Fishing Watch.
"""
import argparse
import json
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

API = "https://gateway.api.globalfishingwatch.org/v3/4wings/report"
DATASET = "public-global-sar-presence:latest"
OUT = Path(__file__).resolve().parent.parent / "data" / "gfw"
# polygon around Jebel Ali + Khalifa Port + approaches (lon, lat), same area as the sea mask
AREA = {"type": "Polygon", "coordinates": [[[54.45, 24.55], [55.30, 24.55], [55.30, 25.30], [54.45, 25.30], [54.45, 24.55]]]}


def report(token, day, matched=None):
    params = {"spatial-resolution": "HIGH", "temporal-resolution": "DAILY", "datasets[0]": DATASET,
              "date-range": f"{day},{day}", "format": "JSON", "group-by": "FLAGANDGEARTYPE"}
    if matched is not None:
        params["filters[0]"] = f"matched='{str(matched).lower()}'"
    r = requests.post(API, params=params, json={"geojson": AREA}, headers={"Authorization": f"Bearer {token}"}, timeout=120)
    r.raise_for_status()
    return r.json()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--matched", choices=["true", "false"])
    a = ap.parse_args()
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    tok = os.getenv("GFW_TOKEN")
    if not tok:
        raise SystemExit("Put GFW_TOKEN=... in ml/.env first (free token at globalfishingwatch.org/our-apis/tokens).")
    data = report(tok, a.date, None if a.matched is None else a.matched == "true")
    OUT.mkdir(parents=True, exist_ok=True)
    f = OUT / f"sar_{a.date}_{a.matched or 'all'}.json"
    f.write_text(json.dumps(data, indent=1))
    print("saved", f, "| top-level keys:", list(data)[:8] if isinstance(data, dict) else type(data))
