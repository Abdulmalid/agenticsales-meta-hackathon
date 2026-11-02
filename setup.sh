#!/usr/bin/env bash
# Rebuilds the full app: downloads the pre-event baseline, adds the files written during the event, applies the event changes to existing files.
set -euo pipefail
BASELINE_URL="https://github.com/Abdulmalid/agenticsales-baseline.git"
BASELINE_COMMIT="e2ddc9c0213e571c3ea2edf3f42a016ccaae7194"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="${1:-$HERE/agenticsales-full}"

[ -e "$OUT" ] && { echo "$OUT already exists; pass another folder: ./setup.sh <folder>"; exit 1; }
git -c core.autocrlf=false clone --quiet "$BASELINE_URL" "$OUT"
git -C "$OUT" checkout --quiet "$BASELINE_COMMIT"
cp -R "$HERE/new/." "$OUT/"
git -C "$OUT" apply --whitespace=nowarn "$HERE/patches/event-changes.patch"
echo "Done. The full app is in $OUT (baseline $BASELINE_COMMIT + event work). See the README there to run it."
