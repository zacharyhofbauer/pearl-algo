from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from pearlalgo.backtesting.engine import SimpleBacktestEngine
from pearlalgo.core.portfolio import Portfolio
from pearlalgo.strategies.daily import MovingAverageCross, Breakout
from pearlalgo.data.loaders import load_csv


STRATEGIES = {
    "ma_cross": MovingAverageCross,
    "breakout": Breakout,
}


def load_data(path: Path) -> pd.DataFrame:
    return load_csv(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Simple backtest runner")
    parser.add_argument("--strategy", required=True, choices=STRATEGIES.keys())
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--data", required=True, help="Path to CSV with OHLCV")
    parser.add_argument("--fast", type=int, default=10, help="Fast MA (for ma_cross)")
    parser.add_argument("--slow", type=int, default=20, help="Slow MA (for ma_cross)")
    parser.add_argument("--lookback", type=int, default=20, help="Breakout lookback")
    args = parser.parse_args(argv)

    data = load_data(Path(args.data))
    portfolio = Portfolio(cash=100000)
    engine = SimpleBacktestEngine(portfolio)

    if args.strategy == "ma_cross":
        strat = MovingAverageCross(fast=args.fast, slow=args.slow)
    else:
        strat = Breakout(lookback=args.lookback)

    result = engine.run_strategy(strat, data, symbol=args.symbol)
    equity = portfolio.mark_to_market({args.symbol: data["Close"].iloc[-1]})
    print(f"Strategy: {strat.name} | Symbol: {args.symbol} | Fills: {len(result.fills)} | Equity: {equity}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
