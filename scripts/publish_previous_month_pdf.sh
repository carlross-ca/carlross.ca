#!/usr/bin/env bash
set -euo pipefail

SITE="${SITE:-/home/trader/carlross.ca}"
DB="${DB:-/home/trader/trading/composite.db}"

cd "$SITE"
git pull --rebase origin main
# Retry missing reports daily, but keep published monthly snapshots frozen.
if ! python3 - "$SITE" <<'PY_CHECK'
import json
import sys
from datetime import date, timedelta
from pathlib import Path

site = Path(sys.argv[1])
previous = date.today().replace(day=1) - timedelta(days=1)
records_path = site / "data/performance_records.json"
records = json.loads(records_path.read_text()) if records_path.exists() else []
complete = any(
    str(record.get("as_of_date", "")).startswith(previous.strftime("%Y-%m-"))
    and record.get("pdf_url")
    and (site / "static" / record["pdf_url"].lstrip("/")).is_file()
    for record in records
)
sys.exit(0 if complete else 1)
PY_CHECK
then
    python3 scripts/export_performance_pdf.py --db "$DB" --site "$SITE" --completed-month previous
fi
git add content/performance static/reports/performance data/performance_records.json
if ! git diff --cached --quiet; then
    git commit -m "Publish monthly performance record"
fi
# A failed push must be retried even when the PDF already exists locally.
git push origin main
