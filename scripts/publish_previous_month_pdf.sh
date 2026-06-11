#!/usr/bin/env bash
set -euo pipefail

SITE="${SITE:-/home/trader/carlross.ca}"
DB="${DB:-/home/trader/trading/composite.db}"

cd "$SITE"
git pull --rebase origin main
python3 scripts/export_performance_pdf.py --db "$DB" --site "$SITE" --completed-month previous
git add content/performance static/reports/performance data/performance_records.json data/latest_performance.json
git diff --cached --quiet && exit 0
git commit -m "Publish monthly performance record"
git push origin main
