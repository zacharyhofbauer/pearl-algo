#!/usr/bin/env python
"""
One-stop daily runner: build signals then generate the daily report.

This wraps `run_daily_signals.py` and `daily_report.py` so you don't have to
call multiple scripts manually. Futures can be specified with expiries or
local symbols to avoid IBKR sec-def errors.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from scripts import daily_report, run_daily_signals


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run signals then generate the daily report.")
    parser.add_argument("--strategy", choices=["ma_cross", "breakout"], default="ma_cross")
    parser.add_argument("--symbols", nargs="+", default=["ES", "NQ", "SPY", "QQQ"], help="Symbols to process")
    parser.add_argument(
        "--sec-types",
        nargs="+",
        default=["FUT", "FUT", "STK", "STK"],
        help="Security types matching symbols (use FUT with expiries/local symbols to avoid sec-def errors)",
    )
    parser.add_argument("--source", choices=["ibkr", "csv"], default="ibkr")
    parser.add_argument("--data-paths", nargs="*", help="CSV paths matching symbols when source=csv")
    parser.add_argument("--outdir", default="signals", help="Where to write signals CSV")
    parser.add_argument("--date", help="Report date YYYYMMDD; defaults to today", default=None)
    parser.add_argument("--expiries", nargs="*", help="Optional futures expiries (YYYYMM or YYYYMMDD) matching symbols")
    parser.add_argument("--local-symbols", nargs="*", help="Optional IBKR local symbols matching symbols")
    parser.add_argument("--skip-report", action="store_true", help="Only run signals, skip report generation")
    args = parser.parse_args(argv)

    # Build args for run_daily_signals
    sig_args: List[str] = [
        "--strategy",
        args.strategy,
        "--outdir",
        args.outdir,
        "--source",
        args.source,
    ]

    if args.symbols:
        sig_args += ["--symbols", *args.symbols]
    if args.sec_types:
        sig_args += ["--sec-types", *args.sec_types]
    if args.data_paths:
        sig_args += ["--data-paths", *args.data_paths]
    if args.expiries:
        sig_args += ["--expiries", *args.expiries]
    if args.local_symbols:
        sig_args += ["--local-symbols", *args.local_symbols]

    sig_status = run_daily_signals.main(sig_args)
    if sig_status != 0:
        print(f"[ERR] run_daily_signals failed with status {sig_status}")
        return sig_status

    # If report is skipped, stop after signals.
    if args.skip_report:
        return 0

    # Resolve date for report and ensure signals file exists.
    report_date = args.date or datetime.now(timezone.utc).strftime("%Y%m%d")
    signals_path = Path(args.outdir) / f"{report_date}_signals.csv"
    if not signals_path.exists():
        print(f"[WARN] Expected signals file not found: {signals_path}; report may be empty")

    rep_args: List[str] = []
    if args.date:
        rep_args = ["--date", args.date]

    rep_status = daily_report.main(rep_args)
    if rep_status != 0:
        print(f"[ERR] daily_report failed with status {rep_status}")
    return rep_status


if __name__ == "__main__":
    raise SystemExit(main())
