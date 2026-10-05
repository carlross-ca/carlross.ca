#!/usr/bin/env python3
"""Export frozen monthly performance PDFs from the trading SQLite DB."""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import date
from pathlib import Path

from export_performance_records import (
    DEFAULT_DB,
    ROOT,
    decimal,
    pct,
    metric_breached,
    risk_breaches,
    report_limit_label,
    risk_limit_map,
    RISK_METRICS,
    rows,
    score,
    signed_pct,
)


from report_calculations import usd_performance_between, core_ticker_attribution_between, drivers_between


PAGE_W, PAGE_H = 612, 792
INK = (0.08, 0.09, 0.10)
MUTED = (0.37, 0.40, 0.42)
WHITE = (1.0, 1.0, 1.0)
LINE = (0.84, 0.82, 0.77)
PAPER = (0.98, 0.98, 0.96)
ACCENT = (0.19, 0.37, 0.36)
ACCENT2 = (0.55, 0.37, 0.17)
BAD = (0.54, 0.18, 0.18)
GOOD = (0.20, 0.48, 0.30)
PORTFOLIO_RED = (0.71, 0.23, 0.20)
SPX_BLUE = (0.15, 0.43, 0.54)


def esc(value: object) -> str:
    return str(value).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def rgb(color: tuple[float, float, float]) -> str:
    return f"{color[0]:.3f} {color[1]:.3f} {color[2]:.3f}"


