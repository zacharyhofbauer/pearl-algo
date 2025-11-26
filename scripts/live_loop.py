#!/usr/bin/env python
from __future__ import annotations

import argparse
import time
from datetime import datetime, timezone
from pathlib import Path

from pearlalgo.data_providers.ibkr_data_provider import IBKRDataProvider
from pearlalgo.data.loaders import load_csv
from pearlalgo.strategies.daily import MovingAverageCross, Breakout


def fetch_data(symbol: str, sec_type: str, source: str, data_path: Path | None = None):
    if source == "csv":
        if not data_path:
            raise ValueError("CSV source requires --data-path")
        return load_csv(data_path)
    provider = IBKRDataProvider()
    return provider.fetch_historical(symbol, sec_type=sec_type, duration="2 D", bar_size="15 mins")


def run_once(strategy_name: str, symbol: str, sec_type: str, source: str, data_path: Path | None):
    if strategy_name == "ma_cross":
        strat = MovingAverageCross(fast=10, slow=20)
    else:
        strat = Breakout(lookback=20)

    df = fetch_data(symbol, sec_type, source, data_path)
    sigs = strat.run(df)
    latest = sigs.iloc[-1] if not sigs.empty else None
    ts = datetime.now(timezone.utc).isoformat()
    if latest is None:
        print(f"[{ts}] {symbol}: no data")
        return
    entry = latest.get("entry", 0)
    direction = "BUY" if entry > 0 else "SELL" if entry < 0 else "FLAT"
    size = latest.get("size", 1)
    print(f"[{ts}] {symbol} ({sec_type}) {strategy_name}: direction={direction} size={size}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Live-ish loop: fetch data, run strategy, print signal.")
    parser.add_argument("--symbols", nargs="+", default=["ES", "NQ"])
    parser.add_argument("--sec-types", nargs="+", default=["FUT_CONT", "FUT_CONT"])
    parser.add_argument("--strategy", choices=["ma_cross", "breakout"], default="ma_cross")
    parser.add_argument("--source", choices=["ibkr", "csv"], default="ibkr")
    parser.add_argument("--data-paths", nargs="*", help="CSV paths matching symbols when source=csv")
    parser.add_argument("--interval", type=int, default=300, help="Loop interval seconds")
    args = parser.parse_args(argv)

    data_paths = args.data_paths or []

    try:
        while True:
            for idx, sym in enumerate(args.symbols):
                sec_type = args.sec_types[idx] if idx < len(args.sec_types) else "STK"
                path = Path(data_paths[idx]) if args.source == "csv" and idx < len(data_paths) else None
                try:
                    run_once(args.strategy, sym, sec_type, args.source, path)
                except Exception as exc:
                    ts = datetime.now(timezone.utc).isoformat()
                    print(f"[{ts}] WARN {sym} failed: {exc}")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("Exiting loop.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
