#!/usr/bin/env python
from __future__ import annotations

"""
Poll a journal/performance log and create a RISK_HALT file if daily loss is breached.
Supports both the legacy journal/trades.csv and the futures performance log.
"""

import argparse
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd


def current_pnl(trades_path: Path) -> float:
    if not trades_path.exists():
        return 0.0
    df = pd.read_csv(trades_path)
    if "pnl_after" in df.columns and not df.empty:
        return float(df["pnl_after"].iloc[-1])
    return 0.0


def latest_realized_from_performance(perf_path: Path) -> float:
    if not perf_path.exists():
        return 0.0
    df = pd.read_csv(perf_path)
    if "realized_pnl" in df.columns and not df.empty:
        return float(df["realized_pnl"].fillna(0).sum())
    return 0.0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Simple risk monitor loop (daily loss guard).")
    parser.add_argument("--max-daily-loss", type=float, required=True, help="Trigger halt if breached.")
    parser.add_argument("--interval", type=int, default=60, help="Seconds between checks.")
    parser.add_argument(
        "--performance-path",
        default="data/performance/futures_decisions.csv",
        help="Optional performance log path to sum realized_pnl.",
    )
    parser.add_argument(
        "--journal-path",
        default="journal/trades.csv",
        help="Legacy journal path; used if performance log missing realized pnl.",
    )
    parser.add_argument(
        "--halt-file",
        default="RISK_HALT",
        help="File to write when risk breach occurs.",
    )
    args = parser.parse_args(argv)

    halt_file = Path(args.halt_file)
    perf_path = Path(args.performance_path)
    journal_path = Path(args.journal_path)

    try:
        while True:
            ts = datetime.now(timezone.utc).isoformat()
            realized = latest_realized_from_performance(perf_path)
            if realized == 0.0:
                realized = current_pnl(journal_path)
            if realized < -abs(args.max_daily_loss):
                halt_file.write_text(f"{ts} Breached max daily loss {args.max_daily_loss}, pnl={realized}\n")
                print(f"[{ts}] RISK HALT: pnl={realized} < -{args.max_daily_loss}. Wrote {halt_file}")
                break
            if halt_file.exists():
                print(f"[{ts}] RISK HALT file exists; stop trading.")
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("Risk monitor stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
