#!/usr/bin/env python3
"""
Run Strategy Variants A/B Test

Runs the same historical data through multiple strategy variants and compares results.
This enables data-driven selection of the best configuration without manual tuning.

Usage:
    python scripts/backtesting/run_variants.py --data-path data/MNQ_1m.parquet
    python scripts/backtesting/run_variants.py --data-path data/NQ_5m.csv --variants default aggressive_scalp
    python scripts/backtesting/run_variants.py --data-path data/MNQ_1m.parquet --start 2025-01-01 --end 2025-01-15

Output:
    - Creates reports/variants_<timestamp>/ folder with:
        - comparison.json: Side-by-side metrics for all variants
        - comparison.csv: Easy Excel import
        - <variant_name>_summary.json: Full backtest result per variant
        - winner.txt: Recommendation of best variant
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from pearlalgo.strategies.nq_intraday.backtest_adapter import (
    BacktestResult,
    run_full_backtest,
)
from pearlalgo.strategies.nq_intraday.config import NQIntradayConfig


@dataclass
class VariantResult:
    """Result from running a single variant."""
    
    variant_name: str
    description: str
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    total_pnl: float
    profit_factor: float
    max_drawdown: float
    sharpe_ratio: float
    avg_win: float
    avg_loss: float
    avg_confidence: float
    total_signals: int
    signals_per_day: float
    
    @classmethod
    def from_backtest(cls, name: str, description: str, result: BacktestResult, days: float) -> "VariantResult":
        return cls(
            variant_name=name,
            description=description,
            total_trades=result.total_trades,
            winning_trades=result.winning_trades,
            losing_trades=result.losing_trades,
            win_rate=result.win_rate,
            total_pnl=result.total_pnl,
            profit_factor=result.profit_factor,
            max_drawdown=result.max_drawdown,
            sharpe_ratio=result.sharpe_ratio,
            avg_win=result.avg_win or 0.0,
            avg_loss=result.avg_loss or 0.0,
            avg_confidence=result.avg_confidence,
            total_signals=result.total_signals,
            signals_per_day=result.total_signals / max(1, days),
        )


def load_data(data_path: Path, start_date: Optional[str], end_date: Optional[str]) -> pd.DataFrame:
    """Load and slice data from file."""
    if data_path.suffix == ".parquet":
        df = pd.read_parquet(data_path)
    elif data_path.suffix == ".csv":
        df = pd.read_csv(data_path, index_col=0, parse_dates=True)
    else:
        raise ValueError(f"Unsupported file format: {data_path.suffix}")
    
    # Ensure datetime index
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)
    
    # Ensure timezone aware (UTC)
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    
    # Slice by date range
    if start_date:
        df = df[df.index >= pd.Timestamp(start_date, tz="UTC")]
    if end_date:
        df = df[df.index <= pd.Timestamp(end_date, tz="UTC")]
    
    return df


def run_variant(
    df: pd.DataFrame,
    variant_name: str,
    variant_cfg: Optional[dict],
    base_config: NQIntradayConfig,
    tick_value: float,
) -> tuple[BacktestResult, NQIntradayConfig]:
    """Run backtest for a single variant."""
    # Create config copy and apply variant
    config = NQIntradayConfig.from_config_file()
    
    if variant_cfg:
        config._apply_variant(variant_cfg)
    
    # Run backtest
    result = run_full_backtest(
        df,
        config=config,
        position_size=config.base_contracts,  # Use dynamic sizing
        tick_value=tick_value,
        slippage_ticks=0.5,
        max_concurrent_trades=1,
        max_contracts=config.max_conf_contracts,
    )
    
    return result, config


def compare_variants(results: List[VariantResult]) -> dict:
    """Compare variants and determine winner."""
    if not results:
        return {"winner": None, "reason": "No results"}
    
    # Scoring: prioritize positive P&L, then profit factor, then Sharpe
    def score(r: VariantResult) -> float:
        # Must be profitable to win
        if r.total_pnl <= 0:
            return r.total_pnl - 100000  # Heavily penalize negative P&L
        
        # Score = PnL * profit_factor * (1 + sharpe)
        pf = max(0.5, r.profit_factor)
        sharpe = max(0, r.sharpe_ratio)
        return r.total_pnl * pf * (1 + sharpe)
    
    scored = [(r, score(r)) for r in results]
    scored.sort(key=lambda x: x[1], reverse=True)
    
    winner = scored[0][0]
    
    # Build comparison
    comparison = {
        "winner": winner.variant_name,
        "winner_score": scored[0][1],
        "reason": f"Highest score: P&L ${winner.total_pnl:.2f}, PF {winner.profit_factor:.2f}, Sharpe {winner.sharpe_ratio:.2f}",
        "rankings": [
            {
                "rank": i + 1,
                "variant": r.variant_name,
                "score": s,
                "pnl": r.total_pnl,
                "win_rate": r.win_rate,
                "profit_factor": r.profit_factor,
            }
            for i, (r, s) in enumerate(scored)
        ],
        "profitable_variants": [r.variant_name for r, _ in scored if r.total_pnl > 0],
        "losing_variants": [r.variant_name for r, _ in scored if r.total_pnl <= 0],
    }
    
    return comparison


def main():
    parser = argparse.ArgumentParser(description="Run strategy variants A/B test")
    parser.add_argument("--data-path", type=Path, required=True, help="Path to historical data (parquet/csv)")
    parser.add_argument("--variants", nargs="*", default=None, help="Specific variants to test (default: all)")
    parser.add_argument("--start", type=str, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, help="End date (YYYY-MM-DD)")
    parser.add_argument("--symbol", type=str, default="MNQ", choices=["MNQ", "NQ"], help="Symbol (default: MNQ)")
    parser.add_argument("--output-dir", type=Path, default=None, help="Output directory (default: reports/variants_<timestamp>)")
    
    args = parser.parse_args()
    
    # Load data
    print(f"Loading data from {args.data_path}...")
    df = load_data(args.data_path, args.start, args.end)
    print(f"  Loaded {len(df)} bars from {df.index[0]} to {df.index[-1]}")
    
    # Calculate days
    days = (df.index[-1] - df.index[0]).total_seconds() / 86400
    print(f"  Period: {days:.1f} days")
    
    # Setup output
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = args.output_dir or Path("reports") / f"variants_{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Get variants
    presets = NQIntradayConfig.get_variant_presets()
    
    if args.variants:
        variant_names = args.variants
    else:
        variant_names = list(presets.keys())
    
    print(f"\nRunning {len(variant_names)} variants: {', '.join(variant_names)}")
    
    # Set tick value
    tick_value = 2.0 if args.symbol == "MNQ" else 20.0
    
    # Base config
    base_config = NQIntradayConfig.from_config_file()
    
    # Run each variant
    results: List[VariantResult] = []
    full_results: Dict[str, BacktestResult] = {}
    
    for name in variant_names:
        print(f"\n{'='*60}")
        print(f"Running variant: {name}")
        print(f"{'='*60}")
        
        variant_cfg = presets.get(name)
        description = variant_cfg.get("description", name) if variant_cfg else "Default configuration"
        
        try:
            result, config = run_variant(df, name, variant_cfg, base_config, tick_value)
            full_results[name] = result
            
            variant_result = VariantResult.from_backtest(name, description, result, days)
            results.append(variant_result)
            
            # Print summary
            print(f"\n  Results for {name}:")
            print(f"    Signals: {result.total_signals} ({variant_result.signals_per_day:.1f}/day)")
            print(f"    Trades:  {result.total_trades} (Win: {result.winning_trades}, Loss: {result.losing_trades})")
            print(f"    Win Rate: {result.win_rate:.1%}")
            print(f"    P&L:     ${result.total_pnl:.2f}")
            print(f"    PF:      {result.profit_factor:.2f}")
            print(f"    Sharpe:  {result.sharpe_ratio:.2f}")
            print(f"    Max DD:  ${result.max_drawdown:.2f}")
            
            # Save individual result
            summary_path = output_dir / f"{name}_summary.json"
            with open(summary_path, "w") as f:
                json.dump(asdict(result), f, indent=2, default=str)
            
        except Exception as e:
            print(f"  ERROR running {name}: {e}")
            import traceback
            traceback.print_exc()
    
    # Compare variants
    print(f"\n{'='*60}")
    print("COMPARISON RESULTS")
    print(f"{'='*60}")
    
    comparison = compare_variants(results)
    
    if comparison["winner"]:
        print(f"\n🏆 WINNER: {comparison['winner']}")
        print(f"   {comparison['reason']}")
        
        print(f"\n📊 Rankings:")
        for r in comparison["rankings"]:
            status = "✅" if r["pnl"] > 0 else "❌"
            print(f"   {r['rank']}. {status} {r['variant']}: P&L ${r['pnl']:.2f}, WR {r['win_rate']:.1%}, PF {r['profit_factor']:.2f}")
    else:
        print("\n⚠️ No profitable variants found")
    
    # Save comparison
    comparison_path = output_dir / "comparison.json"
    with open(comparison_path, "w") as f:
        json.dump(comparison, f, indent=2, default=str)
    
    # Save CSV for easy viewing
    if results:
        csv_data = [asdict(r) for r in results]
        csv_df = pd.DataFrame(csv_data)
        csv_df.to_csv(output_dir / "comparison.csv", index=False)
    
    # Save winner recommendation
    with open(output_dir / "winner.txt", "w") as f:
        if comparison["winner"]:
            f.write(f"Winner: {comparison['winner']}\n")
            f.write(f"Reason: {comparison['reason']}\n\n")
            f.write("Rankings:\n")
            for r in comparison["rankings"]:
                f.write(f"  {r['rank']}. {r['variant']}: P&L ${r['pnl']:.2f}\n")
        else:
            f.write("No profitable variants found.\n")
            f.write("Consider loosening filters or reviewing signal generation.\n")
    
    print(f"\n📁 Results saved to: {output_dir}")
    print(f"   - comparison.json: Full comparison data")
    print(f"   - comparison.csv: Excel-friendly format")
    print(f"   - winner.txt: Quick recommendation")
    print(f"   - <variant>_summary.json: Individual variant results")
    
    return 0 if comparison.get("profitable_variants") else 1


if __name__ == "__main__":
    sys.exit(main())




