"""Convert HRSID (COCO json + images) into a YOLO dataset under ml/data/hrsid/.

Usage: .venv/bin/python prepare_hrsid.py <unzipped_hrsid_dir>
Official split: train + test json. We carve 10% of train into val (seeded).
"""
import json
import random
import shutil
import sys
from pathlib import Path

root = Path(sys.argv[1])
out = Path(__file__).parent / "data" / "hrsid"
random.seed(0)

images = {p.name: p for p in root.rglob("*") if p.suffix.lower() in {".jpg", ".jpeg", ".png"}}
jsons = {p.name.lower(): p for p in root.rglob("*.json")}
print(f"found {len(images)} images, jsons: {sorted(jsons)}")


def pick(name):
    if name not in jsons:
        raise SystemExit(f"missing {name}; have {sorted(jsons)}")
    return jsons[name]


def load(path):
    d = json.loads(path.read_text())
    by_img = {}
    for a in d["annotations"]:
        by_img.setdefault(a["image_id"], []).append(a)
    return [(im, by_img.get(im["id"], [])) for im in d["images"]]


def write(split, items):
    (out / "images" / split).mkdir(parents=True, exist_ok=True)
    (out / "labels" / split).mkdir(parents=True, exist_ok=True)
    n_box = skipped = 0
    for im, anns in items:
        src = images.get(Path(im["file_name"]).name)
        if src is None:
            skipped += 1
            continue
        w, h = im["width"], im["height"]
        lines = []
        for a in anns:
            x, y, bw, bh = a["bbox"]
            if bw <= 0 or bh <= 0:
                continue
            lines.append(f"0 {(x + bw / 2) / w:.6f} {(y + bh / 2) / h:.6f} {bw / w:.6f} {bh / h:.6f}")
        shutil.copy(src, out / "images" / split / src.name)
        (out / "labels" / split / (src.stem + ".txt")).write_text("\n".join(lines))
        n_box += len(lines)
    print(f"{split}: {len(items) - skipped} images, {n_box} boxes, {skipped} missing images")


train = load(pick("train2017.json"))
test = load(pick("test2017.json"))
random.shuffle(train)
k = len(train) // 10
write("val", train[:k])
write("train", train[k:])
write("test", test)

(out / "hrsid.yaml").write_text(
    f"path: {out.resolve()}\ntrain: images/train\nval: images/val\ntest: images/test\nnames:\n  0: ship\n"
)
print("wrote", out / "hrsid.yaml")
