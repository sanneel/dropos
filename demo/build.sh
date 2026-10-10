#!/bin/bash
# Build the static presentation demo into dist/ (Vercel runs this; see vercel.json).
# The UI comes straight from backend/frontend, so the demo always shows the current pages.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/dist"
rm -rf "$OUT" && mkdir -p "$OUT/assets" "$OUT/demo-img"
cp -r "$ROOT/backend/frontend/assets/." "$OUT/assets/"
cp "$ROOT/demo/demo.js" "$OUT/assets/demo.js"
cp "$ROOT/demo/fixtures.json" "$OUT/fixtures.json"
cp "$ROOT/demo/img/"* "$OUT/demo-img/"
sed 's#<script src="assets/core.js#<script src="assets/demo.js"></script>\n<script src="assets/core.js#' \
  "$ROOT/backend/frontend/index.html" > "$OUT/index.html"
grep -q 'assets/demo.js' "$OUT/index.html" || { echo "demo.js was not injected into index.html" >&2; exit 1; }
echo "Static demo built in $OUT"
