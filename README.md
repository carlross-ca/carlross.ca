# carlross.ca

Hugo static site for a public, personal portfolio record.

## Content Model

- `content/performance/`: automated monthly performance records.
- `content/notes/`: manual PM notes, quarterly or annual only when useful.
- `content/about.md`: public method and disclosure.

Performance posts publish percentages only:

- portfolio TWR
- S&P 500 TR CAD benchmark TWR
- difference
- trailing 3M, trailing 12M, since-inception
- current and max drawdown
- risk breach days
- two visuals

## Export Monthly Performance PDF

On the VPS, from the site directory:

```bash
python3 scripts/export_performance_pdf.py --db /home/trader/trading/composite.db --site /home/trader/carlross.ca --period-key month_2026_06
```

This writes a frozen browser-openable PDF record and a small Hugo index page:

- `static/reports/performance/YYYY-MM-performance-record.pdf`
- `content/performance/YYYY-MM.md`
- `data/performance_records.json`
- `data/latest_performance.json`

For the previous completed month:

```bash
python3 scripts/export_performance_pdf.py --db /home/trader/trading/composite.db --site /home/trader/carlross.ca --completed-month previous
```

To publish from the VPS:

```bash
bash scripts/publish_previous_month_pdf.sh
```

Schedule this monthly after reporting checks pass, not daily. The private dashboard can remain live; public monthly PDFs should be frozen records.

## Local Preview

```bash
hugo server -D
```

## Build

```bash
hugo --minify
```

## Manual Notes

Manual notes are plain markdown:

```bash
hugo new notes/2026-q2.md
```

Use them for judgment, mistakes, process changes, and risk posture. Keep the performance record automated.
