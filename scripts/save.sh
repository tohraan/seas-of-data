#!/usr/bin/env bash
# Usage: scripts/save.sh "message"   — commit + push only the paths you own, on your own branch.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
branch=$(git rev-parse --abbrev-ref HEAD)
case "$branch" in
  tohraan) paths=(ml deck contracts) ;;
  aayush)  paths=(dashboard cad) ;;
  *) echo "Refusing: be on branch 'tohraan' or 'aayush' (now on '$branch')"; exit 1 ;;
esac
msg=${1:-"wip: autosave $(date +%H:%M)"}
git add -A -- "${paths[@]}"
if git diff --cached --quiet; then echo "Nothing to commit in: ${paths[*]}"; exit 0; fi
git commit -m "$msg"
git push -u origin "$branch"
