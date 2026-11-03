"""Draw a seeded, stratified random review sample and render contact sheets for visual review.

Usage: .venv/bin/python review_sheets.py --out <dir> [--per-band 30] [--seed 7]
Writes <dir>/sheet_NN.png (9 detections each: 128 px chip at 2x + 7.7 km context) and ml/reports/review_sample.json
(ordered ids per sheet). Tiles show only a number, not size or score, so the reviewer is not primed.
Verdicts are recorded in contracts/labels.csv by review_apply.py.
"""
import argparse
import json
import random
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
CH = ROOT / "contracts"
BANDS = {"tiny": ["tiny"], "small": ["small"], "medium": ["medium"], "large+": ["large", "very_large"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--per-band", type=int, default=30)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    feats = [f["properties"] for f in json.loads((CH / "detections.geojson").read_text())["features"]]
    rng = random.Random(a.seed)
    sample = []
    for band, classes in BANDS.items():
        pool = sorted(p["id"] for p in feats if p["size_class"] in classes)
        sample += rng.sample(pool, min(a.per_band, len(pool)))
    rng.shuffle(sample)  # sheets mix sizes
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    sheets = [sample[i:i + 9] for i in range(0, len(sample), 9)]
    TW, TH = 256 + 8 + 192, 256
    for n, ids in enumerate(sheets, 1):
        im = Image.new("RGB", (3 * (TW + 12), 3 * (TH + 28)), (20, 24, 30))
        dr = ImageDraw.Draw(im)
        for k, i in enumerate(ids):
            x, y = (k % 3) * (TW + 12) + 6, (k // 3) * (TH + 28) + 22
            chip = Image.open(CH / "chips" / f"{i}.png").resize((256, 256), Image.BICUBIC)
            ctx = Image.open(CH / "chips" / f"{i}_ctx.jpg").resize((192, 192), Image.BOX)
            im.paste(chip, (x, y)); im.paste(ctx, (x + 264, y))
            dr.text((x, y - 16), f"#{k + 1}", fill=(240, 240, 240))
        im.save(out / f"sheet_{n:02d}.png")
    (ROOT / "ml" / "reports" / "review_sample.json").write_text(json.dumps(
        {"seed": a.seed, "per_band": a.per_band, "bands": BANDS, "sheets": sheets}, indent=1))
    print(f"{len(sample)} sampled, {len(sheets)} sheets -> {out}")


if __name__ == "__main__":
    main()
