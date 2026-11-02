#!/usr/bin/env bash
# Convert rendered PNG frames (a_0001.png, c2_0001.png ...) to WebP for the site and rewrite the frame manifest.
#   scripts/frames.sh <png dir> <width> [quality]
# Skips frames whose WebP is newer than the PNG, so it can be re-run while a render is still going.
set -euo pipefail
SRC=$1 W=$2 Q=${3:-78}
OUT=$(cd "$(dirname "$0")/.." && pwd)/public/frames
export OUT W Q

find "$SRC" -maxdepth 1 -name '*_[0-9][0-9][0-9][0-9].png' -print0 | xargs -0 -P 8 -n 1 sh -c '
  f=$1; n=$(basename "$f" .png); s=${n%_*}; d="$OUT/$s/$W"; mkdir -p "$d"
  if [ ! "$d/$n.webp" -nt "$f" ]; then cwebp -quiet -q "$Q" -resize "$W" 0 "$f" -o "$d/$n.webp"; fi
' _

# Per sequence: the widths it has, and its frame count (from its smallest width, which every render gets).
entries=()
for dir in "$OUT"/*/; do
  s=$(basename "$dir")
  widths=$(ls "$dir" | sort -n | paste -sd, -)
  count=$(ls "$dir$(ls "$dir" | sort -n | head -1)" | grep -c '\.webp$')
  entries+=("\"$s\":{\"count\":$count,\"widths\":[$widths]}")
done
(IFS=,; printf '{%s}\n' "${entries[*]}") > "$OUT/manifest.json"
echo "frames: $(find "$OUT" -name '*.webp' | wc -l | tr -d ' ') webp, $(cat "$OUT/manifest.json"), $(du -sh "$OUT" | cut -f1)"
