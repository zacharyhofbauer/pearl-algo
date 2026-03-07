#!/usr/bin/env python3
"""
PearlAlgo Backtester

Runs generate_signals() over historical 1-min bars and simulates bracket exits
(SL/TP) to produce performance metrics without live trading.

Data sources (in priority order):
1. CSV files in data/backtest/
2. Cached candle JSON files in data/

Usage:
    # Basic backtest with cached data
    python scripts/backtesting/backtest_engine.py --days 7

    # Override strategy parameters
    python scripts/backtesting/backtest_engine.py --days 7 --ema-fast 9 --ema-slow 21

    # Parameter sweep
    python scripts/backtesting/backtest_engine.py --days 7 --sweep \
        --ema-fast 5,7,9 --ema-slow 13,17,21 --sl-atr 2.5,3.0,3.5,4.0

    # Output to JSON
    python scripts/backtesting/backtest_engine.py --days 7 --output results.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from itertools import product
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from pearlalgo.trading_bots.pearl_bot_auto import generate_signals, CONFIG


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_bars_from_csv(csv_path: Path) -> pd.DataFrame:
    """Load bars from a CSV file with columns: timestamp, open, high, low, close, volume."""
    df = pd.read_csv(csv_path)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df


def load_bars_from_cache(cache_path: Path) -> pd.DataFrame:
    """Load bars from PearlAlgo candle cache JSON format."""
    with open(cache_path) as f:
        data = json.load(f)

    candles = data.get("candles", data) if isinstance(data, dict) else data
    if not candles:
        return pd.DataFrame()

    rows = []
    for c in candles:
        ts = c.get("time") or c.get("timestamp")
        if isinstance(ts, (int, float)):
            ts = datetime.fromtimestamp(ts, tz=timezone.utc)
        rows.append({
            "timestamp": ts,
            "open": float(c["open"]),
            "high": float(c["high"]),
            "low": float(c["low"]),
            "close": float(c["close"]),
            "volume": float(c.get("volume", 0)),
        })

    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df


def load_bars(days: int = 7, csv_dir: Optional[Path] = None) -> pd.DataFrame:
    """Load bars from available sources, filtered to the last N days."""
    data_dir = PROJECT_ROOT / "data"
    backtest_dir = csv_dir or (data_dir / "backtest")

    frames: List[pd.DataFrame] = []

    # Try CSVs first
    if backtest_dir.exists():
        for csv_file in sorted(backtest_dir.glob("MNQ_1m_*.csv")):
            try:
                frames.append(load_bars_from_csv(csv_file))
            except Exception as e:
                print(f"  Warning: Failed to load {csv_file.name}: {e}")

    # Fall back to cache files (try all available cache files)
    if not frames:
        for cache_name in ["candle_cache_MNQ_1m_500.json", "candle_cache_MNQ_1m_200.json",
                           "candle_cache_MNQ_5m_500.json"]:
            cache_file = data_dir / cache_name
            if cache_file.exists():
                try:
                    frames.append(load_bars_from_cache(cache_file))
                    print(f"  Loaded {len(frames[-1])} bars from {cache_name}")
                except Exception as e:
                    print(f"  Warning: Failed to load {cache_name}: {e}")

    if not frames:
        print("ERROR: No bar data found. Place CSVs in data/backtest/ or ensure cache exists.")
        sys.exit(1)

    df = pd.concat(frames, ignore_index=True)
    df = df.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)

    # Filter to last N days
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    df = df[df["timestamp"] >= cutoff].reset_index(drop=True)

    if df.empty:
        print(f"ERROR: No bars found within last {days} days. Available range: "
              f"{frames[0]['timestamp'].min()} to {frames[0]['timestamp'].max()}")
        sys.exit(1)

    return df


# ---------------------------------------------------------------------------
# Backtest engine
# ---------------------------------------------------------------------------

def run_backtest(
    bars_df: pd.DataFrame,
    config_overrides: Optional[Dict] = None,
    trailing_config: Optional[Dict] = None,
    window_size: int = 200,
    point_value: float = 2.0,
) -> List[Dict]:
    """
    Run backtest over bars using generate_signals().

    For each bar, we call generate_signals() with a rolling window. When a
    signal is emitted, we track it as a virtual trade and check subsequent
    bars for SL/TP hits.

    Args:
        bars_df: DataFrame with timestamp, open, high, low, close, volume
        config_overrides: Dict of config keys to override (e.g. ema_fast, sl_atr)
        trailing_config: Optional trailing stop config (phases list)
        window_size: Rolling window size for generate_signals()
        point_value: Dollar value per point (MNQ = $2)

    Returns:
        List of trade result dicts
    """
    # Build config
    cfg = dict(CONFIG)
    if config_overrides:
        cfg.update(config_overrides)

    results: List[Dict] = []
    open_trades: List[Dict] = []  # Active trades awaiting exit
    signal_cooldown: Dict[str, datetime] = {}  # Prevent duplicate signals
    cooldown_seconds = 60

    total_bars = len(bars_df)
    last_progress = 0

    for i in range(window_size, total_bars):
        # Progress indicator
        pct = int((i / total_bars) * 100)
        if pct >= last_progress + 10:
            last_progress = pct
            print(f"  Progress: {pct}% ({i}/{total_bars} bars, {len(results)} trades)")

        current_bar = bars_df.iloc[i]
        bar_high = float(current_bar["high"])
        bar_low = float(current_bar["low"])
        bar_time = current_bar["timestamp"]

        # Check open trades for exits
        still_open = []
        for trade in open_trades:
            direction = trade["direction"]
            stop = trade["stop_loss"]
            target = trade["take_profit"]
            entry_px = trade["entry_price"]

            # Trailing stop update
            if trailing_config and trailing_config.get("enabled"):
                best_key = "best_price"
                if best_key not in trade:
                    trade[best_key] = entry_px
                if direction == "long":
                    trade[best_key] = max(trade[best_key], bar_high)
                    favorable_move = trade[best_key] - entry_px
                else:
                    trade[best_key] = min(trade[best_key], bar_low)
                    favorable_move = entry_px - trade[best_key]

                atr = trade.get("atr", 1.0)
                for phase in reversed(trailing_config.get("phases", [])):
                    if favorable_move >= phase["activation_atr"] * atr:
                        if phase["trail_atr"] == 0.0:
                            # Breakeven
                            new_stop = entry_px + (0.25 if direction == "long" else -0.25)
                        else:
                            trail_dist = phase["trail_atr"] * atr
                            if direction == "long":
                                new_stop = trade[best_key] - trail_dist
                            else:
                                new_stop = trade[best_key] + trail_dist
                        # Ratchet: only move stop in favorable direction
                        if direction == "long" and new_stop > stop:
                            stop = new_stop
                            trade["stop_loss"] = stop
                            trade["trailing_phase"] = phase["name"]
                        elif direction == "short" and new_stop < stop:
                            stop = new_stop
                            trade["stop_loss"] = stop
                            trade["trailing_phase"] = phase["name"]
                        break

            # Check SL/TP hits
            if direction == "long":
                hit_tp = bar_high >= target
                hit_sl = bar_low <= stop
            else:
                hit_tp = bar_low <= target
                hit_sl = bar_high >= stop

            if hit_tp or hit_sl:
                if hit_sl and hit_tp:
                    exit_reason = "stop_loss"  # Conservative tiebreak
                    exit_price = stop
                elif hit_sl:
                    exit_reason = "stop_loss"
                    exit_price = stop
                else:
                    exit_reason = "take_profit"
                    exit_price = target

                # Compute PnL
                if direction == "long":
                    pnl_points = exit_price - entry_px
                else:
                    pnl_points = entry_px - exit_price
                pnl_dollars = pnl_points * point_value

                # MFE/MAE from tracked best/worst
                max_px = trade.get("max_price", entry_px)
                min_px = trade.get("min_price", entry_px)
                if direction == "long":
                    mfe = max_px - entry_px
                    mae = entry_px - min_px
                else:
                    mfe = entry_px - min_px
                    mae = max_px - entry_px

                results.append({
                    "entry_time": trade["entry_time"].isoformat(),
                    "exit_time": bar_time.isoformat() if hasattr(bar_time, "isoformat") else str(bar_time),
                    "direction": direction,
                    "entry_price": entry_px,
                    "exit_price": exit_price,
                    "stop_loss": trade["original_stop"],
                    "take_profit": target,
                    "exit_reason": exit_reason,
                    "pnl_points": round(pnl_points, 4),
                    "pnl_dollars": round(pnl_dollars, 2),
                    "mfe_points": round(mfe, 4),
                    "mae_points": round(mae, 4),
                    "confidence": trade.get("confidence", 0),
                    "reason": trade.get("reason", ""),
                    "trailing_phase": trade.get("trailing_phase"),
                    "hold_bars": i - trade["entry_bar_idx"],
                })
            else:
                # Update MFE/MAE tracking
                trade["max_price"] = max(trade.get("max_price", entry_px), bar_high)
                trade["min_price"] = min(trade.get("min_price", entry_px), bar_low)
                still_open.append(trade)

        open_trades = still_open

        # Generate signals on rolling window
        window = bars_df.iloc[max(0, i - window_size):i + 1].copy()
        try:
            bar_dt = pd.Timestamp(bar_time).to_pydatetime()
            if bar_dt.tzinfo is None:
                bar_dt = bar_dt.replace(tzinfo=timezone.utc)
            signals = generate_signals(window, config=cfg, current_time=bar_dt)
        except Exception:
            continue

        for sig in signals:
            direction = sig["direction"]

            # Cooldown: skip if we recently generated a signal in this direction
            cd_key = direction
            last_sig_time = signal_cooldown.get(cd_key)
            if last_sig_time and (bar_time - last_sig_time).total_seconds() < cooldown_seconds:
                continue

            # Skip if we already have an open trade in this direction
            if any(t["direction"] == direction for t in open_trades):
                continue

            signal_cooldown[cd_key] = bar_time

            # Compute ATR for trailing stop
            atr_val = 1.0
            try:
                if len(window) >= 14:
                    tr = pd.concat([
                        window["high"] - window["low"],
                        (window["high"] - window["close"].shift(1)).abs(),
                        (window["low"] - window["close"].shift(1)).abs(),
                    ], axis=1).max(axis=1)
                    atr_val = float(tr.iloc[-14:].mean())
            except Exception:
                pass

            open_trades.append({
                "direction": direction,
                "entry_price": float(sig["entry_price"]),
                "stop_loss": float(sig["stop_loss"]),
                "take_profit": float(sig["take_profit"]),
                "original_stop": float(sig["stop_loss"]),
                "confidence": float(sig.get("confidence", 0)),
                "reason": sig.get("reason", ""),
                "entry_time": bar_time,
                "entry_bar_idx": i,
                "max_price": float(sig["entry_price"]),
                "min_price": float(sig["entry_price"]),
                "atr": atr_val,
            })

    # Close any remaining open trades at last bar's close
    if open_trades:
        last_close = float(bars_df.iloc[-1]["close"])
        last_time = bars_df.iloc[-1]["timestamp"]
        for trade in open_trades:
            direction = trade["direction"]
            entry_px = trade["entry_price"]
            if direction == "long":
                pnl_points = last_close - entry_px
            else:
                pnl_points = entry_px - last_close

            max_px = trade.get("max_price", entry_px)
            min_px = trade.get("min_price", entry_px)
            if direction == "long":
                mfe = max_px - entry_px
                mae = entry_px - min_px
            else:
                mfe = entry_px - min_px
                mae = max_px - entry_px

            results.append({
                "entry_time": trade["entry_time"].isoformat() if hasattr(trade["entry_time"], "isoformat") else str(trade["entry_time"]),
                "exit_time": last_time.isoformat() if hasattr(last_time, "isoformat") else str(last_time),
                "direction": direction,
                "entry_price": entry_px,
                "exit_price": last_close,
                "stop_loss": trade["original_stop"],
                "take_profit": trade["take_profit"],
                "exit_reason": "end_of_data",
                "pnl_points": round(pnl_points, 4),
                "pnl_dollars": round(pnl_points * point_value, 2),
                "mfe_points": round(mfe, 4),
                "mae_points": round(mae, 4),
                "confidence": trade.get("confidence", 0),
                "reason": trade.get("reason", ""),
                "trailing_phase": trade.get("trailing_phase"),
                "hold_bars": len(bars_df) - 1 - trade["entry_bar_idx"],
            })

    return results


# ---------------------------------------------------------------------------
# Metrics computation
# ---------------------------------------------------------------------------

def compute_metrics(results: List[Dict]) -> Dict[str, Any]:
    """Compute comprehensive backtest metrics from trade results."""
    if not results:
        return {"total_trades": 0, "error": "No trades generated"}

    df = pd.DataFrame(results)
    total = len(df)
    winners = df[df["pnl_dollars"] > 0]
    losers = df[df["pnl_dollars"] < 0]
    breakeven = df[df["pnl_dollars"] == 0]

    win_count = len(winners)
    loss_count = len(losers)
    win_rate = win_count / total if total > 0 else 0

    total_pnl = float(df["pnl_dollars"].sum())
    avg_win = float(winners["pnl_dollars"].mean()) if len(winners) > 0 else 0
    avg_loss = float(losers["pnl_dollars"].mean()) if len(losers) > 0 else 0
    profit_factor = abs(float(winners["pnl_dollars"].sum()) / float(losers["pnl_dollars"].sum())) if len(losers) > 0 and losers["pnl_dollars"].sum() != 0 else float("inf")

    # Max drawdown
    cumulative = df["pnl_dollars"].cumsum()
    running_max = cumulative.cummax()
    drawdown = cumulative - running_max
    max_drawdown = float(drawdown.min())

    # Sharpe (rough: assumes daily-ish returns)
    if df["pnl_dollars"].std() > 0:
        sharpe = float(df["pnl_dollars"].mean() / df["pnl_dollars"].std()) * (252 ** 0.5)
    else:
        sharpe = 0.0

    # MFE/MAE analysis
    avg_mfe = float(df["mfe_points"].mean())
    avg_mae = float(df["mae_points"].mean())
    avg_winner_mfe = float(winners["mfe_points"].mean()) if len(winners) > 0 else 0
    avg_loser_mae = float(losers["mae_points"].mean()) if len(losers) > 0 else 0

    # Giveback: how much MFE winners lose before exit
    if len(winners) > 0:
        giveback = float((winners["mfe_points"] - winners["pnl_points"]).mean())
    else:
        giveback = 0

    # By direction
    by_direction = {}
    for d in ["long", "short"]:
        ddf = df[df["direction"] == d]
        if len(ddf) > 0:
            dw = ddf[ddf["pnl_dollars"] > 0]
            by_direction[d] = {
                "trades": len(ddf),
                "win_rate": round(len(dw) / len(ddf), 4),
                "total_pnl": round(float(ddf["pnl_dollars"].sum()), 2),
                "avg_pnl": round(float(ddf["pnl_dollars"].mean()), 2),
            }

    # By exit reason
    by_exit = {}
    for reason in df["exit_reason"].unique():
        rdf = df[df["exit_reason"] == reason]
        by_exit[reason] = {
            "count": len(rdf),
            "total_pnl": round(float(rdf["pnl_dollars"].sum()), 2),
        }

    metrics = {
        "total_trades": total,
        "winners": win_count,
        "losers": loss_count,
        "breakeven": len(breakeven),
        "win_rate": round(win_rate, 4),
        "total_pnl": round(total_pnl, 2),
        "avg_trade_pnl": round(total_pnl / total, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "profit_factor": round(profit_factor, 4) if profit_factor != float("inf") else "inf",
        "max_drawdown": round(max_drawdown, 2),
        "sharpe_approx": round(sharpe, 4),
        "avg_mfe_points": round(avg_mfe, 2),
        "avg_mae_points": round(avg_mae, 2),
        "avg_winner_mfe": round(avg_winner_mfe, 2),
        "avg_loser_mae": round(avg_loser_mae, 2),
        "avg_winner_giveback": round(giveback, 2),
        "avg_hold_bars": round(float(df["hold_bars"].mean()), 1),
        "by_direction": by_direction,
        "by_exit_reason": by_exit,
    }

    return metrics


# ---------------------------------------------------------------------------
# Parameter sweep
# ---------------------------------------------------------------------------

def run_parameter_sweep(
    bars_df: pd.DataFrame,
    param_grid: Dict[str, List],
    trailing_config: Optional[Dict] = None,
) -> List[Dict]:
    """Run backtest across a grid of parameter combinations."""
    keys = list(param_grid.keys())
    values = list(param_grid.values())
    combos = list(product(*values))

    print(f"\n  Parameter sweep: {len(combos)} combinations")
    sweep_results = []

    for idx, combo in enumerate(combos, 1):
        overrides = dict(zip(keys, combo))
        label = ", ".join(f"{k}={v}" for k, v in overrides.items())
        print(f"\n  [{idx}/{len(combos)}] {label}")

        results = run_backtest(bars_df, config_overrides=overrides, trailing_config=trailing_config)
        metrics = compute_metrics(results)
        metrics["params"] = overrides
        metrics["label"] = label
        sweep_results.append(metrics)

    # Sort by total PnL descending
    sweep_results.sort(key=lambda x: x.get("total_pnl", 0), reverse=True)
    return sweep_results


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def print_metrics(metrics: Dict, title: str = "Backtest Results") -> None:
    """Pretty-print backtest metrics."""
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

    if metrics.get("total_trades", 0) == 0:
        print("  No trades generated.")
        return

    print(f"  Total Trades:     {metrics['total_trades']}")
    print(f"  Win Rate:         {metrics['win_rate']:.1%}")
    print(f"  Total PnL:        ${metrics['total_pnl']:,.2f}")
    print(f"  Avg Trade:        ${metrics['avg_trade_pnl']:,.2f}")
    print(f"  Avg Win:          ${metrics['avg_win']:,.2f}")
    print(f"  Avg Loss:         ${metrics['avg_loss']:,.2f}")
    print(f"  Profit Factor:    {metrics['profit_factor']}")
    print(f"  Max Drawdown:     ${metrics['max_drawdown']:,.2f}")
    print(f"  Sharpe (approx):  {metrics['sharpe_approx']:.2f}")
    print(f"  Avg Hold (bars):  {metrics['avg_hold_bars']:.0f}")

    print(f"\n  MFE/MAE Analysis:")
    print(f"    Avg MFE:          {metrics['avg_mfe_points']:.2f} pts")
    print(f"    Avg MAE:          {metrics['avg_mae_points']:.2f} pts")
    print(f"    Winner Avg MFE:   {metrics['avg_winner_mfe']:.2f} pts")
    print(f"    Loser Avg MAE:    {metrics['avg_loser_mae']:.2f} pts")
    print(f"    Winner Giveback:  {metrics['avg_winner_giveback']:.2f} pts")

    if metrics.get("by_direction"):
        print(f"\n  By Direction:")
        for d, stats in metrics["by_direction"].items():
            print(f"    {d.upper():6s}: {stats['trades']} trades, "
                  f"WR={stats['win_rate']:.1%}, PnL=${stats['total_pnl']:,.2f}")

    if metrics.get("by_exit_reason"):
        print(f"\n  By Exit Reason:")
        for reason, stats in metrics["by_exit_reason"].items():
            print(f"    {reason:15s}: {stats['count']} trades, PnL=${stats['total_pnl']:,.2f}")

    print(f"{'='*60}\n")


def print_sweep_results(sweep_results: List[Dict]) -> None:
    """Print sweep results as a ranked table."""
    print(f"\n{'='*80}")
    print(f"  Parameter Sweep Results (ranked by PnL)")
    print(f"{'='*80}")
    print(f"  {'#':>3}  {'PnL':>10}  {'WR':>6}  {'Trades':>6}  {'PF':>6}  {'MaxDD':>10}  Parameters")
    print(f"  {'-'*3}  {'-'*10}  {'-'*6}  {'-'*6}  {'-'*6}  {'-'*10}  {'-'*30}")

    for i, m in enumerate(sweep_results[:20], 1):
        pf = m.get("profit_factor", 0)
        pf_str = f"{pf:.2f}" if isinstance(pf, (int, float)) else str(pf)
        print(
            f"  {i:>3}  ${m.get('total_pnl', 0):>9,.2f}  "
            f"{m.get('win_rate', 0):>5.1%}  "
            f"{m.get('total_trades', 0):>6}  "
            f"{pf_str:>6}  "
            f"${m.get('max_drawdown', 0):>9,.2f}  "
            f"{m.get('label', '')}"
        )

    print(f"{'='*80}\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_list(value: str) -> List[float]:
    """Parse comma-separated values into a list of floats."""
    return [float(v.strip()) for v in value.split(",")]


def main():
    parser = argparse.ArgumentParser(description="PearlAlgo Backtester")
    parser.add_argument("--days", type=int, default=7, help="Days of data to backtest (default: 7)")
    parser.add_argument("--csv-dir", type=str, help="Directory with CSV bar files")
    parser.add_argument("--output", type=str, help="Write results to JSON file")
    parser.add_argument("--sweep", action="store_true", help="Run parameter sweep mode")

    # Strategy parameter overrides
    parser.add_argument("--ema-fast", type=str, default=None, help="EMA fast period (or comma-separated for sweep)")
    parser.add_argument("--ema-slow", type=str, default=None, help="EMA slow period (or comma-separated for sweep)")
    parser.add_argument("--sl-atr", type=str, default=None, help="Stop loss ATR multiplier (or comma-separated)")
    parser.add_argument("--tp-atr", type=str, default=None, help="Take profit ATR multiplier (or comma-separated)")
    parser.add_argument("--min-confidence", type=str, default=None, help="Minimum confidence (or comma-separated)")

    # Trailing stop simulation
    parser.add_argument("--trailing", action="store_true", help="Enable trailing stop simulation")
    parser.add_argument("--trail-be-atr", type=float, default=1.0, help="Breakeven activation ATR (default: 1.0)")
    parser.add_argument("--trail-lock-atr", type=float, default=2.0, help="Lock profit activation ATR (default: 2.0)")
    parser.add_argument("--trail-lock-trail", type=float, default=1.5, help="Lock profit trail ATR (default: 1.5)")
    parser.add_argument("--trail-tight-atr", type=float, default=3.0, help="Tight trail activation ATR (default: 3.0)")
    parser.add_argument("--trail-tight-trail", type=float, default=1.0, help="Tight trail distance ATR (default: 1.0)")

    args = parser.parse_args()

    print(f"\nPearlAlgo Backtester")
    print(f"{'='*40}")

    # Load data
    print(f"\nLoading {args.days} days of bar data...")
    csv_dir = Path(args.csv_dir) if args.csv_dir else None
    bars_df = load_bars(days=args.days, csv_dir=csv_dir)
    print(f"  Loaded {len(bars_df)} bars")
    print(f"  Range: {bars_df['timestamp'].iloc[0]} to {bars_df['timestamp'].iloc[-1]}")

    # Build trailing config
    trailing_config = None
    if args.trailing:
        trailing_config = {
            "enabled": True,
            "phases": [
                {"name": "breakeven", "activation_atr": args.trail_be_atr, "trail_atr": 0.0},
                {"name": "lock_profit", "activation_atr": args.trail_lock_atr, "trail_atr": args.trail_lock_trail},
                {"name": "tight_trail", "activation_atr": args.trail_tight_atr, "trail_atr": args.trail_tight_trail},
            ],
        }
        print(f"  Trailing stops: ENABLED")

    start = time.time()

    if args.sweep:
        # Build parameter grid
        param_grid: Dict[str, List] = {}
        if args.ema_fast:
            param_grid["ema_fast"] = [int(v) for v in parse_list(args.ema_fast)]
        if args.ema_slow:
            param_grid["ema_slow"] = [int(v) for v in parse_list(args.ema_slow)]
        if args.sl_atr:
            param_grid["stop_loss_atr_mult"] = parse_list(args.sl_atr)
        if args.tp_atr:
            param_grid["take_profit_atr_mult"] = parse_list(args.tp_atr)
        if args.min_confidence:
            param_grid["min_confidence"] = parse_list(args.min_confidence)

        if not param_grid:
            print("ERROR: --sweep requires at least one parameter with multiple values")
            sys.exit(1)

        sweep_results = run_parameter_sweep(bars_df, param_grid, trailing_config=trailing_config)
        print_sweep_results(sweep_results)

        elapsed = time.time() - start
        print(f"  Sweep completed in {elapsed:.1f}s")

        if args.output:
            with open(args.output, "w") as f:
                json.dump(sweep_results, f, indent=2, default=str)
            print(f"  Results saved to {args.output}")

    else:
        # Single backtest run
        overrides: Dict[str, Any] = {}
        if args.ema_fast:
            overrides["ema_fast"] = int(parse_list(args.ema_fast)[0])
        if args.ema_slow:
            overrides["ema_slow"] = int(parse_list(args.ema_slow)[0])
        if args.sl_atr:
            overrides["stop_loss_atr_mult"] = parse_list(args.sl_atr)[0]
        if args.tp_atr:
            overrides["take_profit_atr_mult"] = parse_list(args.tp_atr)[0]
        if args.min_confidence:
            overrides["min_confidence"] = parse_list(args.min_confidence)[0]

        if overrides:
            print(f"  Overrides: {overrides}")

        print(f"\nRunning backtest...")
        results = run_backtest(bars_df, config_overrides=overrides, trailing_config=trailing_config)
        metrics = compute_metrics(results)

        elapsed = time.time() - start
        title = "Backtest Results"
        if trailing_config:
            title += " (with trailing stops)"
        print_metrics(metrics, title=title)
        print(f"  Completed in {elapsed:.1f}s")

        if args.output:
            output_data = {"metrics": metrics, "trades": results}
            with open(args.output, "w") as f:
                json.dump(output_data, f, indent=2, default=str)
            print(f"  Results saved to {args.output}")


if __name__ == "__main__":
    main()
