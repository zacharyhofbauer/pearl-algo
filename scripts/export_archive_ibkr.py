#!/usr/bin/env python3
"""
Export IBKR Virtual archive data to JSON for the web app.
Reads from data/archive/ibkr_virtual/trades.db and outputs to stdout.
Usage: python scripts/export_archive_ibkr.py [summary|trades|daily]
  summary - aggregate stats (default)
  trades - paginated trade list
  daily - daily P&L breakdown
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "archive" / "ibkr_virtual" / "trades.db"


def get_conn():
    if not DB_PATH.exists():
        return None
    return sqlite3.connect(DB_PATH)


def summary(conn):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            COUNT(*) as total_trades,
            COALESCE(SUM(CASE WHEN is_win = 1 THEN 1 ELSE 0 END), 0) as wins,
            COALESCE(SUM(pnl), 0) as total_pnl,
            MIN(entry_time) as first_trade,
            MAX(exit_time) as last_trade
        FROM trades
        WHERE exit_time IS NOT NULL
        """
    )
    row = cur.fetchone()
    if not row:
        return {"total_trades": 0, "wins": 0, "total_pnl": 0, "win_rate": 0}
    total, wins, pnl, first, last = row
    win_rate = (wins / total * 100) if total else 0
    return {
        "total_trades": total,
        "wins": wins,
        "total_pnl": round(pnl, 2),
        "win_rate": round(win_rate, 1),
        "first_trade": first,
        "last_trade": last,
    }


def daily_pnl(conn):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT date(exit_time) as day, COUNT(*) as trades, SUM(pnl) as pnl,
               SUM(CASE WHEN is_win = 1 THEN 1 ELSE 0 END) as wins
        FROM trades
        WHERE exit_time IS NOT NULL
        GROUP BY day
        ORDER BY day
        """
    )
    rows = cur.fetchall()
    return [
        {"day": r[0], "trades": r[1], "pnl": round(r[2], 2), "wins": r[3]}
        for r in rows
    ]


def trades(conn, limit=100, offset=0):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT trade_id, signal_id, direction, entry_price, exit_price, pnl, is_win,
               exit_reason, entry_time, exit_time, hold_duration_minutes, regime
        FROM trades
        WHERE exit_time IS NOT NULL
        ORDER BY exit_time DESC
        LIMIT ? OFFSET ?
        """,
        (limit, offset),
    )
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    return [dict(zip(cols, r)) for r in rows]


def equity_curve(conn):
    """Cumulative P&L over time for chart."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT exit_time as time, pnl,
               SUM(pnl) OVER (ORDER BY exit_time) as cumulative_pnl
        FROM trades
        WHERE exit_time IS NOT NULL
        ORDER BY exit_time
        """
    )
    rows = cur.fetchall()
    return [{"time": r[0], "pnl": round(r[1], 2), "cumulative_pnl": round(r[2], 2)} for r in rows]


def stats(conn):
    """Detailed stats: direction breakdown, exit reasons, hold duration."""
    cur = conn.cursor()
    # Direction breakdown
    cur.execute(
        """
        SELECT direction,
               COUNT(*) as trades,
               SUM(CASE WHEN is_win = 1 THEN 1 ELSE 0 END) as wins,
               ROUND(SUM(pnl), 2) as total_pnl,
               ROUND(AVG(pnl), 2) as avg_pnl,
               ROUND(AVG(hold_duration_minutes), 1) as avg_hold
        FROM trades
        WHERE exit_time IS NOT NULL
        GROUP BY direction
        """
    )
    directions = {}
    for r in cur.fetchall():
        directions[r[0]] = {
            "trades": r[1], "wins": r[2], "total_pnl": r[3],
            "avg_pnl": r[4], "avg_hold": r[5],
            "win_rate": round(r[2] / r[1] * 100, 1) if r[1] else 0,
        }

    # Exit reasons
    cur.execute(
        """
        SELECT exit_reason, COUNT(*) as cnt
        FROM trades
        WHERE exit_time IS NOT NULL
        GROUP BY exit_reason
        ORDER BY cnt DESC
        """
    )
    exit_reasons = [{"reason": r[0], "count": r[1]} for r in cur.fetchall()]

    # Averages
    cur.execute(
        """
        SELECT ROUND(AVG(hold_duration_minutes), 1),
               ROUND(AVG(pnl), 2),
               ROUND(SUM(CASE WHEN pnl > 0 THEN pnl ELSE 0 END), 2) as gross_wins,
               ROUND(ABS(SUM(CASE WHEN pnl < 0 THEN pnl ELSE 0 END)), 2) as gross_losses
        FROM trades
        WHERE exit_time IS NOT NULL
        """
    )
    r = cur.fetchone()
    avg_hold = r[0] or 0
    expectancy = r[1] or 0
    gross_wins = r[2] or 0
    gross_losses = r[3] or 1
    profit_factor = round(gross_wins / gross_losses, 2) if gross_losses > 0 else 0

    return {
        "directions": directions,
        "exit_reasons": exit_reasons,
        "avg_hold_minutes": avg_hold,
        "expectancy": expectancy,
        "profit_factor": profit_factor,
        "gross_wins": gross_wins,
        "gross_losses": gross_losses,
    }


def trade_by_id(conn, trade_id):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT trade_id, signal_id, signal_type, direction, entry_price, exit_price,
               stop_loss, take_profit, pnl, is_win, exit_reason, entry_time, exit_time,
               hold_duration_minutes, regime
        FROM trades
        WHERE trade_id = ?
        """,
        (trade_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", nargs="?", default="summary",
                        choices=["summary", "trades", "daily", "equity", "trade", "stats"])
    parser.add_argument("trade_id", nargs="?", default=None)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--offset", type=int, default=0)
    args = parser.parse_args()

    conn = get_conn()
    if not conn:
        json.dump({"error": "Archive database not found"}, sys.stdout)
        sys.exit(0)  # Exit 0 so API can return the error JSON

    try:
        if args.mode == "summary":
            data = summary(conn)
        elif args.mode == "daily":
            data = daily_pnl(conn)
        elif args.mode == "trades":
            data = trades(conn, limit=args.limit, offset=args.offset)
        elif args.mode == "equity":
            data = equity_curve(conn)
        elif args.mode == "stats":
            data = stats(conn)
        elif args.mode == "trade" and args.trade_id:
            data = trade_by_id(conn, args.trade_id)
            if not data:
                json.dump({"error": "Trade not found"}, sys.stdout)
                sys.exit(1)
        else:
            json.dump({"error": "Invalid mode or missing trade_id"}, sys.stdout)
            sys.exit(1)
        json.dump(data, sys.stdout, indent=0)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
