# carlross.ca

Hugo static site for a public, personal portfolio record.

## Content Model

- `content/performance/`: automated monthly performance records.
- `content/notes/`: manual PM notes, quarterly or annual only when useful.
- `content/methodology.md`: public methodology and disclosure.

Performance posts publish percentages only:

- portfolio TWR
- S&P 500 TR CAD benchmark TWR
- difference
- trailing 3M, trailing 12M, since-inception
- current and max drawdown
- risk breach days
- two visuals

## Export Monthly Performance

On the VPS, from the site directory:

```bash
python3 scripts/export_performance_records.py --db /home/trader/trading/composite.db --site /home/trader/carlross.ca
```

By default, this exports every monthly performance period in the reporting database.

For a specific period:

```bash
python3 scripts/export_performance_records.py --db /home/trader/trading/composite.db --site /home/trader/carlross.ca --period-key month_2026_06
```

The script writes:

- `content/performance/YYYY-MM.md`
- `static/images/performance/YYYY-MM-path.svg`
- `static/images/performance/YYYY-MM-drivers.svg`
- `data/latest_performance.json`

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
