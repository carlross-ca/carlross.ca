#!/usr/bin/env bash
set -euo pipefail

SITE="${SITE:-/home/trader/carlross.ca}"
DB="${DB:-/home/trader/trading/composite.db}"

cd "$SITE"
git pull --rebase origin main
python3 scripts/update_latest_performance.py --db "$DB" --site "$SITE" \
    --expected-date "$(TZ=America/Vancouver date +%F)"
git add data/latest_performance.json
if ! git diff --cached --quiet; then
    git commit -m "Update latest performance summary"
fi
# Retry a previous failed push even when this run generated no new changes.
git push origin main
