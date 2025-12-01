#!/usr/bin/env python
"""
One-stop daily runner for the futures core: build signals, then generate the daily report.
Wraps `run_daily_signals.py` (futures-focused MA cross + logging) and `daily_report.py`.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import os
import sys
from typing import List

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import daily_report, run_daily_signals  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run futures signals then generate the daily report.")
    parser.add_argument("--strategy", choices=["ma_cross", "sr"], default="sr")
    parser.add_argument("--symbols", nargs="+", default=["ES", "NQ", "GC"], help="Symbols to process")
    parser.add_argument(
        "--sec-types",
        nargs="+",
        default=["FUT", "FUT", "FUT"],
        help="Security types matching symbols (use FUT with expiries/local symbols to avoid sec-def errors)",
    )
    parser.add_argument("--source", choices=["ibkr", "csv"], default="ibkr")
    parser.add_argument("--data-paths", nargs="*", help="CSV paths matching symbols when source=csv")
    parser.add_argument("--outdir", default="signals", help="Where to write signals CSV")
    parser.add_argument("--date", help="Report date YYYYMMDD; defaults to today", default=None)
    parser.add_argument("--expiries", nargs="*", help="Optional futures expiries (YYYYMM or YYYYMMDD) matching symbols")
    parser.add_argument("--local-symbols", nargs="*", help="Optional IBKR local symbols matching symbols")
    parser.add_argument("--trading-classes", nargs="*", help="Optional trading classes matching symbols (defaults to symbol)")
    parser.add_argument(
        "--performance-path",
        default="data/performance/futures_decisions.csv",
        help="Path to performance log for daily report.",
    )
    parser.add_argument("--ib-host", help="IBKR host override (e.g., 127.0.0.1)")
    parser.add_argument("--ib-port", type=int, help="IBKR port override (e.g., 4002)")
    parser.add_argument("--ib-client-id", type=int, help="IBKR clientId override for orders")
    parser.add_argument("--ib-data-client-id", type=int, help="IBKR clientId override for data")
    parser.add_argument("--skip-report", action="store_true", help="Only run signals, skip report generation")
    args = parser.parse_args(argv)

    # Propagate IB overrides via env so downstream scripts pick them up.
    if args.ib_host:
        os.environ["PEARLALGO_IB_HOST"] = args.ib_host
    if args.ib_port:
        os.environ["PEARLALGO_IB_PORT"] = str(args.ib_port)
    if args.ib_client_id:
        os.environ["PEARLALGO_IB_CLIENT_ID"] = str(args.ib_client_id)
    if args.ib_data_client_id:
        os.environ["PEARLALGO_IB_DATA_CLIENT_ID"] = str(args.ib_data_client_id)

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
    if args.trading_classes:
        sig_args += ["--trading-classes", *args.trading_classes]

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

    rep_args: List[str] = ["--performance-path", args.performance_path]
    if args.date:
        rep_args += ["--date", args.date]

    rep_status = daily_report.main(rep_args)
    if rep_status != 0:
        print(f"[ERR] daily_report failed with status {rep_status}")
    return rep_status


if __name__ == "__main__":
    raise SystemExit(main())
