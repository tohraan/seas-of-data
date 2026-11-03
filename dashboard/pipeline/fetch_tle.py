"""Fetch the current Sentinel-1 orbits (two-line elements) from CelesTrak for the Ship tracker's satellite view.

Run with: python dashboard/pipeline/fetch_tle.py
Free, no key. A TLE a few days old still places the satellite within a few km, so once a day is plenty.
"""
import json
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

OUTPUT = Path(__file__).resolve().parent.parent / "derived" / "sentinel1_tle.json"
SOURCE = "https://celestrak.org/NORAD/elements/gp.php?CATNR={}&FORMAT=TLE"
# NORAD catalogue numbers. Sentinel-1A retired in 2025, so these two are the pair imaging the Gulf now.
SATELLITES = {"S1C": 62261, "S1D": 66315}


def fetch(norad_id: int) -> list[str]:
    request = urllib.request.Request(SOURCE.format(norad_id), headers={"User-Agent": "seas-of-data/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        lines = [line.rstrip() for line in response.read().decode("ascii", "replace").splitlines() if line.strip()]
    # CelesTrak answers an unknown number with a short text message rather than an error.
    if len(lines) != 3 or not lines[0].startswith("SENTINEL-1") or not lines[1].startswith("1 ") or not lines[2].startswith("2 "):
        raise ValueError(f"CelesTrak returned something other than a Sentinel-1 TLE for {norad_id}: {lines[:1]}")
    return lines


def main() -> None:
    satellites = []
    for short, norad_id in SATELLITES.items():
        name, line1, line2 = fetch(norad_id)
        satellites.append({"id": short, "name": name.strip(), "norad": norad_id, "line1": line1, "line2": line2})
    document = {
        "source": "CelesTrak GP data",
        "fetched_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "satellites": satellites,
    }
    OUTPUT.write_text(json.dumps(document, indent=2) + "\n")
    print(f"Wrote {OUTPUT} ({', '.join(s['name'] for s in satellites)})")


if __name__ == "__main__":
    main()