class Pdf:
    def __init__(self) -> None:
        self.pages: list[str] = []
        self.buf: list[str] = []

    def page(self) -> None:
        if self.buf:
            self.pages.append("\n".join(self.buf))
        self.buf = []

    def text(self, x: float, y: float, text: object, size: int = 9, color=INK, bold: bool = False) -> None:
        font = "F2" if bold else "F1"
        self.buf.append(f"BT /{font} {size} Tf {rgb(color)} rg {x:.1f} {y:.1f} Td ({esc(text)}) Tj ET")

    def centered_text(self, y: float, text: object, size: int = 9, color=INK, bold: bool = False) -> None:
        width = len(str(text)) * size * 0.25
        self.text(PAGE_W / 2 - width, y, text, size, color, bold)

    def line(self, x1: float, y1: float, x2: float, y2: float, color=LINE, width: float = 0.6) -> None:
        self.buf.append(f"{rgb(color)} RG {width:.2f} w {x1:.1f} {y1:.1f} m {x2:.1f} {y2:.1f} l S")

    def rect(self, x: float, y: float, w: float, h: float, stroke=LINE, fill=None, width: float = 0.6) -> None:
        op = "B" if fill else "S"
        fill_part = f"{rgb(fill)} rg " if fill else ""
        self.buf.append(f"{fill_part}{rgb(stroke)} RG {width:.2f} w {x:.1f} {y:.1f} {w:.1f} {h:.1f} re {op}")

    def polyline(self, pts: list[tuple[float, float]], color=ACCENT, width: float = 1.6) -> None:
        if len(pts) < 2:
            return
        path = f"{rgb(color)} RG {width:.2f} w {pts[0][0]:.1f} {pts[0][1]:.1f} m "
        path += " ".join(f"{x:.1f} {y:.1f} l" for x, y in pts[1:])
        self.buf.append(path + " S")

    def save(self, path: Path) -> None:
        if self.buf:
            self.pages.append("\n".join(self.buf))
            self.buf = []
        objects: list[bytes] = []

        def add(obj: str | bytes) -> int:
            objects.append(obj.encode("latin-1") if isinstance(obj, str) else obj)
            return len(objects)

        font1 = add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
        font2 = add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")
        page_ids = []
        for content in self.pages:
            stream = content.encode("latin-1", "replace")
            content_id = add(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
            page_id = add(
                f"<< /Type /Page /Parent 0 0 R /MediaBox [0 0 {PAGE_W} {PAGE_H}] "
                f"/Resources << /Font << /F1 {font1} 0 R /F2 {font2} 0 R >> >> "
                f"/Contents {content_id} 0 R >>"
            )
            page_ids.append(page_id)
        pages_id = len(objects) + 1
        for pid in page_ids:
            objects[pid - 1] = objects[pid - 1].replace(b"/Parent 0 0 R", f"/Parent {pages_id} 0 R".encode())
        add(f"<< /Type /Pages /Kids [{' '.join(f'{pid} 0 R' for pid in page_ids)}] /Count {len(page_ids)} >>")
        catalog_id = add(f"<< /Type /Catalog /Pages {pages_id} 0 R >>")

        out = bytearray(b"%PDF-1.4\n")
        offsets = [0]
        for i, obj in enumerate(objects, 1):
            offsets.append(len(out))
            out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
        xref = len(out)
        out += f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n".encode()
        out += b"".join(f"{off:010d} 00000 n \n".encode() for off in offsets[1:])
        out += f"trailer << /Size {len(objects)+1} /Root {catalog_id} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(out)


def table(pdf: Pdf, x: float, y: float, widths: list[float], header: list[str], rows: list[list[object]], row_h: float = 18, size: int = 9) -> float:
    pdf.rect(x, y - row_h, sum(widths), row_h, fill=PAPER)
    cx = x
    for w, h in zip(widths, header):
        pdf.text(cx + 5, y - 12, h, size, MUTED, True)
        cx += w
    y -= row_h
    for row in rows:
        pdf.line(x, y, x + sum(widths), y)
        cx = x
        for w, cell in zip(widths, row):
            pdf.text(cx + 5, y - 12, cell, size, INK)
            cx += w
        y -= row_h
    pdf.rect(x, y, sum(widths), row_h * (len(rows) + 1))
    return y


def attribution_table(pdf: Pdf, x: float, y: float, rows: list[dict], row_h: float = 15) -> float:
    widths = [158, 78, 292]
    total_w = sum(widths)
    pdf.rect(x, y - row_h, total_w, row_h, fill=PAPER)
    pdf.text(x + 5, y - 11, "Line", 8, MUTED, True)
    pdf.text(x + widths[0] + 5, y - 11, "% Beg NAV", 8, MUTED, True)
    pdf.text(x + widths[0] + widths[1] + 5, y - 11, "Contribution Scale", 8, MUTED, True)
    y -= row_h
    values = [abs(float(r.get("value") or 0)) for r in rows]
    max_abs = max(values + [0.01])
    bar_x = x + widths[0] + widths[1] + 5
    bar_w = widths[2] - 10
    mid = bar_x + bar_w * 0.5
    for r in rows:
        value = float(r.get("value") or 0)
        pdf.line(x, y, x + total_w, y)
        label = str(r["label"])
        pdf.text(x + 5, y - 13, label, 10, INK)
        pdf.text(x + widths[0] + 5, y - 13, r["display"], 10, INK)
        pdf.line(mid, y - 12, mid, y - 3, LINE)
        scaled = min(abs(value) / max_abs, 1.0) * (bar_w * 0.46)
        fill = GOOD if value >= 0 else BAD
        bx = mid if value >= 0 else mid - scaled
        pdf.rect(bx, y - 11, scaled, 7, stroke=fill, fill=fill)
        y -= row_h
    pdf.rect(x, y, total_w, row_h * (len(rows) + 1))
    return y


def section_title(pdf: Pdf, y: float, title: str, subtitle: str | None = None) -> None:
    pdf.centered_text(y, title, 16, INK, True)
    if subtitle:
        pdf.centered_text(y - 16, subtitle, 10, MUTED)


def path_chart(pdf: Pdf, x: float, y: float, w: float, h: float, period: dict) -> None:
    pts = period.get("path", [])
    pdf.rect(x, y - h, w, h, fill=PAPER)
    if not pts:
        pdf.text(x + 8, y - 34, "No path data", 10, MUTED)
        return
    vals = [float(p["portfolio"]) for p in pts] + [float(p["benchmark"]) for p in pts] + [100.0]
    lo, hi = min(vals), max(vals)
    pad = max((hi - lo) * 0.15, 1)
    lo, hi = lo - pad, hi + pad
    left, right, top, bottom = x + 38, x + w - 12, y - 18, y - h + 28

    def xy(i: int, value: float) -> tuple[float, float]:
        px = left + (right - left) * (i / max(len(pts) - 1, 1))
        py = bottom + (value - lo) / (hi - lo) * (top - bottom)
        return px, py

    for value in sorted([lo, 100.0, hi]):
        _, py = xy(0, value)
        pdf.line(left, py, right, py)
        pdf.text(x + 8, py - 4, f"{value - 100:.1f}%", 8, MUTED)
    pdf.polyline([xy(i, float(p["benchmark"])) for i, p in enumerate(pts)], SPX_BLUE)
    pdf.polyline([xy(i, float(p["portfolio"])) for i, p in enumerate(pts)], PORTFOLIO_RED)
    pdf.text(left, y - h + 12, pts[0]["date"], 8, MUTED)
    pdf.text((left + right) / 2 - 24, y - h + 12, pts[len(pts) // 2]["date"], 8, MUTED)
    pdf.text(right - 56, y - h + 12, pts[-1]["date"], 8, MUTED)
    pdf.text(left, y - 12, "Portfolio", 9, PORTFOLIO_RED, True)
    pdf.text(left + 64, y - 12, "S&P 500 TR", 9, SPX_BLUE, True)


def usd_performance(conn: sqlite3.Connection, period_key: str) -> dict | None:
    found = conn.execute(
        """
        SELECT portfolio_return_usd, spx_tr_return_usd, excess_return_usd
        FROM v_report_performance_usd
        WHERE period_key=?
        """,
        (period_key,),
    ).fetchone()
    if found is None:
        return None
    return {
        "portfolio": float(found["portfolio_return_usd"] or 0),
        "benchmark": float(found["spx_tr_return_usd"] or 0),
        "excess": float(found["excess_return_usd"] or 0),
    }


def core_ticker_attribution(conn: sqlite3.Connection, period_key: str) -> list[dict]:
    p = conn.execute("SELECT * FROM v_report_performance_usd WHERE period_key=?", (period_key,)).fetchone()
    return [] if p is None else core_ticker_attribution_between(conn, p["first_date"], p["last_date"], p["nav_start_usd"])


def driver_chart(pdf: Pdf, x: float, y: float, w: float, h: float, drivers: list[dict]) -> None:
    pdf.rect(x, y - h, w, h, fill=PAPER)
    if not drivers:
        pdf.text(x + 8, y - 34, "No driver data", 10, MUTED)
        return
    max_abs = max(abs(float(d["value"])) for d in drivers) or 0.01
    mid = x + w * 0.54
    pdf.line(mid, y - 16, mid, y - h + 12)
    row_h = min(17, (h - 38) / max(len(drivers), 1))
    for i, d in enumerate(drivers[:9]):
        by = y - 26 - i * row_h
        v = float(d["value"])
        bw = abs(v) / max_abs * (w * 0.34)
        bx = mid - bw if v < 0 else mid
        pdf.text(x + 8, by + 1, d["label"], 8, INK)
        pdf.rect(bx, by, bw, 8, stroke=ACCENT if v >= 0 else BAD, fill=ACCENT if v >= 0 else BAD)


def risk_chart(pdf: Pdf, x: float, y: float, w: float, h: float, months: list[dict]) -> None:
    pdf.rect(x, y - h, w, h, fill=PAPER)
    if not months:
        pdf.text(x + 8, y - 34, "No risk data", 10, MUTED)
        return
    max_v = max(int(m["breaches"]) for m in months) or 1
    left, right, bottom, top = x + 28, x + w - 14, y - h + 28, y - 18
    bw = (right - left) / max(len(months), 1) * 0.55
    pdf.line(left, bottom, right, bottom)
    for i, m in enumerate(months):
        cx = left + (right - left) * (i + 0.5) / len(months)
        bh = int(m["breaches"]) / max_v * (top - bottom)
        pdf.rect(cx - bw / 2, bottom, bw, bh, stroke=ACCENT, fill=ACCENT)
        label_y = bottom + max(6, bh - 14)
        pdf.text(cx - 5, label_y, m["breaches"], 10, WHITE, True)
        pdf.text(cx - 18, y - h + 12, m["month"], 8, MUTED)


def prior_chart_date(conn: sqlite3.Connection, start_date: str) -> str:
    found = conn.execute(
        """
        SELECT MAX(date) AS date
        FROM v_core_nav_daily
        WHERE date < ?
        """,
        (start_date,),
    ).fetchone()
    return str(found["date"]) if found and found["date"] else start_date


def score_from_path(conn: sqlite3.Connection, period_key: str, label: str, path: list[sqlite3.Row]) -> dict | None:
    if not path:
        return None
    last = path[-1]
    baseline = conn.execute(
        """
        SELECT date, equity_index, spx_tr_index_cad
        FROM fact_performance_paths_daily
        WHERE period_key='since_inception' AND date < ?
        ORDER BY date DESC
        LIMIT 1
        """,
        (path[0]["date"],),
    ).fetchone()
    baseline_date = str(baseline["date"]) if baseline else prior_chart_date(conn, str(path[0]["date"]))
    portfolio_base = float(baseline["equity_index"] or 100) if baseline else 100.0
    benchmark_base = float(baseline["spx_tr_index_cad"] or 100) if baseline else 100.0
    portfolio = float(last["equity_index"] or portfolio_base) / portfolio_base - 1
    benchmark = float(last["spx_tr_index_cad"] or benchmark_base) / benchmark_base - 1
    rebased_path = [
        {
            "date": str(r["date"]),
            "portfolio": round(float(r["equity_index"] or portfolio_base) / portfolio_base * 100, 4),
            "benchmark": round(float(r["spx_tr_index_cad"] or benchmark_base) / benchmark_base * 100, 4),
        }
        for r in path
    ]
    return {
        "period_key": period_key,
        "label": label,
        "start_date": path[0]["date"],
        "end_date": last["date"],
        "portfolio": pct(portfolio),
        "benchmark": pct(benchmark),
        "excess": signed_pct(portfolio - benchmark),
        "portfolio_value": portfolio,
        "benchmark_value": benchmark,
        "path": [{"date": baseline_date, "portfolio": 100.0, "benchmark": 100.0}] + rebased_path,
    }











def calendar_lookback_start(end_date: str, months: int) -> str:
    end = date.fromisoformat(end_date)
    month_index = end.year * 12 + end.month - months
    return date(month_index // 12, month_index % 12 + 1, 1).isoformat()


def completed_monthly_period_keys(conn: sqlite3.Connection) -> list[str]:
    return [
        str(r["period_key"])
        for r in rows(
            conn,
            """
            SELECT p.period_key
            FROM fact_performance_paths_daily p
            CROSS JOIN v_core_data_freshness f
            WHERE p.period_type='month'
            GROUP BY p.period_key
            HAVING f.latest_account_snapshot_date >= date(MAX(p.period_end_exclusive), '-1 day')
            ORDER BY MIN(p.date)
            """,
        )
    ]


def asof_path(conn: sqlite3.Connection, end_date: str, start_date: str | None = None) -> list[sqlite3.Row]:
    start_sql = "" if start_date is None else "AND date >= ?"
    args: tuple = (end_date,) if start_date is None else (end_date, start_date)
    found = rows(
        conn,
        f"""
        SELECT *
        FROM fact_performance_paths_daily
        WHERE period_key='since_inception'
          AND date <= ?
          {start_sql}
        ORDER BY date
        """,
        args,
    )
    return found


def asof_payload(conn: sqlite3.Connection, label: str, path: list[sqlite3.Row]) -> dict | None:
    payload = score_from_path(conn, label.lower().replace(" ", "_"), label, path)
    if payload is None:
        return None
    usd = usd_performance_between(conn, payload["start_date"], payload["end_date"])
    if usd:
        payload["usd_portfolio"] = pct(usd["portfolio"])
        payload["usd_benchmark"] = pct(usd["benchmark"])
        payload["usd_excess"] = signed_pct(usd["excess"])
        cad_portfolio = float(payload["portfolio_value"])
        cad_benchmark = float(payload["benchmark_value"])
        payload["portfolio_fx"] = signed_pct(cad_portfolio - usd["portfolio"])
        payload["benchmark_fx"] = signed_pct(cad_benchmark - usd["benchmark"])
        payload["drivers"] = drivers_between(conn, payload["start_date"], payload["end_date"], usd)
    else:
        payload["drivers"] = []
    payload["risk_rows"] = risk_rows_between(conn, payload["start_date"], payload["end_date"])
    payload["risk_months"] = risk_months_between(conn, payload["start_date"], payload["end_date"])
    days = sorted({int(r["total_days"]) for r in payload["risk_rows"] if r.get("total_days") is not None})
    payload["risk_total_days"] = days[0] if len(days) == 1 else None
    payload["drawdowns"] = []
    for key, name in [("portfolio", "Portfolio"), ("benchmark", "S&P 500 TR")]:
        peak = 100.0
        dds = []
        for point in payload["path"]:
            peak = max(peak, point[key])
            dds.append(point[key] / peak - 1)
        payload["drawdowns"].append([name, pct(dds[-1]), pct(min(dds))])
    cost = conn.execute("SELECT SUM(execution_fees_usd), SUM(margin_interest_usd), SUM(activity_fees_usd), SUM(hidden_fx_usd) FROM v_report_costs_daily_usd WHERE date BETWEEN ? AND ?", (payload["start_date"], payload["end_date"])).fetchone()
    payload["costs"] = [float(v or 0) / usd["nav_start_usd"] if usd and usd["nav_start_usd"] else 0 for v in cost]
    return payload


def risk_daily_between(conn: sqlite3.Connection, start_date: str, end_date: str) -> list[sqlite3.Row]:
    return rows(
        conn,
        """
        SELECT *
        FROM v_report_risk_daily
        WHERE period_key='since_inception'
          AND date BETWEEN ? AND ?
        ORDER BY date
        """,
        (start_date, end_date),
    )


def risk_rows_between(conn: sqlite3.Connection, start_date: str, end_date: str) -> list[dict]:
    daily = risk_daily_between(conn, start_date, end_date)
    limits = risk_limit_map(conn)
    out = []
    for key, label in RISK_METRICS:
        values = sorted(float(r[key]) for r in daily if r[key] is not None)
        if not values:
            continue
        n = len(values)
        median = values[n // 2] if n % 2 else (values[n // 2 - 1] + values[n // 2]) / 2
        limit = limits.get(key)
        breach_days = sum(1 for r in daily if r[key] is not None and metric_breached(r[key], limit))
        out.append({
            "metric": label,
            "avg": decimal(sum(values) / n),
            "median": decimal(median),
            "limit": report_limit_label(key, limits),
            "breach_days": breach_days,
            "total_days": n,
        })
    return out


def risk_months_between(conn: sqlite3.Connection, start_date: str, end_date: str) -> list[dict]:
    daily = rows(
        conn,
        """
        SELECT *
        FROM v_report_risk_daily
        WHERE period_key='since_inception'
          AND date BETWEEN ? AND ?
        ORDER BY date
        """,
        (start_date, end_date),
    )
    limits = risk_limit_map(conn)
    by_month: dict[str, int] = {}
    for r in daily:
        month = str(r["date"])[:7]
        by_month.setdefault(month, 0)
        by_month[month] += sum(
            1 for key, _label in RISK_METRICS
            if key in r.keys() and r[key] is not None and metric_breached(r[key], limits.get(key))
        )
    return [{"month": month, "breaches": breaches} for month, breaches in sorted(by_month.items())]


def pdf_report_periods(conn: sqlite3.Connection, month_key: str) -> list[dict]:
    month = score(conn, month_key)
    if month is None:
        return []
    end_date = month["last_date"]
    requested = [
        asof_payload(conn, "Trailing 1 Month", asof_path(conn, end_date, month["first_date"])),
        asof_payload(conn, "Trailing 3 Months", asof_path(conn, end_date, calendar_lookback_start(end_date, 3))),
        asof_payload(conn, "Trailing 12 Months", asof_path(conn, end_date, calendar_lookback_start(end_date, 12))),
        asof_payload(conn, "Since Inception", asof_path(conn, end_date)),
    ]
    for i, p in enumerate(requested):
        if p is not None:
            expected = month["first_date"] if i == 0 else calendar_lookback_start(end_date, (3 if i == 1 else 12)) if i < 3 else p["start_date"]
            inception = conn.execute("SELECT MIN(date) FROM fact_performance_paths_daily WHERE period_key='since_inception'").fetchone()[0]
            p["full_window"] = expected >= inception
    return [p for p in requested if p is not None]


def write_pdf(path: Path, title: str, periods: list[dict]) -> None:
    """Two readable pages per window: performance, then risk and methodology."""
    pdf = Pdf()
    total_pages = len(periods) * 2
    def header(p, subtitle, page):
        pdf.page()
        pdf.rect(0, 0, PAGE_W, PAGE_H, stroke=PAPER, fill=PAPER)
        pdf.text(42, 752, "CARL ROSS / PERFORMANCE RECORD", 10, ACCENT, True)
        pdf.text(42, 718, p["label"], 25, INK, True)
        if not p.get("full_window", True):
            pdf.text(42, 666, "PARTIAL WINDOW / available history only", 10, ACCENT, True)
        pdf.text(42, 695, f"{p['start_date']} to {p['end_date']}  |  {subtitle}", 11, MUTED)
        pdf.line(42, 680, 570, 680)
        pdf.text(42, 28, title, 9, MUTED)
        pdf.text(511, 28, f"{page} / {total_pages}", 9, MUTED)
    for i, p in enumerate(periods):
        header(p, "Pre-tax / daily closing values", i*2+1)
        pdf.text(42, 651, "Return summary", 17, INK, True)
        table(pdf, 42, 630, [168,120,120,120], ["Measure","Portfolio","S&P 500 TR","Difference"], [
            ["USD investment TWR",p.get("usd_portfolio","n/a"),p.get("usd_benchmark","n/a"),p.get("usd_excess","n/a")],
            ["CAD reporting TWR",p["portfolio"],p["benchmark"],p["excess"]]], 28, 11)
        pdf.text(42, 523, "CAD includes currency translation. Difference is in percentage points.", 10, MUTED)
        pdf.text(42, 490, "Performance path", 17, INK, True)
        pdf.text(42, 472, "CAD / change from opening value", 10, MUTED)
        path_chart(pdf, 42, 453, 528, 177, p)
        pdf.text(42, 248, "USD attribution", 17, INK, True)
        pdf.text(42, 230, "P&L / beginning NAV. Sums to simple return, not TWR.", 10, MUTED)
        attribution_table(pdf, 42, 212, p.get("drivers", []), 21)
        header(p, "Risk, costs and calculation basis", i*2+2)
        pdf.text(42, 650, "Risk discipline", 17, INK, True)
        pdf.text(42, 630, "Custom operating limits / breaches per observed day", 10, MUTED)
        table(pdf,42,613,[170,60,60,160,78],["Metric","Avg","Median","Limit","Days"],
              [[r["metric"],r["avg"],r["median"],r["limit"],f"{r['breach_days']} / {r['total_days']}"] for r in p.get("risk_rows",[])],23,10)
        pdf.text(42, 378, "Period drawdown", 17, INK, True)
        table(pdf,42,359,[240,144,144],["CAD series","End","Maximum"],p.get("drawdowns",[]),24,11)
        pdf.text(42, 260, "Costs / % beginning USD NAV", 17, INK, True)
        labels=["Trading fees","Interest, net","Fees / rebates","Estimated FX spread"]
        for j,(label,value) in enumerate(zip(labels,p.get("costs",[]))):
            x=42+(j%2)*264; y=236-(j//2)*42
            pdf.text(x,y,label,10,MUTED)
            pdf.text(x,y-18,f"{value:.3%}",13,INK,True)
        notes=[
            "Returns compound daily after external flows. Costs are already included in returns.",
            "Core SPY/RSP combines both ETFs. Satellite / other is the balancing P&L after core",
            "and costs, including unclassified effects; it is not independently measured trade P&L.",
            "FX spread is estimated against the daily rate and can include intraday rate movement.",
            "Drawdowns use this window's peak, including opening value. Missing risk days are excluded.",
            "Windows are limited to available history; coverage dates above are authoritative.",
        ]
        for j,note in enumerate(notes): pdf.text(42,143-j*14,note,10,MUTED)
    pdf.save(path)


def period_key_for_previous_month(today: date) -> str:
    year = today.year
    month = today.month - 1
    if month == 0:
        year -= 1
        month = 12
    return f"{date(year, month, 1).strftime('%b').lower()}_{year}"


INCEPTION_DATE = "2026-05-01"


def drawdown_asof(conn: sqlite3.Connection, start_date: str, end_date: str) -> tuple[float | None, float | None]:
    found = conn.execute(
        """
        SELECT
          (SELECT drawdown
           FROM fact_performance_paths_daily
           WHERE period_key='since_inception' AND date BETWEEN ? AND ?
           ORDER BY date DESC
           LIMIT 1) AS current_dd,
          MIN(drawdown) AS max_dd
        FROM fact_performance_paths_daily
        WHERE period_key='since_inception'
          AND date BETWEEN ? AND ?
        """,
        (start_date, end_date, start_date, end_date),
    ).fetchone()
    if found is None:
        return None, None
    return found["current_dd"], found["max_dd"]


def benchmark_drawdown_asof(conn: sqlite3.Connection, start_date: str, end_date: str) -> tuple[float | None, float | None]:
    found = conn.execute(
        """
        SELECT
          (SELECT spx_tr_drawdown_cad
           FROM fact_performance_paths_daily
           WHERE period_key='since_inception' AND date BETWEEN ? AND ?
           ORDER BY date DESC
           LIMIT 1) AS current_dd,
          MIN(spx_tr_drawdown_cad) AS max_dd
        FROM fact_performance_paths_daily
        WHERE period_key='since_inception'
          AND date BETWEEN ? AND ?
        """,
        (start_date, end_date, start_date, end_date),
    ).fetchone()
    if found is None:
        return None, None
    return found["current_dd"], found["max_dd"]


def write_one(conn: sqlite3.Connection, root: Path, period_key: str) -> dict:
    month = score(conn, period_key)
    if month is None:
        raise SystemExit(f"No data for {period_key}")
    periods = pdf_report_periods(conn, period_key)
    suffix = period_key.replace("month_", "").replace("_", "-")
    pdf_url = f"/reports/performance/{suffix}-performance-record.pdf"
    pdf_path = root / "static" / pdf_url.lstrip("/")
    title = f"{month['display_name']} Performance Record"
    write_pdf(pdf_path, title, periods)
    current_dd, max_dd = drawdown_asof(conn, INCEPTION_DATE, month["last_date"])
    benchmark_current_dd, benchmark_max_dd = benchmark_drawdown_asof(conn, INCEPTION_DATE, month["last_date"])
    front = {
        "title": title,
        "date": f"{month['last_date']}T08:00:00-07:00",
        "as_of_date": month["last_date"],
        "inception_date": INCEPTION_DATE,
        "draft": False,
        "month_covered": month["display_name"],
        "portfolio_1m": periods[0]["portfolio"] if periods else pct(month["portfolio"]),
        "benchmark_1m": periods[0]["benchmark"] if periods else pct(month["benchmark"]),
        "excess_1m": periods[0]["excess"] if periods else "n/a",
        "portfolio_3m": next((p["portfolio"] for p in periods if p["label"] == "Trailing 3 Months" and p.get("full_window", True)), "n/a"),
        "portfolio_12m": next((p["portfolio"] for p in periods if p["label"] == "Trailing 12 Months" and p.get("full_window", True)), "n/a"),
        "portfolio_since_inception": next((p["portfolio"] for p in periods if p["label"] == "Since Inception"), "n/a"),
        "benchmark_since_inception": next((p["benchmark"] for p in periods if p["label"] == "Since Inception"), "n/a"),
        "current_drawdown": pct(current_dd),
        "max_drawdown": pct(max_dd),
        "benchmark_current_drawdown": pct(benchmark_current_dd),
        "benchmark_max_drawdown": pct(benchmark_max_dd),
        "risk_breach_days": "n/a" if risk_breaches(conn, period_key) is None else str(risk_breaches(conn, period_key)),
        "pdf_url": pdf_url,
        "tags": ["performance"],
        "summary": f"PDF public performance record for {month['display_name']}.",
    }
    return front


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--site", type=Path, default=ROOT)
    parser.add_argument("--period-key")
    parser.add_argument("--completed-month", choices=["previous"])
    args = parser.parse_args()

    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        if args.completed_month == "previous":
            previous_key = period_key_for_previous_month(date.today())
            if previous_key not in completed_monthly_period_keys(conn):
                raise SystemExit(f"Previous month is not complete in the database: {previous_key}")
            period_keys = [previous_key]
        elif args.period_key:
            period_keys = [args.period_key]
        else:
            period_keys = completed_monthly_period_keys(conn)
        records = [write_one(conn, args.site, key) for key in period_keys]
        data_path = args.site / "data" / "performance_records.json"
        data_path.parent.mkdir(parents=True, exist_ok=True)
        existing = []
        if data_path.exists():
            try:
                existing = json.loads(data_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                existing = []
        by_month = {r.get("month_covered"): r for r in existing if isinstance(r, dict)}
        for record in records:
            by_month[record["month_covered"]] = record
        data_path.write_text(json.dumps(list(by_month.values()), indent=2) + "\n", encoding="utf-8")
        print(f"wrote {len(records)} PDF performance record(s)")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
