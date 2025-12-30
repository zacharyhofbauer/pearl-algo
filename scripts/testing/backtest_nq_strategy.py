#!/usr/bin/env python3
"""DEPRECATED: Compatibility shim for signal-only backtests.

This script is retained for backward compatibility. It delegates to the
canonical backtest CLI:

    python scripts/backtesting/backtest_cli.py signal --data-path <file>

Usage (deprecated):
    python3 scripts/testing/backtest_nq_strategy.py path/to/mnq_1m.parquet

Prefer the canonical CLI for new work:
    python scripts/backtesting/backtest_cli.py signal --data-path path/to/mnq_1m.parquet
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

# Add project root for imports
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))


def main() -> int:
    warnings.warn(
        "scripts/testing/backtest_nq_strategy.py is deprecated. "
        "Use: python scripts/backtesting/backtest_cli.py signal --data-path <file>",
        DeprecationWarning,
        stacklevel=1,
    )
    print(
        "⚠️  DEPRECATION WARNING: This script is deprecated.\n"
        "   Prefer: python scripts/backtesting/backtest_cli.py signal --data-path <file>\n"
    )

    if len(sys.argv) < 2:
        print("Usage: python3 scripts/testing/backtest_nq_strategy.py <data_path>")
        print("\nCanonical CLI usage:")
        print("  python scripts/backtesting/backtest_cli.py signal --data-path <file>")
        return 1

    data_path = sys.argv[1]

    # Import and run the canonical CLI's signal mode
    # We avoid subprocess to maintain the same process/environment
    from scripts.backtesting.backtest_cli import (
        load_ohlcv_data,
        slice_by_date_range,
        print_summary,
        BacktestReport,
    )
    from pearlalgo.strategies.nq_intraday.backtest_adapter import (
        NQIntradayConfig,
        run_signal_backtest,
    )

    try:
        df = load_ohlcv_data(Path(data_path))
        print(f"Loaded {len(df):,} bars from {data_path}")

        # No date slicing (full dataset), same as old behavior
        df_sliced, date_info = slice_by_date_range(df, start=None, end=None)
        config = NQIntradayConfig.from_config_file()
        result = run_signal_backtest(df_sliced, config=config, return_signals=True)

        report = BacktestReport(
            symbol=config.symbol,
            decision_timeframe="1m",
            date_range=date_info,
            result=result,
        )
        print_summary(report)
        return 0

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
