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
    front_matter,
    monthly_period_keys,
    pct,
    report_periods,
    risk_breaches,
    score,
)


PAGE_W, PAGE_H = 612, 792
INK = (0.08, 0.09, 0.10)
MUTED = (0.37, 0.40, 0.42)
LINE = (0.84, 0.82, 0.77)
PAPER = (0.98, 0.98, 0.96)
ACCENT = (0.19, 0.37, 0.36)
ACCENT2 = (0.55, 0.37, 0.17)
BAD = (0.54, 0.18, 0.18)


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


def table(pdf: Pdf, x: float, y: float, widths: list[float], header: list[str], rows: list[list[object]], row_h: float = 15) -> float:
    pdf.rect(x, y - row_h, sum(widths), row_h, fill=PAPER)
    cx = x
    for w, h in zip(widths, header):
        pdf.text(cx + 4, y - 10, h, 7, MUTED, True)
        cx += w
    y -= row_h
    for row in rows:
        pdf.line(x, y, x + sum(widths), y)
        cx = x
        for w, cell in zip(widths, row):
            pdf.text(cx + 4, y - 10, cell, 7, INK)
            cx += w
        y -= row_h
    pdf.rect(x, y, sum(widths), row_h * (len(rows) + 1))
    return y


def path_chart(pdf: Pdf, x: float, y: float, w: float, h: float, period: dict) -> None:
    pts = period.get("path", [])
    pdf.rect(x, y - h, w, h, fill=PAPER)
    pdf.text(x + 8, y - 14, f"Performance path: {period['start_date']} to {period['end_date']}", 8, INK, True)
    if not pts:
        pdf.text(x + 8, y - 34, "No path data", 8, MUTED)
        return
    vals = [float(p["portfolio"]) for p in pts] + [float(p["benchmark"]) for p in pts] + [100.0]
    lo, hi = min(vals), max(vals)
    pad = max((hi - lo) * 0.15, 1)
    lo, hi = lo - pad, hi + pad
    left, right, top, bottom = x + 38, x + w - 12, y - 30, y - h + 28

    def xy(i: int, value: float) -> tuple[float, float]:
        px = left + (right - left) * (i / max(len(pts) - 1, 1))
        py = bottom + (value - lo) / (hi - lo) * (top - bottom)
        return px, py

    for value in sorted([lo, 100.0, hi]):
        _, py = xy(0, value)
        pdf.line(left, py, right, py)
        pdf.text(x + 8, py - 3, f"{value:.1f}", 6, MUTED)
    pdf.polyline([xy(i, float(p["portfolio"])) for i, p in enumerate(pts)], ACCENT)
    pdf.polyline([xy(i, float(p["benchmark"])) for i, p in enumerate(pts)], ACCENT2)
    pdf.text(left, y - h + 12, pts[0]["date"], 6, MUTED)
    pdf.text((left + right) / 2 - 18, y - h + 12, pts[len(pts) // 2]["date"], 6, MUTED)
    pdf.text(right - 42, y - h + 12, pts[-1]["date"], 6, MUTED)
    pdf.text(left, y - 24, "Portfolio", 7, ACCENT, True)
    pdf.text(left + 52, y - 24, "S&P 500 TR", 7, ACCENT2, True)


def driver_chart(pdf: Pdf, x: float, y: float, w: float, h: float, drivers: list[dict]) -> None:
    pdf.rect(x, y - h, w, h, fill=PAPER)
    pdf.text(x + 8, y - 14, "NAV return drivers", 8, INK, True)
    if not drivers:
        pdf.text(x + 8, y - 34, "No driver data", 8, MUTED)
        return
    max_abs = max(abs(float(d["value"])) for d in drivers) or 0.01
    mid = x + w * 0.54
    pdf.line(mid, y - 26, mid, y - h + 12)
    row_h = min(17, (h - 38) / max(len(drivers), 1))
    for i, d in enumerate(drivers[:9]):
        by = y - 36 - i * row_h
        v = float(d["value"])
        bw = abs(v) / max_abs * (w * 0.34)
        bx = mid - bw if v < 0 else mid
        pdf.text(x + 8, by + 2, d["label"], 6, INK)
        pdf.rect(bx, by, bw, 8, stroke=ACCENT if v >= 0 else BAD, fill=ACCENT if v >= 0 else BAD)
        pdf.text(x + w - 36, by + 2, d["display"], 6, INK)


def risk_chart(pdf: Pdf, x: float, y: float, w: float, h: float, months: list[dict]) -> None:
    pdf.rect(x, y - h, w, h, fill=PAPER)
    pdf.text(x + 8, y - 14, "Risk breach days by month", 8, INK, True)
    if not months:
        pdf.text(x + 8, y - 34, "No risk data", 8, MUTED)
        return
    max_v = max(int(m["breaches"]) for m in months) or 1
    left, right, bottom, top = x + 28, x + w - 14, y - h + 28, y - 30
    bw = (right - left) / max(len(months), 1) * 0.55
    pdf.line(left, bottom, right, bottom)
    for i, m in enumerate(months):
        cx = left + (right - left) * (i + 0.5) / len(months)
        bh = int(m["breaches"]) / max_v * (top - bottom)
        pdf.rect(cx - bw / 2, bottom, bw, bh, stroke=ACCENT, fill=ACCENT)
        pdf.text(cx - 5, bottom + bh + 4, m["breaches"], 6, INK)
        pdf.text(cx - 13, y - h + 12, m["month"], 6, MUTED)


def write_pdf(path: Path, title: str, periods: list[dict]) -> None:
    pdf = Pdf()
    for p in periods:
        pdf.page()
        pdf.text(42, 750, title, 20, INK, True)
        pdf.text(42, 730, f"{p['label']} | {p['start_date']} to {p['end_date']} | CAD time-weighted", 10, MUTED)
        pdf.line(42, 718, 570, 718)

        path_chart(pdf, 42, 700, 318, 155, p)
        table(pdf, 374, 700, [52, 54, 58], ["Portfolio", "S&P TR", "Diff"], [[p["portfolio"], p["benchmark"], p["excess"]]], 18)

        driver_chart(pdf, 42, 520, 318, 155, p.get("drivers", []))
        table(
            pdf,
            374,
            520,
            [98, 66],
            ["Driver", "Contribution"],
            [[d["label"], d["display"]] for d in p.get("drivers", [])[:8]],
            15,
        )

        risk_chart(pdf, 42, 340, 238, 150, p.get("risk_months", []))
        table(
            pdf,
            292,
            340,
            [76, 38, 38, 54, 32],
            ["Metric", "Avg", "Median", "Limit", "Breaches"],
            [[r["metric"], r["avg"], r["median"], r["limit"], r["breach_days"]] for r in p.get("risk_rows", [])],
            13,
        )
        pdf.text(42, 36, "Frozen public record. Source: reporting database export.", 7, MUTED)
    pdf.save(path)


def period_key_for_previous_month(today: date) -> str:
    year = today.year
    month = today.month - 1
    if month == 0:
        year -= 1
        month = 12
    return f"{date(year, month, 1).strftime("%b").lower()}_{year}"


def write_record_page(root: Path, period_key: str, front: dict) -> None:
    suffix = period_key.replace("month_", "").replace("_", "-")
    pdf_url = f"/reports/performance/{suffix}-performance-record.pdf"
    front = dict(front)
    front["pdf_url"] = pdf_url
    body = f"""{front_matter(front)}

Open the frozen PDF record:

[Download performance record PDF]({pdf_url})
"""
    post_path = root / "content" / "performance" / f"{suffix}.md"
    post_path.parent.mkdir(parents=True, exist_ok=True)
    post_path.write_text(body, encoding="utf-8")


def write_one(conn: sqlite3.Connection, root: Path, period_key: str) -> dict:
    month = score(conn, period_key)
    if month is None:
        raise SystemExit(f"No data for {period_key}")
    periods = report_periods(conn, period_key)
    suffix = period_key.replace("month_", "").replace("_", "-")
    pdf_url = f"/reports/performance/{suffix}-performance-record.pdf"
    pdf_path = root / "static" / pdf_url.lstrip("/")
    title = f"{month['display_name']} Performance Record"
    write_pdf(pdf_path, title, periods)
    front = {
        "title": title,
        "date": f"{month['last_date']}T08:00:00-07:00",
        "draft": False,
        "month_covered": month["display_name"],
        "portfolio_1m": periods[0]["portfolio"] if periods else pct(month["portfolio"]),
        "benchmark_1m": periods[0]["benchmark"] if periods else pct(month["benchmark"]),
        "excess_1m": periods[0]["excess"] if periods else "n/a",
        "portfolio_3m": next((p["portfolio"] for p in periods if p["label"] == "3M"), "n/a"),
        "portfolio_12m": next((p["portfolio"] for p in periods if p["label"] == "12M"), "n/a"),
        "portfolio_since_inception": next((p["portfolio"] for p in periods if p["label"] == "Since Inception"), "n/a"),
        "benchmark_since_inception": next((p["benchmark"] for p in periods if p["label"] == "Since Inception"), "n/a"),
        "max_drawdown": "n/a",
        "risk_breach_days": "n/a" if risk_breaches(conn, period_key) is None else str(risk_breaches(conn, period_key)),
        "pdf_url": pdf_url,
        "tags": ["performance"],
        "summary": f"PDF public performance record for {month['display_name']}.",
    }
    write_record_page(root, period_key, front)
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
            period_keys = [period_key_for_previous_month(date.today())]
        elif args.period_key:
            period_keys = [args.period_key]
        else:
            period_keys = monthly_period_keys(conn)
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
        latest_path = args.site / "data" / "latest_performance.json"
        latest_path.write_text(json.dumps(records[-1], indent=2) + "\n", encoding="utf-8")
        print(f"wrote {len(records)} PDF performance record(s)")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
