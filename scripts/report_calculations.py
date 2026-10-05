"""Read-only period calculations. Keep the trading and site copies identical."""
import sqlite3

def rows(conn, sql, args=()):
    return conn.execute(sql, args).fetchall()

def signed_pct(value):
    return f"{value:+.2%}"

def usd_performance_between(conn: sqlite3.Connection, start_date: str, end_date: str) -> dict | None:
    found = conn.execute(
        """
        WITH daily AS (
            SELECT
                d.*,
                COALESCE(d.external_flow_cad / NULLIF(d.usdcad, 0), 0) AS external_flow_usd,
                (
                    SELECT SUM(n0.nav_usd)
                    FROM v_core_nav_daily n0
                    WHERE n0.date = (
                        SELECT MAX(n1.date)
                        FROM v_core_nav_daily n1
                        WHERE n1.date < d.date
                    )
                ) AS prior_nav_usd
            FROM fact_performance_paths_daily d
            WHERE d.period_key='since_inception'
              AND d.date BETWEEN ? AND ?
        )
        SELECT
            EXP(SUM(LN(NULLIF(1.0 + CASE
                WHEN prior_nav_usd IS NULL OR prior_nav_usd = 0 THEN 0
                ELSE (nav_usd - prior_nav_usd - external_flow_usd) / prior_nav_usd
            END, 0)))) - 1.0 AS portfolio_return_usd,
            (SELECT prior_nav_usd FROM daily ORDER BY date ASC LIMIT 1) AS nav_start_usd,
            (SELECT nav_usd FROM daily ORDER BY date DESC LIMIT 1) AS nav_end_usd,
            SUM(external_flow_usd) AS external_flows_usd,
            COALESCE(
              (SELECT value FROM fact_market_data m
                WHERE m.ticker = 'SP500TR'
                  AND m.date < (SELECT MIN(date) FROM daily)
                ORDER BY m.date DESC LIMIT 1),
              (SELECT value FROM fact_market_data m
                WHERE m.ticker = 'SP500TR'
                  AND m.date = (SELECT MIN(date) FROM daily))
            ) AS spx_start,
            (SELECT value FROM fact_market_data m
              WHERE m.ticker = 'SP500TR'
                AND m.date = (SELECT MAX(date) FROM daily)) AS spx_end
        FROM daily
        """,
        (start_date, end_date),
    ).fetchone()
    if found is None or found["portfolio_return_usd"] is None:
        return None
    if found["spx_end"] is None or not found["spx_start"]:
        raise ValueError("Missing benchmark data for the reporting period")
    benchmark = float(found["spx_end"]) / float(found["spx_start"]) - 1.0
    nav_start = float(found["nav_start_usd"] or 0)
    nav_end = float(found["nav_end_usd"] or 0)
    flows = float(found["external_flows_usd"] or 0)
    return {
        "portfolio": float(found["portfolio_return_usd"] or 0),
        "benchmark": benchmark,
        "excess": float(found["portfolio_return_usd"] or 0) - benchmark,
        "nav_start_usd": nav_start,
        "net_pnl_usd": nav_end - nav_start - flows,
    }

