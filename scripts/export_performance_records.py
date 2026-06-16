#!/usr/bin/env python3
"""Export performance records from the trading SQLite DB to Hugo."""

from __future__ import annotations

import argparse
import html
import json
import sqlite3
from pathlib import Path


DEFAULT_DB = Path("/home/trader/trading/composite.db")
ROOT = Path(__file__).resolve().parents[1]


def pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.2f}%"


def signed_pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    sign = "+" if value > 0 else ""
    return f"{sign}{value * 100:.2f}%"


def front_matter(data: dict) -> str:
    lines = ["---"]
    for key, value in data.items():
        if isinstance(value, bool):
            lines.append(f"{key}: {'true' if value else 'false'}")
        elif isinstance(value, (dict, list)):
            lines.append(f"{key}: {json.dumps(value)}")
        elif isinstance(value, list):
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {item}")
        else:
            safe = str(value).replace('"', '\\"')
            lines.append(f'{key}: "{safe}"')
    lines.append("---")
    return "\n".join(lines)


def rows(conn: sqlite3.Connection, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
    return list(conn.execute(sql, args))


def row(conn: sqlite3.Connection, sql: str, args: tuple = ()) -> sqlite3.Row | None:
    return conn.execute(sql, args).fetchone()


def score(conn: sqlite3.Connection, period_key: str) -> dict | None:
    path = rows(
        conn,
        """
        SELECT *
        FROM fact_performance_paths_daily
        WHERE period_key=?
        ORDER BY date
        """,
        (period_key,),
    )
    if not path:
        return None
    first, last = path[0], path[-1]
    portfolio = float(last["equity_index"] or 100) / 100 - 1
    benchmark = float(last["spx_tr_index_cad"] or 100) / 100 - 1
    return {
        "period_key": period_key,
        "display_name": first["display_name"],
        "period_type": first["period_type"],
        "first_date": first["date"],
        "last_date": last["date"],
        "portfolio": portfolio,
        "benchmark": benchmark,
        "excess": portfolio - benchmark,
        "path": path,
    }


def monthly_period_keys(conn: sqlite3.Connection) -> list[str]:
    found = rows(
        conn,
        """
        SELECT period_key
        FROM fact_performance_paths_daily
        WHERE period_type='month'
        GROUP BY period_key
        ORDER BY MIN(date)
        """,
    )
    if not found:
        raise SystemExit("No monthly performance period found.")
    return [str(r["period_key"]) for r in found]


def risk_breaches(conn: sqlite3.Connection, period_key: str) -> int | None:
    info = rows(conn, "PRAGMA table_info(v_report_risk_daily)")
    breach_cols = [r["name"] for r in info if str(r["name"]).startswith("breach_")]
    if not breach_cols:
        return None
    expr = " + ".join(f"COALESCE({c},0)" for c in breach_cols)
    found = row(conn, f"SELECT SUM({expr}) AS breaches FROM v_report_risk_daily WHERE period_key=?", (period_key,))
    return None if found is None or found["breaches"] is None else int(found["breaches"])


def decimal(value: float | None, places: int = 3) -> str:
    if value is None:
        return "n/a"
    return f"{value:.{places}f}"


def compact_decimal(value: float | None) -> str:
    if value is None:
        return "n/a"
    if float(value).is_integer():
        return f"{int(value):,}"
    return f"{float(value):,.6f}".rstrip("0").rstrip(".")


def risk_limit_map(conn: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    try:
        return {r["metric_key"]: r for r in rows(conn, "SELECT * FROM v_limits_risk")}
    except sqlite3.Error:
        return {}


def report_limit_label(key: str, limits: dict[str, sqlite3.Row]) -> str:
    limit = limits.get(key)
    if limit is None:
        return "n/a"
    op = limit["good_operator"]
    lo = limit["good_min"]
    hi = limit["good_max"]
    if op == "between":
        return f"{compact_decimal(lo)} to {compact_decimal(hi)}"
    if op == "lt":
        return f"< {compact_decimal(hi)}"
    if op == "gte":
        return f">= {compact_decimal(lo)}"
    if op == "eq_contango":
        return "contango"
    return str(limit["breach_logic"] or "n/a")


def risk_rows(conn: sqlite3.Connection, period_key: str) -> list[dict]:
    metric_defs = [
        ("asset_delta", "Asset Delta / AUM", "breach_delta"),
        ("asset_gamma", "Asset Gamma / AUM", "breach_gamma"),
        ("net_vega", "P&L per +10 IV / AUM", "breach_vega"),
        ("net_theta", "Annual Theta / AUM", "breach_theta"),
        ("margin_power", "Margin Cushion / AUM", "breach_margin"),
        ("open_contracts", "Contracts", "breach_open_contracts"),
        ("rolling_30d_buy_sell_count", "30d Trade Count", "breach_trade_count"),
        ("vix", "VIX", "breach_vix"),
    ]
    daily = rows(conn, "SELECT * FROM v_report_risk_daily WHERE period_key=?", (period_key,))
    limits = risk_limit_map(conn)
    out = []
    for key, label, breach_key in metric_defs:
        values = sorted(float(r[key]) for r in daily if r[key] is not None)
        if not values:
            continue
        n = len(values)
        median = values[n // 2] if n % 2 else (values[n // 2 - 1] + values[n // 2]) / 2
        breach_days = sum(int(r[breach_key] or 0) for r in daily if breach_key in r.keys() and r[key] is not None)
        out.append({
            "metric": label,
            "avg": decimal(sum(values) / n),
            "median": decimal(median),
            "limit": report_limit_label(key, limits),
            "breach_days": breach_days,
            "total_days": n,
        })
    return out


def risk_months(conn: sqlite3.Connection, period_key: str) -> list[dict]:
    info = rows(conn, "PRAGMA table_info(v_report_risk_daily)")
    breach_cols = [r["name"] for r in info if str(r["name"]).startswith("breach_")]
    if not breach_cols:
        return []
    expr = " + ".join(f"COALESCE({c},0)" for c in breach_cols)
    found = rows(
        conn,
        f"""
        SELECT SUBSTR(date,1,7) AS month, SUM({expr}) AS breaches
        FROM v_report_risk_daily
        WHERE period_key=?
        GROUP BY SUBSTR(date,1,7)
        ORDER BY month
        """,
        (period_key,),
    )
    return [{"month": r["month"], "breaches": int(r["breaches"] or 0)} for r in found]


def drawdown(conn: sqlite3.Connection, end_date: str | None = None) -> tuple[float | None, float | None]:
    date_filter = "AND date <= ?" if end_date else ""
    args = (end_date, end_date) if end_date else ()
    found = row(
        conn,
        f"""
        SELECT
          (SELECT drawdown FROM fact_performance_paths_daily WHERE period_key='since_inception' {date_filter} ORDER BY date DESC LIMIT 1) AS current_dd,
          MIN(drawdown) AS max_dd
        FROM fact_performance_paths_daily
        WHERE period_key='since_inception'
          {date_filter}
        """,
        args,
    )
    if found is None:
        return None, None
    return found["current_dd"], found["max_dd"]


def benchmark_drawdown(conn: sqlite3.Connection, end_date: str | None = None) -> tuple[float | None, float | None]:
    date_filter = "AND date <= ?" if end_date else ""
    args = (end_date, end_date) if end_date else ()
    found = row(
        conn,
        f"""
        SELECT
          (SELECT spx_tr_drawdown_cad FROM fact_performance_paths_daily WHERE period_key='since_inception' {date_filter} ORDER BY date DESC LIMIT 1) AS current_dd,
          MIN(spx_tr_drawdown_cad) AS max_dd
        FROM fact_performance_paths_daily
        WHERE period_key='since_inception'
          {date_filter}
        """,
        args,
    )
    if found is None:
        return None, None
    return found["current_dd"], found["max_dd"]


def public_drivers(conn: sqlite3.Connection, period_key: str) -> list[dict]:
    info = rows(conn, "PRAGMA table_info(v_report_attribution_period_usd)")
    if info:
        found = rows(
            conn,
            """
            SELECT label, pct_start_nav AS value
            FROM v_report_attribution_period_usd
            WHERE period_key=?
            ORDER BY display_order
            """,
            (period_key,),
        )
        return [
            {"label": r["label"], "value": float(r["value"] or 0)}
            for r in found
            if abs(float(r["value"] or 0)) >= 0.00005 or r["label"] == "Residual"
        ]

    found = row(
        conn,
        """
        SELECT *
        FROM v_report_nav_bridge_period
        WHERE period_key=? AND scope='TOTAL'
        """,
        (period_key,),
    )
    if found is None or not found["start_nav_cad"]:
        return []
    start_nav = float(found["start_nav_cad"])
    raw = [
        ("Options P&L", found["option_pnl_cad"]),
        ("Stock/ETF P&L", found["stock_etf_pnl_cad"]),
        ("Dividends", found["dividends_cad"]),
        ("Interest Income", found["interest_income_cad"]),
        ("Commissions", -float(found["commissions_cad"] or 0)),
        ("Margin Interest", -float(found["margin_interest_cad"] or 0)),
        ("Fees", -float(found["fees_cad"] or 0)),
        ("FX Conversion Drag", -float(found["fx_conversion_drag_cad"] or 0)),
        ("Residual / Open Marks", found["bridge_balance_cad"]),
    ]
    out = []
    for label, cad_value in raw:
        value = float(cad_value or 0) / start_nav
        if abs(value) >= 0.00005:
            out.append({"label": label, "value": value})
    return out


def path_points(path: list[sqlite3.Row]) -> list[dict]:
    if not path:
        return []
    return [
        {
            "date": str(r["date"]),
            "portfolio": round(float(r["equity_index"] or 100), 4),
            "benchmark": round(float(r["spx_tr_index_cad"] or 100), 4),
        }
        for r in path
    ]


def report_period_payload(conn: sqlite3.Connection, key: str, label: str) -> dict | None:
    period = score(conn, key)
    if period is None:
        return None
    drivers = public_drivers(conn, key)
    risks = risk_rows(conn, key)
    total_days = sorted({int(r["total_days"]) for r in risks if r.get("total_days") is not None})
    payload = {
        "key": label.lower().replace(" ", "_").replace(".", ""),
        "period_key": key,
        "label": label,
        "start_date": period["first_date"],
        "end_date": period["last_date"],
        "portfolio": pct(period["portfolio"]),
        "benchmark": pct(period["benchmark"]),
        "excess": signed_pct(period["excess"]),
        "path": path_points(period["path"]),
        "drivers": [
            {"label": d["label"], "value": round(float(d["value"]), 6), "display": signed_pct(d["value"])}
            for d in drivers
        ],
        "risk_rows": risks,
        "risk_months": risk_months(conn, key),
        "risk_total_days": total_days[0] if len(total_days) == 1 else None,
    }
    if label == "Since Inception":
        current_dd, max_dd = drawdown(conn, period["last_date"])
        benchmark_current_dd, benchmark_max_dd = benchmark_drawdown(conn, period["last_date"])
        payload["drawdowns"] = [
            {"series": "Portfolio", "current": pct(current_dd), "max": pct(max_dd)},
            {"series": "S&P 500 TR", "current": pct(benchmark_current_dd), "max": pct(benchmark_max_dd)},
        ]
    return payload


def report_periods(conn: sqlite3.Connection, month_key: str) -> list[dict]:
    requested = [
        (month_key, "1M"),
        ("trailing_3m", "3M"),
        ("trailing_12m", "12M"),
        ("since_inception", "Since Inception"),
    ]
    out = []
    for key, label in requested:
        payload = report_period_payload(conn, key, label)
        if payload is not None:
            out.append(payload)
    return out


def svg_path_chart(path: list[sqlite3.Row], out: Path) -> None:
    width, height = 720, 420
    left, right, top, bottom = 64, 660, 70, 330
    first_equity = float(path[0]["equity_index"] or 100) if path else 100
    first_benchmark = float(path[0]["spx_tr_index_cad"] or 100) if path else 100
    vals = []
    for r in path:
        vals.append(float(r["equity_index"] or first_equity) / first_equity * 100)
        vals.append(float(r["spx_tr_index_cad"] or first_benchmark) / first_benchmark * 100)
    lo, hi = min(vals + [100]), max(vals + [100])
    if hi == lo:
        hi, lo = hi + 1, lo - 1

    def points(col: str) -> str:
        n = max(len(path) - 1, 1)
        base = first_equity if col == "equity_index" else first_benchmark
        pts = []
        for i, r in enumerate(path):
            v = float(r[col] or base) / base * 100
            x = left + (right - left) * i / n
            y = bottom - (v - lo) / (hi - lo) * (bottom - top)
            pts.append(f"{x:.1f},{y:.1f}")
        return " ".join(pts)

    start_date = path[0]["date"] if path else "n/a"
    end_date = path[-1]["date"] if path else "n/a"
    mid_date = path[len(path) // 2]["date"] if path else "n/a"
    baseline_y = bottom - (100 - lo) / (hi - lo) * (bottom - top)

    out.write_text(
        f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img">
  <rect width="{width}" height="{height}" fill="#fbfaf6"/>
  <g stroke="#d7d0c4" stroke-width="1">
    <line x1="{left}" y1="{bottom}" x2="{right}" y2="{bottom}"/>
    <line x1="{left}" y1="{top}" x2="{right}" y2="{top}"/>
    <line x1="{left}" y1="{baseline_y:.1f}" x2="{right}" y2="{baseline_y:.1f}"/>
  </g>
  <text x="64" y="38" font-family="Inter, Arial, sans-serif" font-size="18" font-weight="700" fill="#141719">Performance Path: {start_date} to {end_date}</text>
  <text x="54" y="{baseline_y + 4:.1f}" text-anchor="end" font-family="Inter, Arial, sans-serif" font-size="12" fill="#5f676b">100</text>
  <polyline points="{points("equity_index")}" fill="none" stroke="#315f5b" stroke-width="4"/>
  <polyline points="{points("spx_tr_index_cad")}" fill="none" stroke="#8b5f2b" stroke-width="4"/>
  <text x="{left}" y="358" font-family="Inter, Arial, sans-serif" font-size="12" fill="#5f676b">{start_date}</text>
  <text x="{(left + right) / 2:.1f}" y="358" text-anchor="middle" font-family="Inter, Arial, sans-serif" font-size="12" fill="#5f676b">{mid_date}</text>
  <text x="{right}" y="358" text-anchor="end" font-family="Inter, Arial, sans-serif" font-size="12" fill="#5f676b">{end_date}</text>
  <text x="64" y="392" font-family="Inter, Arial, sans-serif" font-size="13" fill="#315f5b">Portfolio</text>
  <text x="160" y="392" font-family="Inter, Arial, sans-serif" font-size="13" fill="#8b5f2b">S&amp;P 500 TR CAD</text>
</svg>
""",
        encoding="utf-8",
    )


def svg_driver_chart(drivers: list[dict], out: Path) -> None:
    width, height = 720, 420
    max_abs = max([abs(d["value"]) for d in drivers] + [0.01])
    bars = []
    for i, d in enumerate(drivers[:8]):
        y = 92 + i * 36
        w = abs(d["value"]) / max_abs * 230
        color = "#315f5b" if d["value"] >= 0 else "#8a2f2f"
        x = 330 if d["value"] >= 0 else 330 - w
        bars.append(
            f'<text x="64" y="{y + 19}" font-family="Inter, Arial, sans-serif" font-size="13" fill="#141719">{html.escape(d["label"])}</text>'
            f'<rect x="{x:.1f}" y="{y}" width="{w:.1f}" height="24" fill="{color}"/>'
            f'<text x="584" y="{y + 18}" text-anchor="end" font-family="Inter, Arial, sans-serif" font-size="13" fill="#141719">{signed_pct(d["value"])}</text>'
        )
    out.write_text(
        f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img">
  <rect width="{width}" height="{height}" fill="#fbfaf6"/>
  <text x="64" y="38" font-family="Inter, Arial, sans-serif" font-size="18" font-weight="700" fill="#141719">Return Drivers</text>
  <text x="64" y="62" font-family="Inter, Arial, sans-serif" font-size="12" fill="#5f676b">Percent of beginning NAV</text>
  <line x1="330" y1="82" x2="330" y2="370" stroke="#d7d0c4" stroke-width="1"/>
  {''.join(bars)}
</svg>
""",
        encoding="utf-8",
    )


def write_record(conn: sqlite3.Connection, period_key: str, root: Path) -> dict:
    month = score(conn, period_key)
    if month is None:
        raise SystemExit(f"No data for {period_key}")
    suffix = period_key.replace("month_", "").replace("_", "-")
    period_scores = {
        "1m": month,
        "3m": score(conn, "trailing_3m"),
        "12m": score(conn, "trailing_12m"),
        "since": score(conn, "since_inception"),
    }
    current_dd, max_dd = drawdown(conn)
    breaches = risk_breaches(conn, period_key)
    drivers = public_drivers(conn, period_key)
    risks = risk_rows(conn, period_key)
    periods = report_periods(conn, period_key)

    image_dir = root / "static" / "images" / "performance"
    image_dir.mkdir(parents=True, exist_ok=True)
    path_chart = f"/images/performance/{suffix}-path.svg"
    driver_chart = f"/images/performance/{suffix}-drivers.svg"
    svg_path_chart(month["path"], image_dir / f"{suffix}-path.svg")
    svg_driver_chart(drivers, image_dir / f"{suffix}-drivers.svg")

    title = f"{month['display_name']} Performance Record"
    front = {
        "title": title,
        "date": f"{month['last_date']}T08:00:00-07:00",
        "draft": False,
        "month_covered": month["display_name"],
        "portfolio_1m": pct(period_scores["1m"]["portfolio"]),
        "benchmark_1m": pct(period_scores["1m"]["benchmark"]),
        "excess_1m": signed_pct(period_scores["1m"]["excess"]),
        "portfolio_3m": pct(period_scores["3m"]["portfolio"] if period_scores["3m"] else None),
        "benchmark_3m": pct(period_scores["3m"]["benchmark"] if period_scores["3m"] else None),
        "excess_3m": signed_pct(period_scores["3m"]["excess"] if period_scores["3m"] else None),
        "portfolio_12m": pct(period_scores["12m"]["portfolio"] if period_scores["12m"] else None),
        "benchmark_12m": pct(period_scores["12m"]["benchmark"] if period_scores["12m"] else None),
        "excess_12m": signed_pct(period_scores["12m"]["excess"] if period_scores["12m"] else None),
        "portfolio_since_inception": pct(period_scores["since"]["portfolio"] if period_scores["since"] else None),
        "benchmark_since_inception": pct(period_scores["since"]["benchmark"] if period_scores["since"] else None),
        "excess_since_inception": signed_pct(period_scores["since"]["excess"] if period_scores["since"] else None),
        "current_drawdown": pct(current_dd),
        "max_drawdown": pct(max_dd),
        "risk_breach_days": "n/a" if breaches is None else str(breaches),
        "path_chart": path_chart,
        "driver_chart": driver_chart,
        "report_periods": periods,
        "tags": ["performance"],
        "summary": f"Public performance record for {month['display_name']}.",
    }
    driver_lines = "\n".join(
        f'| {d["label"]} | {signed_pct(d["value"])} |' for d in drivers
    ) or "| n/a | n/a |"
    risk_lines = "\n".join(
        f'| {r["metric"]} | {r["avg"]} | {r["median"]} | {r["limit"]} | {r["breach_days"]} |' for r in risks
    ) or "| n/a | n/a | n/a | n/a | n/a |"

    body = f"""{front_matter(front)}

## Record

| Measure | Portfolio | Benchmark | Difference |
| --- | ---: | ---: | ---: |
| 1M | {front["portfolio_1m"]} | {front["benchmark_1m"]} | {front["excess_1m"]} |
| 3M | {front["portfolio_3m"]} | {front["benchmark_3m"]} | {front["excess_3m"]} |
| 12M | {front["portfolio_12m"]} | {front["benchmark_12m"]} | {front["excess_12m"]} |
| Since inception | {front["portfolio_since_inception"]} | {front["benchmark_since_inception"]} | {front["excess_since_inception"]} |

## Attribution

Percent of beginning NAV.

| Line | Contribution |
| --- | ---: |
{driver_lines}

## Risk
Risk table is shown in the report template.

## Risk Metrics

| Metric | Average Daily Value | Median Daily Value | Breach Limit | Breach Days |
| --- | ---: | ---: | --- | ---: |
{risk_lines}

"""
    post_path = root / "content" / "performance" / f"{suffix}.md"
    post_path.write_text(body, encoding="utf-8")
    return front


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--site", type=Path, default=ROOT)
    parser.add_argument("--period-key")
    args = parser.parse_args()

    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        period_keys = [args.period_key] if args.period_key else monthly_period_keys(conn)
        records = [write_record(conn, period_key, args.site) for period_key in period_keys]
        record = records[-1]
        data_path = args.site / "data" / "latest_performance.json"
        data_path.parent.mkdir(parents=True, exist_ok=True)
        data_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {len(records)} performance record(s)")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
