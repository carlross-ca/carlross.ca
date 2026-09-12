#!/usr/bin/env python3
"""Update the live performance landing-page summary without touching PDFs."""

from __future__ import annotations

import argparse
import json
import math
from datetime import date, timedelta
import sqlite3
from pathlib import Path

from export_performance_records import DEFAULT_DB, ROOT, pct, signed_pct

INCEPTION_DATE = "2026-05-01"


def latest_since_inception(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT *
        FROM fact_performance_paths_daily
        WHERE period_key='since_inception'
        ORDER BY date DESC
        LIMIT 1
        """
    ).fetchone()


def min_value(conn: sqlite3.Connection, column: str) -> float | None:
    found = conn.execute(
        f"""
        SELECT MIN({column}) AS value
        FROM fact_performance_paths_daily
        WHERE period_key='since_inception'
        """
    ).fetchone()
    return None if found is None else found["value"]


def load_existing(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def performance_chart(conn: sqlite3.Connection) -> dict:
    rows = conn.execute("SELECT date, equity_index, spx_tr_index_cad FROM fact_performance_paths_daily WHERE period_key='since_inception' ORDER BY date").fetchall()
    if not rows or rows[0]["date"] != INCEPTION_DATE:
        raise SystemExit("Performance chart requires the complete inception history.")
    start = date.fromisoformat(INCEPTION_DATE) - timedelta(days=1)
    end = date.fromisoformat(rows[-1]["date"])
    points = [(start, 100.0, 100.0)]
    for row in rows:
        values = (row["equity_index"], row["spx_tr_index_cad"])
        if any(v is None or not math.isfinite(v) or v <= 0 for v in values):
            raise SystemExit(f"Invalid performance chart values on {row['date']}")
        points.append((date.fromisoformat(row["date"]), *values))
    low = math.floor(min(v for _, a, b in points for v in (a, b)) / 5) * 5
    high = math.ceil(max(v for _, a, b in points for v in (a, b)) / 5) * 5
    high = max(high, low + 5)
    def y(value):
        return 250 - (value - low) / (high - low) * 220
    def line(column):
        return " ".join(f"{60 + (point[0]-start).days / max(1,(end-start).days) * 560:.2f},{y(point[column]):.2f}" for point in points)
    return dict(portfolio=line(1), benchmark=line(2),
                ticks=[dict(value=v, y=round(y(v), 2)) for v in range(low, high + 1, 5)],
                start=INCEPTION_DATE, end=end.isoformat(), observations=len(rows))


def write_latest(conn: sqlite3.Connection, site: Path, expected_date: str | None = None) -> dict:
    latest = latest_since_inception(conn)
    if latest is None:
        raise SystemExit("No since_inception performance path rows found.")

    if expected_date is not None and latest["date"] != expected_date:
        raise SystemExit(
            f"Refusing stale performance: expected {expected_date}, found {latest['date']}. "
            "Check the daily ETL log."
        )

    portfolio_return = float(latest["equity_index"] or 100) / 100 - 1
    benchmark_return = float(latest["spx_tr_index_cad"] or 100) / 100 - 1
    current_dd = latest["drawdown"]
    benchmark_current_dd = latest["spx_tr_drawdown_cad"]
    max_dd = min_value(conn, "drawdown")
    benchmark_max_dd = min_value(conn, "spx_tr_drawdown_cad")

    latest_path = site / "data" / "latest_performance.json"
    payload = load_existing(latest_path)
    payload.update(
        {
            "title": "Latest Performance Snapshot",
            "chart": performance_chart(conn),
            "as_of_date": latest["date"],
            "inception_date": INCEPTION_DATE,
            "month_covered": "Latest",
            "portfolio_since_inception": pct(portfolio_return),
            "benchmark_since_inception": pct(benchmark_return),
            "excess_since_inception": signed_pct(portfolio_return - benchmark_return),
            "current_drawdown": pct(current_dd),
            "max_drawdown": pct(max_dd),
            "benchmark_current_drawdown": pct(benchmark_current_dd),
            "benchmark_max_drawdown": pct(benchmark_max_dd),
            "drawdown_difference": signed_pct((current_dd or 0) - (benchmark_current_dd or 0)),
            "max_drawdown_difference": signed_pct((max_dd or 0) - (benchmark_max_dd or 0)),
            "pdf_url": "",
            "summary": "Live since-inception performance snapshot.",
        }
    )
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = latest_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(latest_path)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--site", type=Path, default=ROOT)
    parser.add_argument("--expected-date", help="Require this YYYY-MM-DD before writing.")
    args = parser.parse_args()

    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        payload = write_latest(conn, args.site, args.expected_date)
        print(f"updated latest performance through {payload['as_of_date']}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
