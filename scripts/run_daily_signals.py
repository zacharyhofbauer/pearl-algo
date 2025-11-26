from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd

from pearlalgo.strategies.daily import MovingAverageCross, Breakout
from pearlalgo.data_providers.ibkr_data_provider import IBKRDataProvider
from pearlalgo.data.loaders import load_csv


def get_data(symbol: str, sec_type: str, source: str, path: Path | None = None) -> pd.DataFrame:
    if source == "csv":
        if not path:
            raise ValueError("CSV source requires --data-path")
        return load_csv(path)
    # default: IBKR historical fetch
    provider = IBKRDataProvider()
    df = provider.fetch_historical(symbol, sec_type=sec_type, duration="2 D", bar_size="15 mins")
    return df


def run_strategy(strategy_name: str, data: pd.DataFrame):
    if strategy_name == "ma_cross":
        strat = MovingAverageCross(fast=10, slow=20)
    else:
        strat = Breakout(lookback=20)
    sigs = strat.run(data)
    # attach close for sizing/reference
    return sigs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run daily signals and write to CSV.")
    parser.add_argument("--strategy", choices=["ma_cross", "breakout"], default="ma_cross")
    parser.add_argument("--symbols", nargs="+", default=["ES", "NQ", "SPY", "QQQ"])
    parser.add_argument("--sec-types", nargs="+", default=["FUT_CONT", "FUT_CONT", "STK", "STK"])
    parser.add_argument("--source", choices=["ibkr", "csv"], default="ibkr")
    parser.add_argument("--data-paths", nargs="*", help="CSV paths matching symbols order when source=csv")
    parser.add_argument("--outdir", default="signals")
    args = parser.parse_args(argv)

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    today = datetime.utcnow().strftime("%Y%m%d")
    outfile = outdir / f"{today}_signals.csv"

    rows = []
    data_paths = args.data_paths or []
    for idx, symbol in enumerate(args.symbols):
        sec_type = args.sec_types[idx] if idx < len(args.sec_types) else "STK"
        path = Path(data_paths[idx]) if args.source == "csv" and idx < len(data_paths) else None
        try:
            df = get_data(symbol, sec_type, source=args.source, path=path)
            sigs = run_strategy(args.strategy, df)
            if sigs.empty:
                continue
            latest = sigs.iloc[-1]
            direction = "BUY" if latest.get("entry", 0) > 0 else "SELL" if latest.get("entry", 0) < 0 else "FLAT"
            rows.append(
                {
                    "timestamp": datetime.utcnow().isoformat(),
                    "symbol": symbol,
                    "instrument_type": sec_type,
                    "direction": direction,
                    "size_hint": latest.get("size", 1),
                }
            )
        except Exception as exc:
            print(f"[WARN] Failed to build signal for {symbol} ({sec_type}): {exc}")
            continue

    if rows:
        df_out = pd.DataFrame(rows)
        df_out.to_csv(outfile, index=False)
        print(f"[OK] Wrote {len(rows)} signals -> {outfile}")
    else:
        print("[WARN] No signals generated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
