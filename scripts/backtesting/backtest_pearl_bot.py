#!/usr/bin/env python3
"""
PEARL Bot Backtesting CLI

Comprehensive backtesting tool for individual PEARL automated trading bots.
Tests bots on historical data with various configurations and generates detailed reports.

Usage:
    python scripts/backtesting/backtest_pearl_bot.py --bot trend_follower --data-path data/mnq_1m.parquet --period 3mo
    python scripts/backtesting/backtest_pearl_bot.py --bot breakout_trader --start 2024-01-01 --end 2024-12-31 --contracts 5
    python scripts/backtesting/backtest_pearl_bot.py --bot mean_reverter --walk-forward --optimization-runs 10
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any

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
    create_bot,
)
from pearlalgo.strategies.pearl_bots.backtest_adapter import (
    PearlBotBacktestAdapter,
    backtest_pearl_bot,
    PearlBotBacktestResult,
)
from pearlalgo.utils.logger import logger


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="PEARL Bot Backtesting CLI")

    # Required arguments
    parser.add_argument(
        "--bot",
        required=True,
        choices=["trend_follower", "breakout_trader", "mean_reverter"],
        help="Bot to backtest"
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

    # Trading parameters
    parser.add_argument(
        "--contracts",
        type=int,
        default=1,
        help="Number of contracts per trade (default: 1)"
    )
    parser.add_argument(
        "--risk-per-trade",
        type=float,
        default=0.01,
        help="Risk per trade as fraction (default: 0.01)"
    )

    # Bot-specific parameters
    parser.add_argument(
        "--min-trend-strength",
        type=float,
        help="Minimum trend strength (TrendFollowerBot)"
    )
    parser.add_argument(
        "--max-pullback-pct",
        type=float,
        help="Maximum pullback percentage (TrendFollowerBot)"
    )
    parser.add_argument(
        "--min-pattern-strength",
        type=float,
        help="Minimum pattern strength (BreakoutBot)"
    )
    parser.add_argument(
        "--min-mr-strength",
        type=float,
        help="Minimum MR strength (MeanReversionBot)"
    )

    # Backtesting options
    parser.add_argument(
        "--walk-forward",
        action="store_true",
        help="Use walk-forward optimization"
    )
    parser.add_argument(
        "--optimization-runs",
        type=int,
        default=5,
        help="Number of optimization runs (default: 5)"
    )
    parser.add_argument(
        "--parameter-sweep",
        action="store_true",
        help="Perform parameter sweep optimization"
    )

    # Output options
    parser.add_argument(
        "--output-dir",
        type=str,
        default="reports/backtests",
        help="Output directory for reports"
    )
    parser.add_argument(
        "--generate-charts",
        action="store_true",
        help="Generate performance charts"
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Verbose output"
    )

    return parser.parse_args()


def create_bot_config(bot_name: str, args) -> BotConfig:
    """Create bot configuration from command line arguments."""
    # Base configuration
    config = BotConfig(
        name=bot_name.replace("_", " ").title(),
        description=f"Backtesting {bot_name.replace('_', ' ')} bot",
        risk_per_trade=args.risk_per_trade,
        enable_regime_filtering=True,
        enable_ml_enhancement=True,
    )

    # Bot-specific parameters
    if bot_name == "trend_follower":
        config.parameters.update({
            "min_trend_strength": args.min_trend_strength or 25.0,
            "max_pullback_pct": args.max_pullback_pct or 0.02,
            "momentum_threshold": 0.005,
        })
    elif bot_name == "breakout_trader":
        config.parameters.update({
            "min_pattern_strength": args.min_pattern_strength or 0.6,
            "require_volume_confirmation": True,
            "min_momentum_acceleration": 0.001,
        })
    elif bot_name == "mean_reverter":
        config.parameters.update({
            "min_mr_strength": args.min_mr_strength or 0.7,
            "require_divergence": False,
            "max_hold_bars": 10,
        })

    return config


def load_historical_data(args) -> pd.DataFrame:
    """Load and prepare historical data."""
    if args.data_path:
        # Load from specific file
        if not Path(args.data_path).exists():
            raise FileNotFoundError(f"Data file not found: {args.data_path}")

        df = pd.read_parquet(args.data_path)
        logger.info(f"Loaded data from {args.data_path}")
    else:
        # Try to find default data file
        default_paths = [
            "data/mnq_1m.parquet",
            "data/MNQ_1m.parquet",
            "data/nq_1m.parquet",
        ]

        for path in default_paths:
            if Path(path).exists():
                df = pd.read_parquet(path)
                logger.info(f"Loaded data from {path}")
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

    # If no date range specified, use period
    if not args.start and not args.end:
        if args.period == "1mo":
            days = 30
        elif args.period == "3mo":
            days = 90
        elif args.period == "6mo":
            days = 180
        elif args.period == "1y":
            days = 365
        elif args.period == "2y":
            days = 730

        end_date = df.index.max()
        start_date = end_date - pd.Timedelta(days=days)
        df = df[df.index >= start_date]

    logger.info(f"Data range: {df.index.min()} to {df.index.max()} ({len(df)} bars)")
    return df


def optimize_parameters(bot_class, base_config: BotConfig, df: pd.DataFrame,
                       optimization_runs: int) -> BotConfig:
    """Perform parameter optimization."""
    logger.info(f"Optimizing parameters with {optimization_runs} runs...")

    best_config = base_config
    best_performance = 0.0

    # Parameter ranges for optimization
    param_ranges = {}

    if bot_class.__name__ == "TrendFollowerBot":
        param_ranges = {
            "min_trend_strength": (15.0, 35.0),
            "max_pullback_pct": (0.01, 0.05),
        }
    elif bot_class.__name__ == "BreakoutBot":
        param_ranges = {
            "min_pattern_strength": (0.4, 0.8),
        }
    elif bot_class.__name__ == "MeanReversionBot":
        param_ranges = {
            "min_mr_strength": (0.5, 0.9),
        }

    for run in range(optimization_runs):
        # Create random parameter set
        test_config = BotConfig(
            name=base_config.name,
            description=base_config.description,
            risk_per_trade=base_config.risk_per_trade,
            enable_regime_filtering=base_config.enable_regime_filtering,
            enable_ml_enhancement=False,  # Disable ML during optimization
            parameters=base_config.parameters.copy(),
        )

        # Randomize parameters
        for param, (min_val, max_val) in param_ranges.items():
            if isinstance(min_val, float):
                test_config.parameters[param] = np.random.uniform(min_val, max_val)
            else:
                test_config.parameters[param] = np.random.randint(min_val, max_val)

        # Test configuration
        bot = bot_class(test_config)
        result = backtest_pearl_bot(bot, df, return_signals=False, return_trades=False)

        # Evaluate performance (sharpe ratio + win rate)
        score = result.sharpe_ratio * 0.6 + (result.win_rate - 0.5) * 0.4

        if score > best_performance:
            best_performance = score
            best_config = test_config
            logger.info(f"New best config (run {run+1}): Sharpe={result.sharpe_ratio:.2f}, "
                       f"Win Rate={result.win_rate:.1%}, Score={score:.3f}")

    logger.info(f"Optimization complete. Best score: {best_performance:.3f}")
    return best_config


def generate_report(result: PearlBotBacktestResult, output_dir: str, generate_charts: bool) -> str:
    """Generate comprehensive backtest report."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report_file = output_path / f"pearl_bot_backtest_{result.bot_name.lower().replace(' ', '_')}_{timestamp}.json"

    # Convert result to dict and save
    report_data = result.to_dict()

    # Add additional metadata
    report_data.update({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "1.0.0",
        "metadata": {
            "total_bars": result.total_bars,
            "test_period_days": (pd.to_datetime(result.signals[-1]["timestamp"]) - pd.to_datetime(result.signals[0]["timestamp"])).days if result.signals else 0,
        }
    })

    with open(report_file, 'w') as f:
        json.dump(report_data, f, indent=2, default=str)

    logger.info(f"Report saved to: {report_file}")

    # Generate summary
    summary = f"""
PEARL Bot Backtest Report
========================

Bot: {result.bot_name}
Period: {result.total_bars} bars
Signals: {result.total_signals}
Trades: {result.total_trades}

Performance Metrics:
- Win Rate: {result.win_rate:.1%}
- Total P&L: ${result.total_pnl:.2f}
- Profit Factor: {result.profit_factor:.2f}
- Sharpe Ratio: {result.sharpe_ratio:.2f}
- Max Drawdown: {result.max_drawdown_pct:.1%}
- Avg Hold Time: {result.avg_hold_time_minutes:.1f} minutes

Risk Metrics:
- Avg Win: ${result.avg_win:.2f}
- Avg Loss: ${result.avg_loss:.2f}
- Max Drawdown: {result.max_drawdown_pct:.1%}
- Sharpe Ratio: {result.sharpe_ratio:.2f}

Signal Quality:
- Avg Confidence: {result.avg_confidence:.2f}
- Avg Risk/Reward: {result.avg_risk_reward:.2f}

Report saved to: {report_file}
"""

    print(summary)
    return str(report_file)


def main():
    """Main backtesting function."""
    args = parse_args()

    try:
        logger.info(f"Starting PEARL bot backtest for: {args.bot}")

        # Load historical data
        df = load_historical_data(args)
        if df.empty:
            logger.error("No data available for backtesting")
            return 1

        # Create bot configuration
        base_config = create_bot_config(args.bot, args)

        # Map bot name to class
        bot_classes = {
            "trend_follower": TrendFollowerBot,
            "breakout_trader": BreakoutBot,
            "mean_reverter": MeanReversionBot,
        }
        bot_class = bot_classes[args.bot]

        # Parameter optimization if requested
        if args.walk_forward or args.parameter_sweep:
            optimized_config = optimize_parameters(bot_class, base_config, df, args.optimization_runs)
        else:
            optimized_config = base_config

        # Create and configure bot
        bot = bot_class(optimized_config)

        # Run backtest
        logger.info("Running backtest...")
        result = backtest_pearl_bot(
            bot=bot,
            df=df,
            return_signals=True,
            return_trades=True,
        )

        # Generate report
        report_path = generate_report(result, args.output_dir, args.generate_charts)

        logger.info("Backtest complete!")
        return 0

    except Exception as e:
        logger.error(f"Backtest failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())