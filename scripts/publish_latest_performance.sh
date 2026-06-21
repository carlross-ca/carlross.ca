#!/usr/bin/env bash
set -euo pipefail

SITE="${SITE:-/home/trader/carlross.ca}"
DB="${DB:-/home/trader/trading/composite.db}"

cd "$SITE"
git pull --rebase origin main
python3 scripts/update_latest_performance.py --db "$DB" --site "$SITE"
git add data/latest_performance.json
git diff --cached --quiet && exit 0
git commit -m "Update latest performance summary"
git push origin main
