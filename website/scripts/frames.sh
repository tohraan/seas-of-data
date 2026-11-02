#!/usr/bin/env bash
# Convert rendered PNG frames (a_0001.png ...) to WebP for the site and rewrite the frame manifest.
#   scripts/frames.sh <png dir> <width> [quality]
# Skips frames whose WebP is newer than the PNG, so it can be re-run while a render is still going.
set -euo pipefail
SRC=$1 W=$2 Q=${3:-78}
OUT=$(cd "$(dirname "$0")/.." && pwd)/public/frames
export OUT W Q

find "$SRC" -maxdepth 1 -name '[abc]_[0-9][0-9][0-9][0-9].png' -print0 | xargs -0 -P 8 -n 1 sh -c '
  f=$1; n=$(basename "$f" .png); s=${n%%_*}; d="$OUT/$s/$W"; mkdir -p "$d"
  if [ ! "$d/$n.webp" -nt "$f" ]; then cwebp -quiet -q "$Q" -resize "$W" 0 "$f" -o "$d/$n.webp"; fi
' _

# Widths that exist for every sequence.
widths=$(for s in a b c; do ls "$OUT/$s" 2>/dev/null || true; done | sort -n | uniq -c | awk '$1 == 3 { print $2 }' | paste -sd, -)
printf '{"widths":[%s],"a":{"count":180},"b":{"count":150},"c":{"count":180}}\n' "${widths:-960}" > "$OUT/manifest.json"
echo "frames: $(find "$OUT" -name '*.webp' | wc -l | tr -d ' ') webp, widths [${widths:-960}], $(du -sh "$OUT" | cut -f1)"
