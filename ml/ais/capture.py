"""Collect real AIS from aisstream.io for the Gulf box and append it to ml/data/ais/YYYY-MM-DD.jsonl.

Usage: .venv/bin/python -m ais.capture [--hours 12] [--bbox LAT0 LON0 LAT1 LON1]     (run from ml/; needs AISSTREAM_KEY in ml/.env)
aisstream is real-time only (no history, no SLA, messages dropped if we read too slowly), so run this BEFORE a Sentinel-1
overpass to have AIS for it. Terrestrial receivers: coverage far offshore may be thin; match.py refuses to call anything
dark when too few vessels were heard. Field names follow https://aisstream.io/documentation (confirm on first run).
"""
import argparse
import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

URL = "wss://stream.aisstream.io/v0/stream"
OUT = Path(__file__).resolve().parent.parent / "data" / "ais"
GULF = (24.30, 54.20, 25.60, 55.60)   # lat0 lon0 lat1 lon1: Jebel Ali, Khalifa Port and approaches


def parse(msg, now):
    """aisstream JSON -> flat record, or None for message types we do not use."""
    kind = msg.get("MessageType")
    body = msg.get("Message", {}).get(kind) if kind else None
    if kind not in ("PositionReport", "StandardClassBPositionReport") or not body:
        return None
    meta = msg.get("MetaData", {})
    return {"mmsi": str(body.get("UserID") or meta.get("MMSI")), "lat": body.get("Latitude"), "lon": body.get("Longitude"),
            "sog": body.get("Sog"), "cog": body.get("Cog"), "heading": body.get("TrueHeading"),
            "name": (meta.get("ShipName") or "").strip() or None, "t_recv": now, "t_msg": meta.get("time_utc")}


async def run(key, bbox, seconds):
    import websockets
    OUT.mkdir(parents=True, exist_ok=True)
    end, n = time.time() + seconds, 0
    while time.time() < end:
        try:
            async with websockets.connect(URL, max_size=None) as ws:
                await ws.send(json.dumps({"APIKey": key, "BoundingBoxes": [[[bbox[0], bbox[1]], [bbox[2], bbox[3]]]],
                                          "FilterMessageTypes": ["PositionReport", "StandardClassBPositionReport"]}))
                async for raw in ws:
                    now = time.time()
                    rec = parse(json.loads(raw if isinstance(raw, str) else raw.decode()), now)
                    if rec and rec["lat"] is not None:
                        day = datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%d")
                        with open(OUT / f"{day}.jsonl", "a") as f:
                            f.write(json.dumps(rec) + "\n")
                        n += 1
                        if n % 500 == 0:
                            print(f"{n} reports", flush=True)
                    if time.time() > end:
                        return
        except Exception as exc:       # reconnect: the service gives no uptime guarantee
            print("connection lost:", exc, "- retrying in 5 s", flush=True)
            await asyncio.sleep(5)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=12)
    ap.add_argument("--bbox", type=float, nargs=4, default=GULF)
    a = ap.parse_args()
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    if not os.getenv("AISSTREAM_KEY"):
        raise SystemExit("Put AISSTREAM_KEY=... in ml/.env first (free key at aisstream.io).")
    asyncio.run(run(os.environ["AISSTREAM_KEY"], a.bbox, a.hours * 3600))
