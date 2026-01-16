#!/usr/bin/env python3
"""
PEARL Bot Performance Analysis CLI

Deep performance analysis for PEARL automated trading bots including:
- Walk-forward optimization
- Parameter sensitivity analysis
- Risk-adjusted performance metrics
- Market regime performance breakdown
- Monte Carlo simulation

Usage:
    python scripts/backtesting/analyze_pearl_bot_performance.py --bot trend_follower --walk-forward --monte-carlo 1000
    python scripts/backtesting/analyze_pearl_bot_performance.py --bot breakout_trader --parameter-sensitivity --regime-analysis
    python scripts/backtesting/analyze_pearl_bot_performance.py --bot mean_reverter --optimization --risk-metrics
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
from scipy import stats

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from pearlalgo.strategies.pearl_bots import (
    TrendFollowerBot,
    BreakoutBot,
    MeanReversionBot,
    BotConfig,
)
from pearlalgo.strategies.pearl_bots.backtest_adapter import backtest_pearl_bot
from pearlalgo.strategies.pearl_bots.market_regime_detector import market_regime_detector
from pearlalgo.utils.logger import logger


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="PEARL Bot Performance Analysis CLI")

    # Required arguments
    parser.add_argument(
        "--bot",
        required=True,
        choices=["trend_follower", "breakout_trader", "mean_reverter"],
        help="Bot to analyze"
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
        choices=["3mo", "6mo", "1y", "2y"],
        default="6mo",
        help="Analysis period (default: 6mo)"
    )

    # Analysis types
    parser.add_argument(
        "--walk-forward",
        action="store_true",
        help="Perform walk-forward optimization analysis"
    )
    parser.add_argument(
        "--parameter-sensitivity",
        action="store_true",
        help="Analyze parameter sensitivity"
    )
    parser.add_argument(
        "--regime-analysis",
        action="store_true",
        help="Break down performance by market regime"
    )
    parser.add_argument(
        "--monte-carlo",
        type=int,
        help="Number of Monte Carlo simulations"
    )
    parser.add_argument(
        "--risk-metrics",
        action="store_true",
        help="Calculate advanced risk metrics"
    )

    # Analysis parameters
    parser.add_argument(
        "--optimization-runs",
        type=int,
        default=10,
        help="Number of optimization runs (default: 10)"
    )
    parser.add_argument(
        "--walk-forward-window",
        type=str,
        default="1mo",
        help="Walk-forward window size (default: 1mo)"
    )
    parser.add_argument(
        "--confidence-level",
        type=float,
        default=0.95,
        help="Confidence level for statistical tests (default: 0.95)"
    )

    # Output options
    parser.add_argument(
        "--output-dir",
        type=str,
        default="reports/analysis",
        help="Output directory for reports"
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Verbose output"
    )

    return parser.parse_args()


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
            "3mo": 90, "6mo": 180, "1y": 365, "2y": 730
        }[args.period]

        end_date = df.index.max()
        start_date = end_date - pd.Timedelta(days=period_days)
        df = df[df.index >= start_date]

    logger.info(f"Analysis data: {df.index.min()} to {df.index.max()} ({len(df)} bars)")
    return df


def create_base_config(bot_name: str) -> BotConfig:
    """Create base configuration for analysis."""
    config = BotConfig(
        name=bot_name.replace("_", " ").title(),
        description=f"Performance analysis for {bot_name.replace('_', ' ')} bot",
        risk_per_trade=0.01,
        enable_regime_filtering=True,
        enable_ml_enhancement=True,
    )

    # Bot-specific parameters
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

    return config


def perform_walk_forward_optimization(bot_class, df: pd.DataFrame, window_size: str,
                                   optimization_runs: int) -> Dict[str, Any]:
    """Perform walk-forward optimization analysis."""
    logger.info(f"Performing walk-forward optimization with {window_size} windows...")

    # Parse window size
    if window_size == "1mo":
        window_days = 30
    elif window_size == "2mo":
        window_days = 60
    elif window_size == "3mo":
        window_days = 90
    else:
        window_days = 30

    # Split data into walk-forward windows
    total_days = (df.index.max() - df.index.min()).days
    n_windows = max(1, total_days // window_days)

    results = []
    optimized_configs = []

    for i in range(n_windows):
        # Define window
        window_start = df.index.min() + pd.Timedelta(days=i * window_days)
        window_end = min(window_start + pd.Timedelta(days=window_days), df.index.max())

        window_data = df[(df.index >= window_start) & (df.index <= window_end)]

        if len(window_data) < 1000:  # Minimum bars for reliable testing
            continue

        logger.info(f"Optimizing window {i+1}/{n_windows}: {window_start.date()} to {window_end.date()}")

        # Optimize parameters for this window
        best_config = optimize_parameters_window(bot_class, window_data, optimization_runs)

        # Test optimized config on next window (if available)
        next_window_start = window_end + pd.Timedelta(days=1)
        next_window_end = min(next_window_start + pd.Timedelta(days=window_days), df.index.max())

        if next_window_start < df.index.max():
            next_window_data = df[(df.index >= next_window_start) & (df.index <= next_window_end)]
            if len(next_window_data) >= 500:
                # Test optimized parameters on future data
                test_config = BotConfig(
                    name=f"WF_Test_{i+1}",
                    description=f"Walk-forward test window {i+1}",
                    risk_per_trade=best_config.risk_per_trade,
                    enable_regime_filtering=False,  # Disable for testing
                    enable_ml_enhancement=False,
                    parameters=best_config.parameters.copy(),
                )

                bot = bot_class(test_config)
                result = backtest_pearl_bot(bot, next_window_data, return_signals=False, return_trades=False)

                results.append({
                    "window": i+1,
                    "optimization_period": f"{window_start.date()} to {window_end.date()}",
                    "test_period": f"{next_window_start.date()} to {next_window_end.date()}",
                    "optimized_params": best_config.parameters,
                    "test_performance": {
                        "sharpe_ratio": result.sharpe_ratio,
                        "total_pnl": result.total_pnl,
                        "win_rate": result.win_rate,
                        "profit_factor": result.profit_factor,
                    }
                })

                optimized_configs.append(best_config)

    # Calculate overall walk-forward performance
    if results:
        avg_sharpe = np.mean([r["test_performance"]["sharpe_ratio"] for r in results])
        avg_win_rate = np.mean([r["test_performance"]["win_rate"] for r in results])
        total_pnl = sum([r["test_performance"]["total_pnl"] for r in results])

        wf_performance = {
            "total_windows": len(results),
            "average_sharpe_ratio": avg_sharpe,
            "average_win_rate": avg_win_rate,
            "total_pnl": total_pnl,
            "window_results": results,
        }
    else:
        wf_performance = {"error": "Insufficient data for walk-forward analysis"}

    return wf_performance


def optimize_parameters_window(bot_class, df: pd.DataFrame, optimization_runs: int) -> BotConfig:
    """Optimize parameters for a specific data window."""
    base_config = create_base_config(bot_class.__name__.lower().replace("bot", "").replace("trendfollower", "trend_follower").replace("breakout", "breakout_trader").replace("meanreversion", "mean_reverter"))

    best_config = base_config
    best_score = -float('inf')

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
            description=f"Optimization run {run+1}",
            risk_per_trade=base_config.risk_per_trade,
            enable_regime_filtering=False,  # Disable during optimization
            enable_ml_enhancement=False,
            parameters=base_config.parameters.copy(),
        )

        # Random parameter sampling
        for param, (min_val, max_val) in param_ranges.items():
            test_config.parameters[param] = np.random.uniform(min_val, max_val)

        # Test configuration
        bot = bot_class(test_config)
        result = backtest_pearl_bot(bot, df, return_signals=False, return_trades=False)

        # Composite score favoring Sharpe ratio and win rate
        score = (
            result.sharpe_ratio * 0.5 +
            (result.win_rate - 0.5) * 0.3 +
            min(result.profit_factor, 3.0) * 0.2  # Cap profit factor contribution
        )

        if score > best_score:
            best_score = score
            best_config = test_config

    return best_config


def analyze_parameter_sensitivity(bot_class, df: pd.DataFrame) -> Dict[str, Any]:
    """Analyze how performance varies with parameter changes."""
    logger.info("Analyzing parameter sensitivity...")

    base_config = create_base_config(bot_class.__name__.lower().replace("bot", "").replace("trendfollower", "trend_follower").replace("breakout", "breakout_trader").replace("meanreversion", "mean_reverter"))
    results = {}

    # Define parameter ranges to test
    param_tests = {}

    if bot_class.__name__ == "TrendFollowerBot":
        param_tests = {
            "min_trend_strength": [15, 20, 25, 30, 35],
            "max_pullback_pct": [0.01, 0.015, 0.02, 0.025, 0.03],
        }
    elif bot_class.__name__ == "BreakoutBot":
        param_tests = {
            "min_pattern_strength": [0.4, 0.5, 0.6, 0.7, 0.8],
        }
    elif bot_class.__name__ == "MeanReversionBot":
        param_tests = {
            "min_mr_strength": [0.5, 0.6, 0.7, 0.8, 0.9],
        }

    for param_name, test_values in param_tests.items():
        param_results = []

        for value in test_values:
            test_config = BotConfig(
                name=f"Param_Test_{param_name}_{value}",
                description=f"Testing {param_name} = {value}",
                risk_per_trade=base_config.risk_per_trade,
                enable_regime_filtering=False,
                enable_ml_enhancement=False,
                parameters=base_config.parameters.copy(),
            )
            test_config.parameters[param_name] = value

            bot = bot_class(test_config)
            result = backtest_pearl_bot(bot, df, return_signals=False, return_trades=False)

            param_results.append({
                "parameter_value": value,
                "sharpe_ratio": result.sharpe_ratio,
                "win_rate": result.win_rate,
                "total_pnl": result.total_pnl,
                "profit_factor": result.profit_factor,
            })

        results[param_name] = param_results

        # Calculate sensitivity metrics
        sharpe_values = [r["sharpe_ratio"] for r in param_results]
        results[param_name + "_sensitivity"] = {
            "range": max(sharpe_values) - min(sharpe_values),
            "optimal_value": test_values[np.argmax(sharpe_values)],
            "optimal_sharpe": max(sharpe_values),
        }

    return results


def analyze_regime_performance(bot_class, df: pd.DataFrame) -> Dict[str, Any]:
    """Analyze performance across different market regimes."""
    logger.info("Analyzing regime-specific performance...")

    config = create_base_config(bot_class.__name__.lower().replace("bot", "").replace("trendfollower", "trend_follower").replace("breakout", "breakout_trader").replace("meanreversion", "mean_reverter"))

    # Get regime classifications for each bar
    regime_data = []
    window_size = 200  # Rolling window for regime detection

    for i in range(window_size, len(df), 50):  # Sample every 50 bars for efficiency
        window = df.iloc[i-window_size:i]
        regime, metrics, confidence = market_regime_detector.detect_regime(window)

        regime_data.append({
            "timestamp": df.index[i],
            "regime": regime.value,
            "confidence": confidence,
            "adx": metrics.adx,
            "trend_direction": metrics.trend_direction,
        })

    regime_df = pd.DataFrame(regime_data)
    regime_df.set_index("timestamp", inplace=True)

    # Test bot performance in each regime
    regime_performance = {}

    for regime in ["trending_bull", "trending_bear", "ranging", "volatile", "mixed"]:
        regime_mask = regime_df["regime"] == regime
        if regime_mask.sum() == 0:
            continue

        # Get data for this regime
        regime_timestamps = regime_df[regime_mask].index
        regime_data_subset = df[df.index.isin(regime_timestamps)]

        if len(regime_data_subset) < 500:  # Minimum bars
            continue

        logger.info(f"Testing {regime} regime ({len(regime_data_subset)} bars)...")

        # Test bot in this regime
        bot = bot_class(config)
        result = backtest_pearl_bot(bot, regime_data_subset, return_signals=False, return_trades=False)

        regime_performance[regime] = {
            "bars": len(regime_data_subset),
            "sharpe_ratio": result.sharpe_ratio,
            "win_rate": result.win_rate,
            "total_pnl": result.total_pnl,
            "profit_factor": result.profit_factor,
            "total_trades": result.total_trades,
        }

    return regime_performance


def perform_monte_carlo_analysis(bot_class, df: pd.DataFrame, n_simulations: int) -> Dict[str, Any]:
    """Perform Monte Carlo analysis for robustness testing."""
    logger.info(f"Performing Monte Carlo analysis with {n_simulations} simulations...")

    config = create_base_config(bot_class.__name__.lower().replace("bot", "").replace("trendfollower", "trend_follower").replace("breakout", "breakout_trader").replace("meanreversion", "mean_reverter"))

    results = []

    for sim in range(n_simulations):
        # Create random subset of data (bootstrapping)
        sample_indices = np.random.choice(len(df), size=len(df), replace=True)
        sample_df = df.iloc[sample_indices].sort_index()

        # Test bot on random sample
        bot = bot_class(config)
        result = backtest_pearl_bot(bot, sample_df, return_signals=False, return_trades=False)

        results.append({
            "simulation": sim + 1,
            "sharpe_ratio": result.sharpe_ratio,
            "total_pnl": result.total_pnl,
            "win_rate": result.win_rate,
            "profit_factor": result.profit_factor,
        })

    # Calculate statistics
    sharpe_ratios = [r["sharpe_ratio"] for r in results]
    pnl_values = [r["total_pnl"] for r in results]
    win_rates = [r["win_rate"] for r in results]

    mc_stats = {
        "n_simulations": n_simulations,
        "sharpe_ratio": {
            "mean": np.mean(sharpe_ratios),
            "std": np.std(sharpe_ratios),
            "min": np.min(sharpe_ratios),
            "max": np.max(sharpe_ratios),
            "confidence_interval_95": stats.t.interval(0.95, len(sharpe_ratios)-1,
                                                    loc=np.mean(sharpe_ratios),
                                                    scale=stats.sem(sharpe_ratios))
        },
        "total_pnl": {
            "mean": np.mean(pnl_values),
            "std": np.std(pnl_values),
            "min": np.min(pnl_values),
            "max": np.max(pnl_values),
        },
        "win_rate": {
            "mean": np.mean(win_rates),
            "std": np.std(win_rates),
        },
        "prob_profit": sum(1 for pnl in pnl_values if pnl > 0) / n_simulations,
        "expected_pnl": np.mean(pnl_values),
        "sharpe_stability": np.mean(sharpe_ratios) / np.std(sharpe_ratios) if np.std(sharpe_ratios) > 0 else 0,
    }

    return mc_stats


def calculate_risk_metrics(bot_class, df: pd.DataFrame) -> Dict[str, Any]:
    """Calculate advanced risk metrics."""
    logger.info("Calculating advanced risk metrics...")

    config = create_base_config(bot_class.__name__.lower().replace("bot", "").replace("trendfollower", "trend_follower").replace("breakout", "breakout_trader").replace("meanreversion", "mean_reverter"))

    bot = bot_class(config)
    result = backtest_pearl_bot(bot, df, return_signals=True, return_trades=True)

    if not result.trades:
        return {"error": "No trades generated"}

    # Extract trade P&L series
    trade_returns = [trade.get("pnl", 0) for trade in result.trades if trade.get("pnl") is not None]

    if not trade_returns:
        return {"error": "No trade P&L data"}

    # Calculate advanced metrics
    returns_array = np.array(trade_returns)

    # Value at Risk (VaR)
    var_95 = np.percentile(returns_array, 5)  # 95% confidence
    var_99 = np.percentile(returns_array, 1)  # 99% confidence

    # Expected Shortfall (CVaR)
    cvar_95 = np.mean(returns_array[returns_array <= var_95])
    cvar_99 = np.mean(returns_array[returns_array <= var_99])

    # Maximum Drawdown from equity curve
    equity_curve = np.cumsum(returns_array)
    peak = np.maximum.accumulate(equity_curve)
    drawdowns = equity_curve - peak
    max_drawdown = np.min(drawdowns)

    # Calmar Ratio (annual return / max drawdown)
    # Assume daily returns for annualization
    annual_return = np.mean(returns_array) * 252
    calmar_ratio = annual_return / abs(max_drawdown) if max_drawdown != 0 else 0

    # Sortino Ratio (only downside deviation)
    downside_returns = returns_array[returns_array < 0]
    downside_std = np.std(downside_returns) if len(downside_returns) > 0 else 0
    sortino_ratio = np.mean(returns_array) / downside_std * np.sqrt(252) if downside_std > 0 else 0

    # Omega Ratio (probability weighted return)
    threshold = 0  # Risk-free rate proxy
    omega_ratio = np.sum(returns_array[returns_array > threshold]) / abs(np.sum(returns_array[returns_array < threshold])) if np.sum(returns_array[returns_array < threshold]) != 0 else 0

    # Tail Ratio (upside potential / downside risk)
    upside_potential = np.percentile(returns_array, 95)
    downside_risk = abs(np.percentile(returns_array, 5))
    tail_ratio = upside_potential / downside_risk if downside_risk > 0 else 0

    risk_metrics = {
        "var_95": var_95,
        "var_99": var_99,
        "cvar_95": cvar_95,
        "cvar_99": cvar_99,
        "max_drawdown": max_drawdown,
        "calmar_ratio": calmar_ratio,
        "sortino_ratio": sortino_ratio,
        "omega_ratio": omega_ratio,
        "tail_ratio": tail_ratio,
        "kurtosis": stats.kurtosis(returns_array),
        "skewness": stats.skew(returns_array),
        "probability_profit": len([r for r in returns_array if r > 0]) / len(returns_array),
        "avg_win": np.mean([r for r in returns_array if r > 0]) if any(r > 0 for r in returns_array) else 0,
        "avg_loss": np.mean([r for r in returns_array if r < 0]) if any(r < 0 for r in returns_array) else 0,
    }

    return risk_metrics


def generate_analysis_report(analysis_results: Dict[str, Any], output_dir: str) -> str:
    """Generate comprehensive analysis report."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report_file = output_path / f"pearl_bot_analysis_{timestamp}.json"

    # Add metadata
    report_data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "analysis_version": "1.0.0",
        "results": analysis_results,
    }

    with open(report_file, 'w') as f:
        json.dump(report_data, f, indent=2, default=str)

    logger.info(f"Analysis report saved to: {report_file}")
    return str(report_file)


