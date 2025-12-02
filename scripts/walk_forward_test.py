#!/usr/bin/env python
"""
Walk-Forward Testing Framework
Implements walk-forward analysis for strategy validation and parameter optimization.
"""

from __future__ import annotations

import argparse
from datetime import timedelta
from pathlib import Path
from typing import Any

import pandas as pd
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

from pearlalgo.futures.signals import generate_signal

console = Console()


def walk_forward_test(
    df: pd.DataFrame,
    symbol: str,
    strategy_name: str,
    train_period_days: int = 60,
    test_period_days: int = 30,
    step_days: int = 30,
    strategy_params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """
    Perform walk-forward testing on a strategy.

    Args:
        df: OHLCV DataFrame with datetime index
        symbol: Trading symbol
        strategy_name: Strategy name
        train_period_days: Training period in days
        test_period_days: Testing period in days
        step_days: Step size between windows in days
        strategy_params: Strategy parameters

    Returns:
        List of test results for each window
    """
    if df.empty or "timestamp" not in df.columns:
        df = df.reset_index()
        if "Date" in df.columns:
            df["timestamp"] = pd.to_datetime(df["Date"])
        elif df.index.name == "Date" or isinstance(df.index, pd.DatetimeIndex):
            df["timestamp"] = df.index

    if "timestamp" not in df.columns:
        raise ValueError("DataFrame must have a timestamp column or datetime index")

    df = df.sort_values("timestamp").reset_index(drop=True)
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    start_date = df["timestamp"].min()
    end_date = df["timestamp"].max()

    results = []
    current_start = start_date

    window_num = 0
    while current_start < end_date:
        train_end = current_start + timedelta(days=train_period_days)
        test_start = train_end
        test_end = test_start + timedelta(days=test_period_days)

        if test_end > end_date:
            break

        # Extract training and testing windows
        train_df = df[
            (df["timestamp"] >= current_start) & (df["timestamp"] < train_end)
        ].copy()
        test_df = df[
            (df["timestamp"] >= test_start) & (df["timestamp"] < test_end)
        ].copy()

        if len(train_df) < 50 or len(test_df) < 10:
            current_start += timedelta(days=step_days)
            continue

        # Run strategy on test period
        test_signals = []
        test_pnl = 0.0
        test_trades = 0
        test_wins = 0

        # Simple backtest: track signals and simulate trades
        for i in range(len(test_df)):
            window_df = test_df.iloc[: i + 1]
            if len(window_df) < 20:  # Need minimum data
                continue

            signal = generate_signal(
                symbol=symbol,
                df=window_df,
                strategy_name=strategy_name,
                **(strategy_params or {}),
            )

            if signal["side"] != "flat":
                test_signals.append(
                    {
                        "timestamp": window_df["timestamp"].iloc[-1],
                        "side": signal["side"],
                        "price": float(window_df["Close"].iloc[-1]),
                        "confidence": signal.get("confidence", 0.0),
                    }
                )

        # Simple P&L calculation (entry/exit simulation)
        position = None
        entry_price = None
        for signal in test_signals:
            if position is None:
                if signal["side"] in ["long", "short"]:
                    position = signal["side"]
                    entry_price = signal["price"]
                    test_trades += 1
            else:
                # Exit on opposite signal or flat
                if (position == "long" and signal["side"] in ["short", "flat"]) or (
                    position == "short" and signal["side"] in ["long", "flat"]
                ):
                    if entry_price:
                        if position == "long":
                            pnl = signal["price"] - entry_price
                        else:
                            pnl = entry_price - signal["price"]
                        test_pnl += pnl
                        if pnl > 0:
                            test_wins += 1
                    position = None
                    entry_price = None

        # Close any open position at end
        if position and entry_price and len(test_df) > 0:
            exit_price = float(test_df["Close"].iloc[-1])
            if position == "long":
                pnl = exit_price - entry_price
            else:
                pnl = entry_price - exit_price
            test_pnl += pnl
            if pnl > 0:
                test_wins += 1

        win_rate = (test_wins / test_trades * 100) if test_trades > 0 else 0.0

        results.append(
            {
                "window": window_num,
                "train_start": current_start,
                "train_end": train_end,
                "test_start": test_start,
                "test_end": test_end,
                "test_trades": test_trades,
                "test_wins": test_wins,
                "win_rate": win_rate,
                "test_pnl": test_pnl,
                "signals_count": len(test_signals),
            }
        )

        window_num += 1
        current_start += timedelta(days=step_days)

    return results


def optimize_parameters(
    df: pd.DataFrame,
    symbol: str,
    strategy_name: str,
    param_grid: dict[str, list[Any]],
    train_period_days: int = 60,
    test_period_days: int = 30,
) -> dict[str, Any]:
    """
    Optimize strategy parameters using walk-forward testing.

    Args:
        df: OHLCV DataFrame
        symbol: Trading symbol
        strategy_name: Strategy name
        param_grid: Parameter grid to search (e.g., {"fast": [10, 20, 30], "slow": [50, 100]})
        train_period_days: Training period
        test_period_days: Testing period

    Returns:
        Best parameters and performance metrics
    """
    from itertools import product

    best_params = None
    best_score = float("-inf")
    best_results = None

    # Generate all parameter combinations
    param_names = list(param_grid.keys())
    param_values = list(param_grid.values())
    param_combinations = list(product(*param_values))

    console.print(
        f"[cyan]Testing {len(param_combinations)} parameter combinations...[/cyan]"
    )

    for combo in param_combinations:
        params = dict(zip(param_names, combo))

        try:
            results = walk_forward_test(
                df=df,
                symbol=symbol,
                strategy_name=strategy_name,
                train_period_days=train_period_days,
                test_period_days=test_period_days,
                strategy_params=params,
            )

            if not results:
                continue

            # Calculate average performance
            avg_pnl = sum(r["test_pnl"] for r in results) / len(results)
            avg_win_rate = sum(r["win_rate"] for r in results) / len(results)

            # Score: weighted combination of P&L and win rate
            score = avg_pnl + (avg_win_rate * 10)  # Win rate weighted by 10

            if score > best_score:
                best_score = score
                best_params = params
                best_results = {
                    "avg_pnl": avg_pnl,
                    "avg_win_rate": avg_win_rate,
                    "total_windows": len(results),
                }
        except Exception as e:
            console.print(f"[red]Error testing params {params}: {e}[/red]")
            continue

    return {
        "best_params": best_params,
        "best_score": best_score,
        "results": best_results,
    }


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Walk-forward testing framework")
    parser.add_argument(
        "--data",
        type=Path,
        required=True,
        help="Path to OHLCV CSV file",
    )
    parser.add_argument(
        "--symbol",
        type=str,
        required=True,
        help="Trading symbol",
    )
    parser.add_argument(
        "--strategy",
        type=str,
        default="sr",
        help="Strategy name (sr, ma_cross, breakout, mean_reversion)",
    )
    parser.add_argument(
        "--train-days",
        type=int,
        default=60,
        help="Training period in days (default: 60)",
    )
    parser.add_argument(
        "--test-days",
        type=int,
        default=30,
        help="Testing period in days (default: 30)",
    )
    parser.add_argument(
        "--step-days",
        type=int,
        default=30,
        help="Step size between windows in days (default: 30)",
    )
    parser.add_argument(
        "--optimize",
        action="store_true",
        help="Run parameter optimization",
    )
    parser.add_argument(
        "--fast",
        type=int,
        nargs="+",
        help="Fast parameter values for optimization (e.g., --fast 10 20 30)",
    )
    parser.add_argument(
        "--slow",
        type=int,
        nargs="+",
        help="Slow parameter values for optimization (e.g., --slow 50 100)",
    )

    args = parser.parse_args()

    # Load data
    if not args.data.exists():
        console.print(f"[red]Data file not found: {args.data}[/red]")
        return 1

    df = pd.read_csv(args.data)
    console.print(f"[green]Loaded {len(df)} rows from {args.data}[/green]")

    if args.optimize:
        # Parameter optimization
        param_grid = {}
        if args.fast:
            param_grid["fast"] = args.fast
        if args.slow:
            param_grid["slow"] = args.slow

        if not param_grid:
            console.print(
                "[yellow]No parameter grid specified. Using default optimization...[/yellow]"
            )
            if args.strategy in ["sr", "ma_cross"]:
                param_grid = {
                    "fast": [10, 20, 30],
                    "slow": [50, 100, 200],
                }

        result = optimize_parameters(
            df=df,
            symbol=args.symbol,
            strategy_name=args.strategy,
            param_grid=param_grid,
            train_period_days=args.train_days,
            test_period_days=args.test_days,
        )

        table = Table(title="Parameter Optimization Results", box=box.ROUNDED)
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="white")

        table.add_row("Best Parameters", str(result["best_params"]))
        table.add_row("Best Score", f"{result['best_score']:.2f}")
        if result["results"]:
            table.add_row("Average P&L", f"${result['results']['avg_pnl']:,.2f}")
            table.add_row(
                "Average Win Rate", f"{result['results']['avg_win_rate']:.1f}%"
            )
            table.add_row("Total Windows", str(result["results"]["total_windows"]))

        console.print(table)
    else:
        # Standard walk-forward test
        results = walk_forward_test(
            df=df,
            symbol=args.symbol,
            strategy_name=args.strategy,
            train_period_days=args.train_days,
            test_period_days=args.test_days,
            step_days=args.step_days,
        )

        if not results:
            console.print(
                "[red]No test windows generated. Check data and parameters.[/red]"
            )
            return 1

        # Display results
        table = Table(
            title="Walk-Forward Test Results", box=box.ROUNDED, header_style="bold cyan"
        )
        table.add_column("Window", justify="right")
        table.add_column("Test Start", style="dim")
        table.add_column("Test End", style="dim")
        table.add_column("Trades", justify="right")
        table.add_column("Wins", justify="right")
        table.add_column("Win Rate", justify="right")
        table.add_column("P&L", justify="right")

        total_pnl = 0.0
        for r in results:
            total_pnl += r["test_pnl"]
            table.add_row(
                str(r["window"]),
                r["test_start"].strftime("%Y-%m-%d"),
                r["test_end"].strftime("%Y-%m-%d"),
                str(r["test_trades"]),
                str(r["test_wins"]),
                f"{r['win_rate']:.1f}%",
                f"${r['test_pnl']:,.2f}",
            )

        console.print(table)

        # Summary
        avg_pnl = total_pnl / len(results) if results else 0.0
        avg_win_rate = (
            sum(r["win_rate"] for r in results) / len(results) if results else 0.0
        )

        summary = Panel(
            f"Total Windows: {len(results)}\n"
            f"Average P&L per Window: ${avg_pnl:,.2f}\n"
            f"Average Win Rate: {avg_win_rate:.1f}%\n"
            f"Total P&L: ${total_pnl:,.2f}",
            title="Summary",
            border_style="green",
        )
        console.print(summary)

    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
