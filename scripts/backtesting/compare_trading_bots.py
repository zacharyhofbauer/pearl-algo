#!/usr/bin/env python3
"""
Trading Bot Comparison CLI

Compare multiple trading bot variants side-by-side on the same historical OHLCV data.

Usage:
  python3 scripts/backtesting/compare_trading_bots.py --bots all --data-path data/historical/MNQ_1m.parquet
  python3 scripts/backtesting/compare_trading_bots.py --bots PearlAutoBot,TrendFollowerBot --data-path data/historical/MNQ_1m.parquet
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))

from pearlalgo.strategies.trading_bots import BotConfig, create_bot  # noqa: E402
from pearlalgo.strategies.trading_bots.backtest_adapter import backtest_trading_bot  # noqa: E402


ALL_BOTS = ["PearlAutoBot", "TrendFollowerBot", "BreakoutBot", "MeanReversionBot"]


def _parse_timeframe_to_minutes(timeframe: str) -> int:
    tf = str(timeframe or "").strip().lower()
    if tf.endswith("m"):
        return int(tf[:-1])
    if tf.endswith("h"):
        return int(tf[:-1]) * 60
    raise ValueError(f"Unsupported timeframe: {timeframe!r} (use Xm or Xh)")


def _load_ohlcv(path: Path) -> pd.DataFrame:
    df = pd.read_parquet(path)
    if "timestamp" in df.columns:
        df = df.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
        df = df.dropna(subset=["timestamp"]).set_index("timestamp")
    elif not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("Data must have a 'timestamp' column or a DateTimeIndex")
    return df.sort_index()


def _resample_ohlcv(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    minutes = _parse_timeframe_to_minutes(timeframe)
    if minutes <= 1:
        return df

    rule = f"{minutes}min"
    agg: Dict[str, Any] = {"open": "first", "high": "max", "low": "min", "close": "last"}
    if "volume" in df.columns:
        agg["volume"] = "sum"
    return df.resample(rule).agg(agg).dropna(subset=["open", "high", "low", "close"])


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Trading Bot Comparison CLI")
    p.add_argument("--bots", required=True, help="Comma-separated bot list or 'all'")
    p.add_argument("--data-path", required=True, type=str, help="Parquet OHLCV file")
    p.add_argument("--symbol", default="MNQ", help="Symbol label (metadata only)")
    p.add_argument("--timeframe", default="5m", help="Target timeframe (resamples input)")
    p.add_argument("--tick-value", type=float, default=2.0)
    p.add_argument("--out-dir", type=str, default="data/reports")
    p.add_argument("--rank-by", choices=["total_pnl", "win_rate", "profit_factor"], default="total_pnl")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    bots = ALL_BOTS if str(args.bots).strip().lower() == "all" else [b.strip() for b in str(args.bots).split(",") if b.strip()]
    for b in bots:
        if b not in ALL_BOTS:
            raise SystemExit(f"Unknown bot: {b}. Allowed: {ALL_BOTS} or 'all'")

    df = _resample_ohlcv(_load_ohlcv(Path(args.data_path)), args.timeframe)

    results: List[Dict[str, Any]] = []
    for bot_name in bots:
        cfg = BotConfig(
            name=bot_name,
            description=f"Compare {bot_name}",
            symbol=str(args.symbol),
            timeframe=str(args.timeframe),
            enable_alerts=False,
        )
        bot = create_bot(bot_name, cfg)
        r = backtest_trading_bot(bot=bot, df=df, tick_value=float(args.tick_value))
        results.append(
            {
                "bot": bot_name,
                "total_trades": int(r.total_trades),
                "win_rate": float(r.win_rate),
                "total_pnl": float(r.total_pnl),
                "profit_factor": float(r.profit_factor),
                "max_drawdown": float(r.max_drawdown),
            }
        )

    results_sorted = sorted(results, key=lambda x: x.get(args.rank_by) or 0.0, reverse=True)
    report = {
        "symbol": args.symbol,
        "timeframe": args.timeframe,
        "rank_by": args.rank_by,
        "bots": results_sorted,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    report_path = out_dir / f"compare_trading_bots_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    report_path.write_text(json.dumps(report, indent=2))

    print(json.dumps(report, indent=2))
    print(f"\nSaved report: {report_path}")


if __name__ == "__main__":
    main()