def print_analysis_summary(analysis_results: Dict[str, Any]) -> None:
    """Print human-readable analysis summary."""
    print("\n" + "="*60)
    print("PEARL BOT PERFORMANCE ANALYSIS SUMMARY")
    print("="*60)

    if "walk_forward" in analysis_results:
        wf = analysis_results["walk_forward"]
        if "total_windows" in wf:
            print(f"\nWalk-Forward Optimization:")
            print(f"  Windows tested: {wf['total_windows']}")
            print(f"  Average Sharpe: {wf['average_sharpe_ratio']:.3f}")
            print(f"  Average Win Rate: {wf['average_win_rate']:.1%}")
            print(f"  Total P&L: ${wf['total_pnl']:.2f}")

    if "parameter_sensitivity" in analysis_results:
        ps = analysis_results["parameter_sensitivity"]
        print(f"\nParameter Sensitivity:")
        for param, data in ps.items():
            if param.endswith("_sensitivity"):
                base_param = param.replace("_sensitivity", "")
                sens = data
                print(f"  {base_param}:")
                print(f"    Optimal: {sens['optimal_value']} (Sharpe: {sens['optimal_sharpe']:.3f})")
                print(f"    Range: {sens['range']:.3f}")

    if "regime_analysis" in analysis_results:
        ra = analysis_results["regime_analysis"]
        print(f"\nRegime Performance:")
        for regime, perf in ra.items():
            print(f"  {regime}: Sharpe={perf['sharpe_ratio']:.3f}, "
                  f"Win Rate={perf['win_rate']:.1%}, P&L=${perf['total_pnl']:.2f}")

    if "monte_carlo" in analysis_results:
        mc = analysis_results["monte_carlo"]
        sr_stats = mc["sharpe_ratio"]
        print(f"\nMonte Carlo Analysis ({mc['n_simulations']} simulations):")
        print(f"  Sharpe Ratio: {sr_stats['mean']:.3f} ± {sr_stats['std']:.3f}")
        print(f"  Profit Probability: {mc['prob_profit']:.1%}")
        print(f"  Expected P&L: ${mc['expected_pnl']:.2f}")

    if "risk_metrics" in analysis_results:
        rm = analysis_results["risk_metrics"]
        if "var_95" in rm:
            print(f"\nRisk Metrics:")
            print(f"  VaR (95%): ${rm['var_95']:.2f}")
            print(f"  CVaR (95%): ${rm['cvar_95']:.2f}")
            print(f"  Calmar Ratio: {rm['calmar_ratio']:.3f}")
            print(f"  Sortino Ratio: {rm['sortino_ratio']:.3f}")
            print(f"  Profit Probability: {rm['probability_profit']:.1%}")

    print(f"\nDetailed results saved to analysis report.")


