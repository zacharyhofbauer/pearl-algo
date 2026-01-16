#!/usr/bin/env python3
"""
PEARL Bots Comparison CLI

Compare multiple PEARL automated trading bots side-by-side on the same historical data.
Generates comprehensive comparison reports and rankings.

Usage:
    python scripts/backtesting/compare_pearl_bots.py --bots trend_follower,breakout_trader --period 6mo
    python scripts/backtesting/compare_pearl_bots.py --bots all --start 2024-01-01 --end 2024-12-31 --ranking sharpe
    python scripts/backtesting/compare_pearl_bots.py --bots trend_follower,mean_reverter --walk-forward --top-n 3
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

import pandas as pd
import numpy as np

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from pearlalgo.strategies.pearl_bots import (
    TrendFollowerBot,
    BreakoutBot,
    MeanReversionBot,
    BotConfig,
)
from pearlalgo.strategies.pearl_bots.backtest_adapter import (
    backtest_pearl_bot,
    PearlBotBacktestResult,
)
from pearlalgo.utils.logger import logger


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="PEARL Bots Comparison CLI")

    # Bot selection
    parser.add_argument(
        "--bots",
        required=True,
        help="Comma-separated list of bots (trend_follower,breakout_trader,mean_reverter) or 'all'"
    )

    # Data source options
    parser.add_argument(
        "--data-path",
        type=str,
        help="Path to historical data file (parquet format)"
    )
    parser.add_argument(
        "--start",
        type=str,
        help="Start date (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--end",
        type=str,
        help="End date (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--period",
        type=str,
        choices=["1mo", "3mo", "6mo", "1y", "2y"],
        default="3mo",
        help="Testing period (default: 3mo)"
    )

    # Comparison options
    parser.add_argument(
        "--ranking",
        type=str,
        choices=["sharpe", "profit_factor", "win_rate", "total_pnl", "calmar"],
        default="sharpe",
        help="Ranking metric (default: sharpe)"
    )
    parser.add_argument(
        "--top-n",
        type=int,
        help="Show only top N bots"
    )
    parser.add_argument(
        "--walk-forward",
        action="store_true",
        help="Use walk-forward optimization for each bot"
    )
    parser.add_argument(
        "--optimization-runs",
        type=int,
        default=3,
        help="Number of optimization runs per bot (default: 3)"
    )

    # Output options
    parser.add_argument(
        "--output-dir",
        type=str,
        default="reports/comparisons",
        help="Output directory for reports"
    )
    parser.add_argument(
        "--format",
        choices=["table", "json", "csv"],
        default="table",
        help="Output format (default: table)"
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Verbose output"
    )

    return parser.parse_args()


def get_available_bots() -> Dict[str, type]:
    """Get all available bot classes."""
    return {
        "trend_follower": TrendFollowerBot,
        "breakout_trader": BreakoutBot,
        "mean_reverter": MeanReversionBot,
    }


def parse_bot_list(bot_arg: str) -> List[str]:
    """Parse bot list argument."""
    if bot_arg.lower() == "all":
        return list(get_available_bots().keys())

    return [bot.strip() for bot in bot_arg.split(",") if bot.strip()]


def create_bot_configs(bots: List[str]) -> Dict[str, BotConfig]:
    """Create default configurations for specified bots."""
    configs = {}

    for bot_name in bots:
        config = BotConfig(
            name=bot_name.replace("_", " ").title(),
            description=f"Comparison testing {bot_name.replace('_', ' ')} bot",
            risk_per_trade=0.01,
            enable_regime_filtering=True,
            enable_ml_enhancement=True,
        )

        # Bot-specific default parameters
        if bot_name == "trend_follower":
            config.parameters.update({
                "min_trend_strength": 25.0,
                "max_pullback_pct": 0.02,
                "momentum_threshold": 0.005,
            })
        elif bot_name == "breakout_trader":
            config.parameters.update({
                "min_pattern_strength": 0.6,
                "require_volume_confirmation": True,
                "min_momentum_acceleration": 0.001,
            })
        elif bot_name == "mean_reverter":
            config.parameters.update({
                "min_mr_strength": 0.7,
                "require_divergence": False,
                "max_hold_bars": 10,
            })

        configs[bot_name] = config

    return configs


def load_historical_data(args) -> pd.DataFrame:
    """Load and prepare historical data."""
    if args.data_path:
        if not Path(args.data_path).exists():
            raise FileNotFoundError(f"Data file not found: {args.data_path}")
        df = pd.read_parquet(args.data_path)
    else:
        # Try default paths
        default_paths = [
            "data/mnq_1m.parquet",
            "data/MNQ_1m.parquet",
            "data/nq_1m.parquet",
        ]
        for path in default_paths:
            if Path(path).exists():
                df = pd.read_parquet(path)
                break
        else:
            raise FileNotFoundError("No data file found. Please specify --data-path")

    # Ensure proper datetime index
    if 'timestamp' in df.columns:
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df.set_index('timestamp', inplace=True)

    # Filter date range
    if args.start:
        start_date = pd.to_datetime(args.start)
        df = df[df.index >= start_date]
    if args.end:
        end_date = pd.to_datetime(args.end)
        df = df[df.index <= end_date]

    # Use period if no date range specified
    if not args.start and not args.end:
        period_days = {
            "1mo": 30, "3mo": 90, "6mo": 180, "1y": 365, "2y": 730
        }[args.period]

        end_date = df.index.max()
        start_date = end_date - pd.Timedelta(days=period_days)
        df = df[df.index >= start_date]

    logger.info(f"Data range: {df.index.min()} to {df.index.max()} ({len(df)} bars)")
    return df


def optimize_bot_parameters(bot_class, base_config: BotConfig, df: pd.DataFrame,
                          optimization_runs: int) -> BotConfig:
    """Optimize parameters for a single bot."""
    best_config = base_config
    best_score = 0.0

    # Parameter ranges for optimization
    param_ranges = {}

    if bot_class.__name__ == "TrendFollowerBot":
        param_ranges = {
            "min_trend_strength": (20.0, 35.0),
            "max_pullback_pct": (0.015, 0.035),
        }
    elif bot_class.__name__ == "BreakoutBot":
        param_ranges = {
            "min_pattern_strength": (0.5, 0.8),
        }
    elif bot_class.__name__ == "MeanReversionBot":
        param_ranges = {
            "min_mr_strength": (0.6, 0.85),
        }

    for run in range(optimization_runs):
        test_config = BotConfig(
            name=base_config.name,
            description=base_config.description,
            risk_per_trade=base_config.risk_per_trade,
            enable_regime_filtering=base_config.enable_regime_filtering,
            enable_ml_enhancement=False,  # Disable ML during optimization
            parameters=base_config.parameters.copy(),
        )

        # Random parameter sampling
        for param, (min_val, max_val) in param_ranges.items():
            test_config.parameters[param] = np.random.uniform(min_val, max_val)

        # Test configuration
        bot = bot_class(test_config)
        result = backtest_pearl_bot(bot, df, return_signals=False, return_trades=False)

        # Calculate composite score
        score = (
            result.sharpe_ratio * 0.4 +
            (result.profit_factor - 1.0) * 0.3 +
            (result.win_rate - 0.5) * 0.3
        )

        if score > best_score:
            best_score = score
            best_config = test_config

    return best_config


def run_bot_comparison(bots: List[str], configs: Dict[str, BotConfig], df: pd.DataFrame,
                       walk_forward: bool, optimization_runs: int) -> Dict[str, PearlBotBacktestResult]:
    """Run backtests for all specified bots."""
    results = {}
    available_bots = get_available_bots()

    for bot_name in bots:
        if bot_name not in available_bots:
            logger.warning(f"Unknown bot: {bot_name}")
            continue

        logger.info(f"Testing {bot_name}...")

        # Optimize parameters if requested
        if walk_forward:
            config = optimize_bot_parameters(available_bots[bot_name], configs[bot_name],
                                           df, optimization_runs)
            logger.info(f"Optimized parameters: {config.parameters}")
        else:
            config = configs[bot_name]

        # Create and test bot
        bot_class = available_bots[bot_name]
        bot = bot_class(config)

        result = backtest_pearl_bot(
            bot=bot,
            df=df,
            return_signals=True,
            return_trades=True,
        )

        results[bot_name] = result
        logger.info(f"{bot_name}: Win Rate={result.win_rate:.1%}, "
                   f"P&L=${result.total_pnl:.2f}, Sharpe={result.sharpe_ratio:.2f}")

    return results


def rank_bots(results: Dict[str, PearlBotBacktestResult], ranking_metric: str) -> List[Tuple[str, float]]:
    """Rank bots by specified metric."""
    rankings = []

    for bot_name, result in results.items():
        if ranking_metric == "sharpe":
            score = result.sharpe_ratio
        elif ranking_metric == "profit_factor":
            score = result.profit_factor
        elif ranking_metric == "win_rate":
            score = result.win_rate
        elif ranking_metric == "total_pnl":
            score = result.total_pnl
        elif ranking_metric == "calmar":
            # Calmar ratio: annual return / max drawdown
            if result.max_drawdown_pct > 0:
                score = (result.total_pnl * 252 / len(results[bot_name].signals or [1])) / result.max_drawdown_pct if results[bot_name].signals else 0
            else:
                score = 0.0
        else:
            score = result.sharpe_ratio  # Default

        rankings.append((bot_name, score))

    # Sort by score descending
    rankings.sort(key=lambda x: x[1], reverse=True)
    return rankings


def generate_comparison_table(results: Dict[str, PearlBotBacktestResult],
                            rankings: List[Tuple[str, float]], ranking_metric: str,
                            top_n: Optional[int] = None) -> str:
    """Generate formatted comparison table."""
    if top_n:
        rankings = rankings[:top_n]

    table_lines = [
        "PEARL Bots Comparison Report",
        "=" * 50,
        "",
        f"Ranking by: {ranking_metric.upper()}",
        "",
        f"{'Rank':<5} {'Bot':<20} {'Score':<8} {'Win Rate':<10} {'P&L':<10} {'Sharpe':<8} {'Max DD':<10} {'Trades':<8}",
        "-" * 90,
    ]

    for rank, (bot_name, score) in enumerate(rankings, 1):
        result = results[bot_name]
        table_lines.append(
            f"{rank:<5} {bot_name:<20} {score:<8.3f} {result.win_rate:<10.1%} "
            f"${result.total_pnl:<9.2f} {result.sharpe_ratio:<8.2f} "
            f"{result.max_drawdown_pct:<10.1%} {result.total_trades:<8}"
        )

    table_lines.extend([
        "",
        "Performance Summary:",
        f"- Best {ranking_metric}: {rankings[0][0]} ({rankings[0][1]:.3f})",
        f"- Total bots tested: {len(results)}",
        f"- Test period: {len(list(results.values())[0].signals or [])} bars" if results else "- Test period: N/A",
    ])

    return "\n".join(table_lines)


def save_comparison_report(results: Dict[str, PearlBotBacktestResult],
                          rankings: List[Tuple[str, float]], output_dir: str,
                          format: str) -> str:
    """Save comparison report in specified format."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    base_name = f"pearl_bots_comparison_{timestamp}"
    report_file = None

    if format == "json":
        report_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "ranking_metric": rankings[0][1] if rankings else "none",
            "rankings": [{"bot": bot, "score": score} for bot, score in rankings],
            "results": {bot: result.to_dict() for bot, result in results.items()},
        }

        report_file = output_path / f"{base_name}.json"
        with open(report_file, 'w') as f:
            json.dump(report_data, f, indent=2, default=str)

    elif format == "csv":
        # Create summary CSV
        summary_data = []
        for bot_name, result in results.items():
            summary_data.append({
                "bot": bot_name,
                "win_rate": result.win_rate,
                "total_pnl": result.total_pnl,
                "sharpe_ratio": result.sharpe_ratio,
                "profit_factor": result.profit_factor,
                "max_drawdown_pct": result.max_drawdown_pct,
                "total_trades": result.total_trades,
                "avg_confidence": result.avg_confidence,
            })

        df_summary = pd.DataFrame(summary_data)
        report_file = output_path / f"{base_name}.csv"
        df_summary.to_csv(report_file, index=False)

    if report_file:
        logger.info(f"Comparison report saved to: {report_file}")
        return str(report_file)
    else:
        logger.warning("No report file generated")
        return ""


def main():
    """Main comparison function."""
    args = parse_args()

    try:
        # Parse bot list
        bots = parse_bot_list(args.bots)
        logger.info(f"Comparing bots: {', '.join(bots)}")

        # Create bot configurations
        configs = create_bot_configs(bots)

        # Load historical data
        df = load_historical_data(args)
        if df.empty:
            logger.error("No data available for comparison")
            return 1

        # Run comparison
        results = run_bot_comparison(bots, configs, df, args.walk_forward, args.optimization_runs)

        if not results:
            logger.error("No successful bot tests")
            return 1

        # Rank bots
        rankings = rank_bots(results, args.ranking)

        # Generate and display comparison table
        table = generate_comparison_table(results, rankings, args.ranking, args.top_n)
        print(table)

        # Save report
        report_path = save_comparison_report(results, rankings, args.output_dir, args.format)

        logger.info("Bot comparison complete!")
        return 0

    except Exception as e:
        logger.error(f"Comparison failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())