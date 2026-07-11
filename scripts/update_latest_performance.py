#!/usr/bin/env python3
"""Update the live performance landing-page summary without touching PDFs."""

from __future__ import annotations

import argparse
import json
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


def write_latest(conn: sqlite3.Connection, site: Path) -> dict:
    latest = latest_since_inception(conn)
    if latest is None:
        raise SystemExit("No since_inception performance path rows found.")

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
    latest_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--site", type=Path, default=ROOT)
    args = parser.parse_args()

    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        payload = write_latest(conn, args.site)
        print(f"updated latest performance through {payload['as_of_date']}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
