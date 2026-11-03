"""Build the map of navigable water that build_gfw.py checks ship positions against.

Run from dashboard/pipeline:
  uv run python build_water.py

Writes ../derived/water_mask.npz and ../derived/waterways.json. OpenStreetMap's response is cached in data/osm; --refresh fetches
it again. Only rerun this if the map itself needs updating, since coastlines rarely change.
"""
import argparse
import json
import urllib.parse
import urllib.request
from pathlib import Path

from water import EAST, NORTH, SOUTH, WEST, WaterMap, named_waterways, navigable_water

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = Path(__file__).resolve().parent.parent / "derived"
CACHE = ROOT / "data" / "osm" / "water.json"
OVERPASS = "https://overpass-api.de/api/interpreter"
USER_AGENT = "seas-of-data-dashboard/0.1"
# The base map leaves these out at the zoom the replay opens at, so boats on them seem to be sailing through the city.
SHOWN_WATERWAYS = ("Dubai Canal", "Dubai Creek")
KINDS = (
    'way["natural"="coastline"]',
    'way["natural"="water"]',
    'relation["natural"="water"]',
    'way["waterway"~"^(canal|river|riverbank|dock|boatyard)$"]',
    'relation["waterway"="riverbank"]',
    'way["water"]',
    'relation["water"]',
    'way["leisure"="marina"]',
    'relation["leisure"="marina"]',
    'way["landuse"="basin"]',
)


def fetch(refresh: bool) -> list[dict]:
    if not refresh and CACHE.exists():
        return json.loads(CACHE.read_text())["elements"]
    box = f"({SOUTH},{WEST},{NORTH},{EAST})"
    query = "[out:json][timeout:170];(" + "".join(f"{kind}{box};" for kind in KINDS) + ");out geom;"
    request = urllib.request.Request(OVERPASS, data=urllib.parse.urlencode({"data": query}).encode(), headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=200) as response:
        raw = response.read()
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_bytes(raw)
    return json.loads(raw)["elements"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="fetch from OpenStreetMap again")
    parser.add_argument("--out", type=Path, default=OUTPUT)
    args = parser.parse_args()
    elements = fetch(args.refresh)
    water = navigable_water(elements)
    print(f"{len(elements)} OpenStreetMap features, {water.mean():.1%} of the grid is navigable water", flush=True)
    args.out.mkdir(parents=True, exist_ok=True)
    WaterMap(water).save(args.out / "water_mask.npz")
    waterways = named_waterways(elements, SHOWN_WATERWAYS)
    (args.out / "waterways.json").write_text(json.dumps(waterways, separators=(",", ":")))
    print(f"waterways: {sorted({way['name'] for way in waterways})}", flush=True)
    for name in ("water_mask.npz", "waterways.json"):
        print(f"{name}: {(args.out / name).stat().st_size / 1e3:.0f} KB", flush=True)


if __name__ == "__main__":
    main()
