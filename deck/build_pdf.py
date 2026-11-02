"""Assemble the deck's slide files into one HTML page and print it to PDF with headless Chrome.
Usage: python3 deck/build_pdf.py <folder containing project/> <out dir>   (then run Chrome --print-to-pdf on <out>/deck.html)
Image assets uploaded to the artifact (/_blob/<id>) are mapped to local files in deck/figures via ASSETS below.
"""
import json, sys
from pathlib import Path

ASSETS = {"/_blob/b65252db3b927d8ee32cdc1605a493b6": "demo_20261102.png"}
deck, out = Path(sys.argv[1]), Path(sys.argv[2]); out.mkdir(parents=True, exist_ok=True)
fig = Path(__file__).resolve().parent / "figures"
idx = json.loads((deck / "project/deck.json").read_text())
links = "".join(f'<link rel="stylesheet" href="{f["href"]}">' for f in idx["faces"].values() if "href" in f)
secs = [(deck / f"project/slides/{i}.html").read_text() for i in idx["order"]]
for blob, name in ASSETS.items():
    secs = [s.replace(blob, (fig / name).as_uri()) for s in secs]
css = """@page{size:1920px 1080px;margin:0}*{box-sizing:border-box}html,body{margin:0;padding:0;background:#fff}
section{width:1920px;height:1080px;position:relative;overflow:hidden;page-break-after:always;break-after:page;-webkit-print-color-adjust:exact;print-color-adjust:exact}
h1,h2,h3,p{margin:0}aside{display:none}table{border-collapse:collapse}
th,td{padding:0.35em 0.6em;border-bottom:1px solid rgba(128,128,128,.4);vertical-align:top}th{font-weight:600;border-bottom:2px solid rgba(128,128,128,.6)}"""
(out / "deck.html").write_text(f'<!doctype html><meta charset="utf-8"><title>{idx["title"]}</title>{links}<style>{css}</style><body>' + "\n".join(secs))
print("wrote", out / "deck.html", len(secs), "slides")
