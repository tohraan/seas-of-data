"""Find and download Sentinel-1 GRD scenes (VV band only) from Copernicus Data Space.

  .venv/bin/python fetch_scenes.py --list                       # public catalogue search, no login needed
  .venv/bin/python fetch_scenes.py --download --n 4             # needs ml/.env with CDSE_USER / CDSE_PASS
Scenes are saved to ml/data/scenes/<scene>_vv.tiff (the ~1.7 GB zip is deleted after extracting VV).
"""
import argparse
import os
import re
import sys
import zipfile
from pathlib import Path

import requests
from dotenv import load_dotenv

CAT = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products"
TOKEN = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
DL = "https://download.dataspace.copernicus.eu/odata/v1/Products({id})/$value"
OUT = Path(__file__).parent / "data" / "scenes"


def search(lon, lat, since, n):
    flt = (f"Collection/Name eq 'SENTINEL-1' and contains(Name,'GRDH') and not contains(Name,'COG') "
           f"and OData.CSC.Intersects(area=geography'SRID=4326;POINT({lon} {lat})') "
           f"and ContentDate/Start gt {since}T00:00:00.000Z")
    r = requests.get(CAT, params={"$filter": flt, "$orderby": "ContentDate/Start desc", "$top": n}, timeout=60)
    r.raise_for_status()
    return r.json()["value"]


def token():
    load_dotenv(Path(__file__).parent / ".env")
    u, p = os.getenv("CDSE_USER"), os.getenv("CDSE_PASS")
    if not u or not p or "example.com" in u:
        sys.exit("Fill CDSE_USER and CDSE_PASS in ml/.env first (see ml/.env.example).")
    r = requests.post(TOKEN, data={"client_id": "cdse-public", "grant_type": "password", "username": u, "password": p}, timeout=60)
    if r.status_code != 200:
        sys.exit(f"Login failed ({r.status_code}). Check username/password at dataspace.copernicus.eu.")
    return r.json()["access_token"]


def download(prod, tok):
    name = prod["Name"].removesuffix(".SAFE")
    target = OUT / f"{name}_vv.tiff"
    if target.exists():
        print("have", target.name)
        return
    OUT.mkdir(parents=True, exist_ok=True)
    zpath = OUT / f"{name}.zip"
    with requests.get(DL.format(id=prod["Id"]), headers={"Authorization": f"Bearer {tok}"}, stream=True, timeout=120) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        got = 0
        with open(zpath, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
                got += len(chunk)
                if total:
                    print(f"\r{name[:40]} {got / total:.0%}", end="", flush=True)
    print()
    with zipfile.ZipFile(zpath) as z:
        vv = [n for n in z.namelist() if re.search(r"measurement/.*-vv-.*\.tiff$", n)]
        if not vv:
            sys.exit(f"no VV tiff in {zpath.name}: {z.namelist()[:10]}")
        with z.open(vv[0]) as src, open(target, "wb") as dst:
            while chunk := src.read(1 << 20):
                dst.write(chunk)
    zpath.unlink()
    print("saved", target)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lon", type=float, default=55.06)
    ap.add_argument("--lat", type=float, default=25.01)
    ap.add_argument("--since", default="2026-10-15")
    ap.add_argument("--n", type=int, default=4)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--download", action="store_true")
    a = ap.parse_args()
    prods = search(a.lon, a.lat, a.since, a.n)
    for p in prods:
        print(p["Name"], f"{p['ContentLength'] / 1e6:.0f} MB")
    if a.download:
        tok = token()
        for p in prods:
            download(p, tok)


if __name__ == "__main__":
    main()