def main():
    """Main analysis function."""
    args = parse_args()

    try:
        logger.info(f"Starting PEARL bot performance analysis for: {args.bot}")

        # Load historical data
        df = load_historical_data(args)
        if df.empty:
            logger.error("No data available for analysis")
            return 1

        # Get bot class
        bot_classes = {
            "trend_follower": TrendFollowerBot,
            "breakout_trader": BreakoutBot,
            "mean_reverter": MeanReversionBot,
        }
        bot_class = bot_classes[args.bot]

        # Run requested analyses
        analysis_results = {}

        if args.walk_forward:
            analysis_results["walk_forward"] = perform_walk_forward_optimization(
                bot_class, df, args.walk_forward_window, args.optimization_runs
            )

        if args.parameter_sensitivity:
            analysis_results["parameter_sensitivity"] = analyze_parameter_sensitivity(bot_class, df)

        if args.regime_analysis:
            analysis_results["regime_analysis"] = analyze_regime_performance(bot_class, df)

        if args.monte_carlo:
            analysis_results["monte_carlo"] = perform_monte_carlo_analysis(
                bot_class, df, args.monte_carlo
            )

        if args.risk_metrics:
            analysis_results["risk_metrics"] = calculate_risk_metrics(bot_class, df)

        # Generate report
        if analysis_results:
            report_path = generate_analysis_report(analysis_results, args.output_dir)
            print_analysis_summary(analysis_results)
        else:
            logger.warning("No analyses were requested")

        logger.info("Performance analysis complete!")
        return 0

    except Exception as e:
        logger.error(f"Analysis failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())