def core_ticker_attribution_between(conn: sqlite3.Connection, start_date: str, end_date: str, nav_start_usd: float) -> list[dict]:
    found = rows(
        conn,
        """
        WITH core_symbols(symbol, display_order) AS (
            VALUES ('SGOV', 1), ('SPY', 2), ('RSP', 2), ('GLD', 3), ('IBIT', 4)
        ),
        start_pos AS (
            SELECT cs.symbol, COALESCE(SUM(ps.quantity * ps.market_price), 0) AS amount_usd
            FROM core_symbols cs
            LEFT JOIN fact_pos_snap ps
              ON ps.snapshot_date = (
                  SELECT MAX(snapshot_date)
                  FROM fact_pos_snap
                  WHERE snapshot_date < ?
              )
             AND ps.symbol = cs.symbol
             AND COALESCE(ps.option_symbol, '') = ''
             AND ps.position_side = 'LONG'
            GROUP BY cs.symbol
        ),
        end_pos AS (
            SELECT cs.symbol, COALESCE(SUM(ps.quantity * ps.market_price), 0) AS amount_usd
            FROM core_symbols cs
            LEFT JOIN fact_pos_snap ps
              ON ps.snapshot_date = ?
             AND ps.symbol = cs.symbol
             AND COALESCE(ps.option_symbol, '') = ''
             AND ps.position_side = 'LONG'
            GROUP BY cs.symbol
        ),
        trades AS (
            SELECT cs.symbol, COALESCE(SUM(-t.quantity * t.price * t.multiplier), 0) AS amount_usd
            FROM core_symbols cs
            LEFT JOIN v_core_trades t
              ON t.trade_date >= ?
             AND t.trade_date <= ?
             AND t.symbol = cs.symbol
             AND COALESCE(t.option_symbol, '') = ''
             AND t.txn_type IN ('BUY','SELL')
            GROUP BY cs.symbol
        ),
        dividends AS (
            SELECT cs.symbol, COALESCE(SUM(t.net_amount_usd), 0) AS amount_usd
            FROM core_symbols cs
            LEFT JOIN v_core_trades t
              ON t.trade_date >= ?
             AND t.trade_date <= ?
             AND t.symbol = cs.symbol
             AND t.txn_type = 'DIV'
            GROUP BY cs.symbol
        )
        SELECT
            cs.symbol,
            COALESCE(e.amount_usd, 0) - COALESCE(s.amount_usd, 0)
              + COALESCE(t.amount_usd, 0) + COALESCE(d.amount_usd, 0) AS amount_usd
        FROM core_symbols cs
        LEFT JOIN start_pos s ON s.symbol = cs.symbol
        LEFT JOIN end_pos e ON e.symbol = cs.symbol
        LEFT JOIN trades t ON t.symbol = cs.symbol
        LEFT JOIN dividends d ON d.symbol = cs.symbol
        ORDER BY cs.display_order
        """,
        (start_date, end_date, start_date, end_date, start_date, end_date),
    )
    combined = {}
    for r in found:
        symbol = "SPY/RSP" if r["symbol"] in ("SPY", "RSP") else r["symbol"]
        combined[symbol] = combined.get(symbol, 0.0) + float(r["amount_usd"] or 0)
    found = [{"symbol": k, "amount_usd": v} for k, v in combined.items()]
    return [
        {
            "label": "Core " + str(r["symbol"]),
            "value": 0 if nav_start_usd == 0 else float(r["amount_usd"] or 0) / nav_start_usd,
            "display": signed_pct(0 if nav_start_usd == 0 else float(r["amount_usd"] or 0) / nav_start_usd),
            "amount_usd": float(r["amount_usd"] or 0),
        }
        for r in found
    ]

def drivers_between(conn: sqlite3.Connection, start_date: str, end_date: str, perf: dict) -> list[dict]:
    nav_start = float(perf["nav_start_usd"] or 0)
    ticker_lines = core_ticker_attribution_between(conn, start_date, end_date, nav_start)
    core_usd = sum(float(d["amount_usd"] or 0) for d in ticker_lines)
    costs = conn.execute(
        """
        SELECT
            -COALESCE(SUM(total_cost_usd), 0) AS amount_usd
        FROM v_report_costs_daily_usd
        WHERE date >= ?
          AND date <= ?
        """,
        (start_date, end_date),
    ).fetchone()
    costs_usd = float(costs["amount_usd"] or 0)
    satellite_usd = float(perf["net_pnl_usd"] or 0) - core_usd - costs_usd
    tail = [
        ("Satellite / other", satellite_usd),
        ("Costs", costs_usd),
    ]
    return ticker_lines + [
        {
            "label": label,
            "amount_usd": amount,
            "value": 0 if nav_start == 0 else amount / nav_start,
            "display": signed_pct(0 if nav_start == 0 else amount / nav_start),
        }
        for label, amount in tail
    ]
