#!/usr/bin/env python3
"""
PearlAlgo Backtest Analyzer

Produces detailed session-aware analysis from backtest results JSON.
Outputs as both terminal table and JSON for cron consumption.

Usage:
    python scripts/backtesting/analyze_backtest.py /tmp/test_bt.json
    python scripts/backtesting/analyze_backtest.py /tmp/test_bt.json --json-out data/backtest/latest_analysis.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Session classification (ET-based)
# ---------------------------------------------------------------------------

SESSION_DEFS = {
    "overnight":  (18, 4),    # 6PM - 4AM ET
    "premarket":  (4, 6),     # 4AM - 6AM ET
    "rth_morning": (6, 10),   # 6AM - 10AM ET (includes open)
    "midday":     (10, 14),   # 10AM - 2PM ET
    "afternoon":  (14, 16),   # 2PM - 4PM ET
    "evening":    (16, 18),   # 4PM - 6PM ET
}


def classify_session(ts: pd.Timestamp) -> str:
    """Classify a UTC timestamp into a trading session (ET-based)."""
    try:
        import zoneinfo
        et = zoneinfo.ZoneInfo("America/New_York")
    except ImportError:
        import pytz
        et = pytz.timezone("America/New_York")
    et_dt = ts.astimezone(et) if ts.tzinfo else ts.tz_localize("UTC").astimezone(et)
    hour = et_dt.hour
    for session_name, (start, end) in SESSION_DEFS.items():
        if start > end:  # overnight wraps
            if hour >= start or hour < end:
                return session_name
        elif start <= hour < end:
            return session_name
    return "other"


def classify_confidence_bucket(conf: float) -> str:
    """Classify confidence into buckets."""
    if conf < 0.5:
        return "0.40-0.50"
    elif conf < 0.6:
        return "0.50-0.60"
    elif conf < 0.7:
        return "0.60-0.70"
    else:
        return "0.70+"


def extract_regime(reason: str) -> str:
    """Extract regime from trade reason string if present."""
    reason_lower = reason.lower()
    for regime in ["trending_up", "trending_down", "ranging", "volatile"]:
        if regime in reason_lower:
            return regime
    return "unknown"


# ---------------------------------------------------------------------------
# Analysis functions
# ---------------------------------------------------------------------------

def analyze_by_session(df: pd.DataFrame) -> Dict[str, Any]:
    """P&L breakdown by session."""
    results = {}
    for session in df["session"].unique():
        sdf = df[df["session"] == session]
        wins = sdf[sdf["pnl_dollars"] > 0]
        results[session] = {
            "trades": len(sdf),
            "win_rate": round(len(wins) / len(sdf), 4) if len(sdf) > 0 else 0,
            "total_pnl": round(float(sdf["pnl_dollars"].sum()), 2),
            "avg_pnl": round(float(sdf["pnl_dollars"].mean()), 2),
        }
    return dict(sorted(results.items(), key=lambda x: x[1]["total_pnl"], reverse=True))


def analyze_by_direction_session(df: pd.DataFrame) -> Dict[str, Any]:
    """P&L by direction x session."""
    results = {}
    for direction in ["long", "short"]:
        ddf = df[df["direction"] == direction]
        for session in ddf["session"].unique():
            sdf = ddf[ddf["session"] == session]
            wins = sdf[sdf["pnl_dollars"] > 0]
            key = f"{direction}_{session}"
            results[key] = {
                "direction": direction,
                "session": session,
                "trades": len(sdf),
                "win_rate": round(len(wins) / len(sdf), 4) if len(sdf) > 0 else 0,
                "total_pnl": round(float(sdf["pnl_dollars"].sum()), 2),
            }
    return dict(sorted(results.items(), key=lambda x: x[1]["total_pnl"], reverse=True))


def analyze_by_regime(df: pd.DataFrame) -> Dict[str, Any]:
    """P&L by regime at entry."""
    results = {}
    for regime in df["regime"].unique():
        rdf = df[df["regime"] == regime]
        wins = rdf[rdf["pnl_dollars"] > 0]
        results[regime] = {
            "trades": len(rdf),
            "win_rate": round(len(wins) / len(rdf), 4) if len(rdf) > 0 else 0,
            "total_pnl": round(float(rdf["pnl_dollars"].sum()), 2),
            "avg_pnl": round(float(rdf["pnl_dollars"].mean()), 2),
        }
    return dict(sorted(results.items(), key=lambda x: x[1]["total_pnl"], reverse=True))


def analyze_by_confidence(df: pd.DataFrame) -> Dict[str, Any]:
    """P&L by confidence bucket."""
    results = {}
    for bucket in df["confidence_bucket"].unique():
        bdf = df[df["confidence_bucket"] == bucket]
        wins = bdf[bdf["pnl_dollars"] > 0]
        results[bucket] = {
            "trades": len(bdf),
            "win_rate": round(len(wins) / len(bdf), 4) if len(bdf) > 0 else 0,
            "total_pnl": round(float(bdf["pnl_dollars"].sum()), 2),
            "avg_pnl": round(float(bdf["pnl_dollars"].mean()), 2),
        }
    return dict(sorted(results.items()))


def analyze_mfe_mae(df: pd.DataFrame) -> Dict[str, Any]:
    """MFE/MAE analysis: are stops too tight? Leaving money on table?"""
    winners = df[df["pnl_dollars"] > 0]
    losers = df[df["pnl_dollars"] < 0]

    result: Dict[str, Any] = {
        "avg_mfe": round(float(df["mfe_points"].mean()), 2),
        "avg_mae": round(float(df["mae_points"].mean()), 2),
    }

    if len(winners) > 0:
        giveback = winners["mfe_points"] - winners["pnl_points"]
        result["winner_avg_mfe"] = round(float(winners["mfe_points"].mean()), 2)
        result["winner_avg_giveback"] = round(float(giveback.mean()), 2)
        result["winner_giveback_pct"] = round(
            float(giveback.mean() / winners["mfe_points"].mean()) * 100, 1
        ) if winners["mfe_points"].mean() > 0 else 0
        result["stops_too_tight_signal"] = result["winner_giveback_pct"] > 40

    if len(losers) > 0:
        result["loser_avg_mae"] = round(float(losers["mae_points"].mean()), 2)
        result["loser_avg_mfe"] = round(float(losers["mfe_points"].mean()), 2)
        # If losers had significant MFE, TP might be too far
        result["losers_had_profit_opportunity"] = float(losers["mfe_points"].mean()) > 0
        result["loser_mfe_vs_mae_ratio"] = round(
            float(losers["mfe_points"].mean() / losers["mae_points"].mean()), 2
        ) if losers["mae_points"].mean() > 0 else 0

    return result


def analyze_rolling_win_rate(df: pd.DataFrame, window: int = 20) -> List[Dict]:
    """Rolling win rate over time to detect performance degradation."""
    if len(df) < window:
        return []
    is_win = (df["pnl_dollars"] > 0).astype(float)
    rolling_wr = is_win.rolling(window).mean()
    snapshots = []
    for i in range(window - 1, len(df), max(1, len(df) // 20)):
        snapshots.append({
            "trade_index": int(i),
            "entry_time": str(df.iloc[i].get("entry_time", "")),
            "rolling_win_rate": round(float(rolling_wr.iloc[i]), 4) if not pd.isna(rolling_wr.iloc[i]) else None,
        })
    return snapshots


def analyze_optimal_confidence(df: pd.DataFrame) -> Dict[str, Any]:
    """Find the confidence threshold that maximizes P&L."""
    thresholds = [0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75]
    best_pnl = float("-inf")
    best_threshold = 0.40
    threshold_results = []

    for t in thresholds:
        subset = df[df["confidence"] >= t]
        if len(subset) == 0:
            continue
        wins = subset[subset["pnl_dollars"] > 0]
        pnl = float(subset["pnl_dollars"].sum())
        entry = {
            "threshold": t,
            "trades": len(subset),
            "win_rate": round(len(wins) / len(subset), 4),
            "total_pnl": round(pnl, 2),
            "avg_pnl": round(float(subset["pnl_dollars"].mean()), 2),
        }
        threshold_results.append(entry)
        if pnl > best_pnl:
            best_pnl = pnl
            best_threshold = t

    return {
        "optimal_threshold": best_threshold,
        "optimal_pnl": round(best_pnl, 2),
        "thresholds": threshold_results,
    }


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------

def run_analysis(results_path: str) -> Dict[str, Any]:
    """Run full analysis on backtest results JSON."""
    with open(results_path) as f:
        data = json.load(f)

    trades = data.get("trades", data) if isinstance(data, dict) else data
    if isinstance(data, dict) and "trades" in data:
        trades = data["trades"]
    elif isinstance(data, list):
        trades = data

    if not trades:
        return {"error": "No trades found in results file"}

    df = pd.DataFrame(trades)

    # Parse timestamps
    if "entry_time" in df.columns:
        df["entry_time"] = pd.to_datetime(df["entry_time"], utc=True)

    # Add derived columns
    df["session"] = df["entry_time"].apply(classify_session) if "entry_time" in df.columns else "unknown"
    df["confidence_bucket"] = df["confidence"].apply(classify_confidence_bucket) if "confidence" in df.columns else "unknown"
    df["regime"] = df["reason"].apply(extract_regime) if "reason" in df.columns else "unknown"

    # Also check for explicit regime field
    if "regime" in [c for c in df.columns if c != "regime"]:
        pass  # already set from reason

    analysis: Dict[str, Any] = {
        "generated_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "total_trades": len(df),
        "date_range": {
            "start": str(df["entry_time"].min()) if "entry_time" in df.columns else None,
            "end": str(df["entry_time"].max()) if "entry_time" in df.columns else None,
        },
    }

    # Core metrics
    total_pnl = float(df["pnl_dollars"].sum())
    wins = df[df["pnl_dollars"] > 0]
    analysis["summary"] = {
        "total_pnl": round(total_pnl, 2),
        "win_rate": round(len(wins) / len(df), 4) if len(df) > 0 else 0,
        "avg_trade_pnl": round(total_pnl / len(df), 2) if len(df) > 0 else 0,
    }

    analysis["by_session"] = analyze_by_session(df)
    analysis["by_direction_session"] = analyze_by_direction_session(df)
    analysis["by_regime"] = analyze_by_regime(df)
    analysis["by_confidence"] = analyze_by_confidence(df)
    analysis["mfe_mae"] = analyze_mfe_mae(df)
    analysis["rolling_win_rate"] = analyze_rolling_win_rate(df)
    analysis["optimal_confidence"] = analyze_optimal_confidence(df)

    return analysis


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def print_analysis(analysis: Dict[str, Any]) -> None:
    """Pretty-print analysis to terminal."""
    print(f"\n{'='*70}")
    print(f"  PearlAlgo Backtest Analysis")
    print(f"{'='*70}")

    if "error" in analysis:
        print(f"  ERROR: {analysis['error']}")
        return

    s = analysis.get("summary", {})
    print(f"  Total Trades: {analysis['total_trades']}")
    print(f"  Total PnL:    ${s.get('total_pnl', 0):,.2f}")
    print(f"  Win Rate:     {s.get('win_rate', 0):.1%}")
    print(f"  Avg Trade:    ${s.get('avg_trade_pnl', 0):,.2f}")

    dr = analysis.get("date_range", {})
    if dr.get("start"):
        print(f"  Date Range:   {dr['start']} to {dr['end']}")

    # By Session
    by_session = analysis.get("by_session", {})
    if by_session:
        print(f"\n  {'Session':<15} {'Trades':>7} {'WR':>7} {'PnL':>12} {'Avg':>10}")
        print(f"  {'-'*15} {'-'*7} {'-'*7} {'-'*12} {'-'*10}")
        for sess, st in by_session.items():
            print(f"  {sess:<15} {st['trades']:>7} {st['win_rate']:>6.1%} "
                  f"${st['total_pnl']:>10,.2f} ${st['avg_pnl']:>8,.2f}")

    # By Direction x Session
    by_ds = analysis.get("by_direction_session", {})
    if by_ds:
        print(f"\n  {'Dir+Session':<25} {'Trades':>7} {'WR':>7} {'PnL':>12}")
        print(f"  {'-'*25} {'-'*7} {'-'*7} {'-'*12}")
        for key, st in by_ds.items():
            print(f"  {key:<25} {st['trades']:>7} {st['win_rate']:>6.1%} "
                  f"${st['total_pnl']:>10,.2f}")

    # By Regime
    by_regime = analysis.get("by_regime", {})
    if by_regime:
        print(f"\n  {'Regime':<15} {'Trades':>7} {'WR':>7} {'PnL':>12} {'Avg':>10}")
        print(f"  {'-'*15} {'-'*7} {'-'*7} {'-'*12} {'-'*10}")
        for regime, st in by_regime.items():
            print(f"  {regime:<15} {st['trades']:>7} {st['win_rate']:>6.1%} "
                  f"${st['total_pnl']:>10,.2f} ${st['avg_pnl']:>8,.2f}")

    # By Confidence
    by_conf = analysis.get("by_confidence", {})
    if by_conf:
        print(f"\n  {'Confidence':<12} {'Trades':>7} {'WR':>7} {'PnL':>12} {'Avg':>10}")
        print(f"  {'-'*12} {'-'*7} {'-'*7} {'-'*12} {'-'*10}")
        for bucket, st in by_conf.items():
            print(f"  {bucket:<12} {st['trades']:>7} {st['win_rate']:>6.1%} "
                  f"${st['total_pnl']:>10,.2f} ${st['avg_pnl']:>8,.2f}")

    # MFE/MAE
    mfe_mae = analysis.get("mfe_mae", {})
    if mfe_mae:
        print(f"\n  MFE/MAE Analysis:")
        print(f"    Avg MFE:              {mfe_mae.get('avg_mfe', 0):.2f} pts")
        print(f"    Avg MAE:              {mfe_mae.get('avg_mae', 0):.2f} pts")
        if "winner_avg_giveback" in mfe_mae:
            print(f"    Winner Giveback:      {mfe_mae['winner_avg_giveback']:.2f} pts ({mfe_mae.get('winner_giveback_pct', 0):.0f}%)")
        if mfe_mae.get("stops_too_tight_signal"):
            print(f"    ** SIGNAL: Stops may be too tight (>40% giveback)")
        if mfe_mae.get("losers_had_profit_opportunity"):
            print(f"    ** Losers had avg MFE of {mfe_mae.get('loser_avg_mfe', 0):.2f} pts (profit was available)")

    # Optimal confidence
    opt = analysis.get("optimal_confidence", {})
    if opt and opt.get("thresholds"):
        print(f"\n  Optimal Confidence Threshold:")
        print(f"    Best: {opt['optimal_threshold']} -> ${opt['optimal_pnl']:,.2f}")
        print(f"    {'Threshold':>10} {'Trades':>7} {'WR':>7} {'PnL':>12}")
        print(f"    {'-'*10} {'-'*7} {'-'*7} {'-'*12}")
        for t in opt["thresholds"]:
            marker = " <--" if t["threshold"] == opt["optimal_threshold"] else ""
            print(f"    {t['threshold']:>10.2f} {t['trades']:>7} {t['win_rate']:>6.1%} "
                  f"${t['total_pnl']:>10,.2f}{marker}")

    print(f"\n{'='*70}\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="PearlAlgo Backtest Analyzer")
    parser.add_argument("results_file", help="Path to backtest results JSON file")
    parser.add_argument("--json-out", type=str, help="Write analysis to JSON file")
    args = parser.parse_args()

    if not Path(args.results_file).exists():
        print(f"ERROR: File not found: {args.results_file}")
        sys.exit(1)

    analysis = run_analysis(args.results_file)
    print_analysis(analysis)

    if args.json_out:
        out_path = Path(args.json_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w") as f:
            json.dump(analysis, f, indent=2, default=str)
        print(f"  Analysis saved to {args.json_out}")


if __name__ == "__main__":
    main()
