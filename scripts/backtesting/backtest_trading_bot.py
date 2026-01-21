#!/usr/bin/env python3
"""
Trading Bot Backtesting CLI

Backtest a single trading bot variant (including PearlAutoBot) on historical OHLCV data.

Usage:
  python3 scripts/backtesting/backtest_trading_bot.py --bot PearlAutoBot --data-path data/historical/MNQ_1m.parquet
  python3 scripts/backtesting/backtest_trading_bot.py --bot TrendFollowerBot --data-path data/historical/MNQ_1m.parquet --timeframe 5m
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import pandas as pd

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))

from pearlalgo.strategies.trading_bots import BotConfig, create_bot  # noqa: E402
from pearlalgo.strategies.trading_bots.backtest_adapter import (  # noqa: E402
    TradingBotBacktestResult,
    backtest_trading_bot,
)


def _parse_timeframe_to_minutes(timeframe: str) -> int:
    tf = str(timeframe or "").strip().lower()
    if tf.endswith("m"):
        return int(tf[:-1])
    if tf.endswith("h"):
        return int(tf[:-1]) * 60
    raise ValueError(f"Unsupported timeframe: {timeframe!r} (use Xm or Xh)")


def _load_ohlcv(path: Path) -> pd.DataFrame:
    df = pd.read_parquet(path)
    # Normalize datetime index
    if "timestamp" in df.columns:
        df = df.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
        df = df.dropna(subset=["timestamp"]).set_index("timestamp")
    elif not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("Data must have a 'timestamp' column or a DateTimeIndex")

    df = df.sort_index()
    # Normalize common column names
    cols = {c.lower(): c for c in df.columns}
    required = ["open", "high", "low", "close"]
    missing = [c for c in required if c not in cols]
    if missing:
        raise ValueError(f"Missing OHLC columns: {missing} (columns={list(df.columns)})")
    return df


def _resample_ohlcv(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    minutes = _parse_timeframe_to_minutes(timeframe)
    if minutes <= 1:
        return df

    rule = f"{minutes}min"
    agg: Dict[str, Any] = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
    }
    if "volume" in df.columns:
        agg["volume"] = "sum"
    out = df.resample(rule).agg(agg).dropna(subset=["open", "high", "low", "close"])
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Trading Bot Backtesting CLI")
    parser.add_argument(
        "--bot",
        required=True,
        choices=["PearlAutoBot", "TrendFollowerBot", "BreakoutBot", "MeanReversionBot"],
        help="Trading bot variant to backtest",
    )
    parser.add_argument("--data-path", required=True, type=str, help="Parquet OHLCV file")
    parser.add_argument("--symbol", default="MNQ", help="Symbol label (metadata only)")
    parser.add_argument("--timeframe", default="5m", help="Target timeframe (resamples input)")
    parser.add_argument("--tick-value", type=float, default=2.0, help="Tick value (e.g., MNQ=2.0, NQ=20.0)")
    parser.add_argument("--out-dir", type=str, default="data/reports", help="Output directory for JSON report")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    data_path = Path(args.data_path)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    df = _load_ohlcv(data_path)
    df = _resample_ohlcv(df, args.timeframe)

    cfg = BotConfig(
        name=args.bot,
        description=f"Backtest {args.bot}",
        symbol=str(args.symbol),
        timeframe=str(args.timeframe),
        max_positions=1,
        risk_per_trade=0.01,
        stop_loss_pct=0.005,
        take_profit_pct=0.01,
        min_confidence=0.6,
        parameters={},
        enable_alerts=False,
    )
    bot = create_bot(args.bot, cfg)

    result: TradingBotBacktestResult = backtest_trading_bot(bot=bot, df=df, tick_value=float(args.tick_value))

    summary = {
        "bot": args.bot,
        "symbol": args.symbol,
        "timeframe": args.timeframe,
        "rows": int(len(df)),
        "total_trades": int(result.total_trades),
        "win_rate": float(result.win_rate),
        "total_pnl": float(result.total_pnl),
        "profit_factor": float(result.profit_factor),
        "max_drawdown": float(result.max_drawdown),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    report_path = out_dir / f"backtest_{args.bot}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    report_path.write_text(json.dumps({"summary": summary, "result": result.to_dict()}, indent=2))

    print(json.dumps(summary, indent=2))
    print(f"\nSaved report: {report_path}")


if __name__ == "__main__":
    main()

