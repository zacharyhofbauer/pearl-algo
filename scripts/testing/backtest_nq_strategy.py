#!/usr/bin/env python3
"""Offline signal-only backtest for the MNQ intraday strategy.

Usage:

    python3 scripts/testing/backtest_nq_strategy.py path/to/mnq_1m.parquet

The input file must be a pandas-compatible file (parquet or CSV) with a
DateTime index (or a column named `timestamp`) and at least `open`, `high`,
`low`, `close`, `volume` columns.

This script does **not** place trades; it reuses the live strategy stack
(`NQIntradayStrategy` and `NQSignalGenerator`) to generate signals
bar-by-bar and prints a compact summary so you can sanity-check signal
frequency and quality on historical data.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from pearlalgo.strategies.nq_intraday.backtest_adapter import (
    NQIntradayConfig,
    BacktestResult,
    run_signal_backtest,
)


def _load_dataframe(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)

    if path.suffix.lower() in {".parquet", ".pq"}:
        df = pd.read_parquet(path)
    elif path.suffix.lower() in {".csv"}:
        df = pd.read_csv(path)
    else:
        raise ValueError(f"Unsupported file type: {path.suffix}")

    # Normalize index
    if not isinstance(df.index, pd.DatetimeIndex):
        # Try common column names
        for col in ("timestamp", "time", "datetime", "date"):
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], utc=True)
                df = df.set_index(col)
                break
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("DataFrame must have a DateTime index or a 'timestamp' column")

    # Ensure sorted by time
    df = df.sort_index()
    return df


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest MNQ intraday strategy in signal-only mode.")
    parser.add_argument("data_path", type=str, help="Path to MNQ 1m historical data (parquet or CSV)")
    args = parser.parse_args()

    data_path = Path(args.data_path)
    df = _load_dataframe(data_path)

    print(f"Loaded {len(df):,} bars from {data_path}")

    config = NQIntradayConfig.from_config_file()
    result: BacktestResult = run_signal_backtest(df, config=config)

    print("\n=== MNQ Intraday Signal Backtest (Signal-only) ===")
    print(f"Symbol: {config.symbol} | Timeframe: {config.timeframe} | Scan interval: {config.scan_interval}s")
    print(f"Total bars:      {result.total_bars:,}")
    print(f"Total signals:   {result.total_signals:,}")
    print(f"Avg confidence:  {result.avg_confidence:.3f}")
    print(f"Avg R:R (if set): {result.avg_risk_reward:.2f}:1")

    if result.total_signals == 0:
        print("\nNo signals were generated on this dataset. Check market hours and data quality.")


if __name__ == "__main__":
    main()
