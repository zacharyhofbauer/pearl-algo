#!/usr/bin/env python
"""
Performance Analysis Script
Generates detailed performance reports from trading data.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

from pearlalgo.futures.performance import (
    DEFAULT_PERF_PATH,
    load_performance,
    calculate_enhanced_metrics,
    calculate_profit_factor,
    summarize_daily_performance,
)

console = Console()


def analyze_trade_patterns(df: pd.DataFrame) -> dict[str, Any]:
    """Analyze patterns in trading data."""
    if df.empty:
        return {}

    patterns = {}

    # Time of day analysis
    if "time_of_day_hour" in df.columns:
        hour_pnl = (
            df.groupby("time_of_day_hour")["realized_pnl"]
            .agg(["sum", "mean", "count"])
            .to_dict()
        )
        patterns["hourly_performance"] = hour_pnl

    # Day of week analysis
    if "day_of_week" in df.columns:
        dow_pnl = (
            df.groupby("day_of_week")["realized_pnl"]
            .agg(["sum", "mean", "count"])
            .to_dict()
        )
        patterns["day_of_week_performance"] = dow_pnl

    # Strategy performance
    if "strategy_name" in df.columns:
        strategy_perf = (
            df.groupby("strategy_name")
            .agg(
                {
                    "realized_pnl": ["sum", "mean", "count"],
                    "hold_time_minutes": "mean",
                }
            )
            .to_dict()
        )
        patterns["strategy_performance"] = strategy_perf

    # Symbol performance
    if "symbol" in df.columns:
        symbol_perf = (
            df.groupby("symbol")
            .agg(
                {
                    "realized_pnl": ["sum", "mean", "count"],
                }
            )
            .to_dict()
        )
        patterns["symbol_performance"] = symbol_perf

    return patterns


def find_best_worst_trades(
    df: pd.DataFrame, n: int = 5
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Find best and worst trades."""
    if df.empty or "realized_pnl" not in df.columns:
        return pd.DataFrame(), pd.DataFrame()

    trades = df.dropna(subset=["realized_pnl"]).copy()
    if trades.empty:
        return pd.DataFrame(), pd.DataFrame()

    best = trades.nlargest(n, "realized_pnl")[
        [
            "timestamp",
            "symbol",
            "strategy_name",
            "side",
            "entry_price",
            "exit_price",
            "realized_pnl",
            "hold_time_minutes",
        ]
    ]
    worst = trades.nsmallest(n, "realized_pnl")[
        [
            "timestamp",
            "symbol",
            "strategy_name",
            "side",
            "entry_price",
            "exit_price",
            "realized_pnl",
            "hold_time_minutes",
        ]
    ]

    return best, worst


def create_performance_report(
    df: pd.DataFrame,
    date_range: tuple[datetime, datetime] | None = None,
    output_file: Path | None = None,
) -> str:
    """Create comprehensive performance report."""
    if df.empty:
        return "No trading data available."

    # Filter by date range if provided
    if date_range:
        start_date, end_date = date_range
        df = df[(df["timestamp"] >= start_date) & (df["timestamp"] <= end_date)]

    if df.empty:
        return "No trading data in specified date range."

    # Calculate enhanced metrics
    df = calculate_enhanced_metrics(df)

    # Get completed trades
    trades = df.dropna(subset=["realized_pnl"]).copy()

    report_lines = []
    report_lines.append("=" * 80)
    report_lines.append("PERFORMANCE ANALYSIS REPORT")
    report_lines.append("=" * 80)
    report_lines.append(f"Generated: {datetime.now(timezone.utc).isoformat()}")
    report_lines.append(
        f"Date Range: {df['timestamp'].min()} to {df['timestamp'].max()}"
    )
    report_lines.append("")

    # Overall Statistics
    report_lines.append("OVERALL STATISTICS")
    report_lines.append("-" * 80)
    if not trades.empty:
        total_trades = len(trades)
        wins = trades[trades["realized_pnl"] > 0]
        losses = trades[trades["realized_pnl"] < 0]
        win_rate = (len(wins) / total_trades * 100) if total_trades > 0 else 0.0

        total_pnl = trades["realized_pnl"].sum()
        avg_pnl = trades["realized_pnl"].mean()
        largest_winner = trades["realized_pnl"].max()
        largest_loser = trades["realized_pnl"].min()

        profit_factor = calculate_profit_factor(trades)

        avg_hold_time = (
            trades["hold_time_minutes"].mean()
            if "hold_time_minutes" in trades.columns
            else 0.0
        )

        report_lines.append(f"Total Trades: {total_trades}")
        report_lines.append(f"Winners: {len(wins)} ({win_rate:.1f}%)")
        report_lines.append(f"Losers: {len(losses)} ({100 - win_rate:.1f}%)")
        report_lines.append(f"Total P&L: ${total_pnl:,.2f}")
        report_lines.append(f"Average P&L per Trade: ${avg_pnl:,.2f}")
        report_lines.append(f"Largest Winner: ${largest_winner:,.2f}")
        report_lines.append(f"Largest Loser: ${largest_loser:,.2f}")
        report_lines.append(f"Profit Factor: {profit_factor:.2f}")
        report_lines.append(f"Average Hold Time: {avg_hold_time:.1f} minutes")
    else:
        report_lines.append("No completed trades found.")

    report_lines.append("")

    # Strategy Performance
    if "strategy_name" in df.columns and not trades.empty:
        report_lines.append("STRATEGY PERFORMANCE")
        report_lines.append("-" * 80)
        strategy_stats = []
        for strategy in trades["strategy_name"].dropna().unique():
            strat_trades = trades[trades["strategy_name"] == strategy]
            strat_wins = strat_trades[strat_trades["realized_pnl"] > 0]
            strat_pnl = strat_trades["realized_pnl"].sum()
            strat_win_rate = (
                (len(strat_wins) / len(strat_trades) * 100)
                if len(strat_trades) > 0
                else 0.0
            )
            strat_pf = calculate_profit_factor(strat_trades)

            strategy_stats.append(
                {
                    "strategy": strategy,
                    "trades": len(strat_trades),
                    "win_rate": strat_win_rate,
                    "total_pnl": strat_pnl,
                    "profit_factor": strat_pf,
                }
            )

        # Sort by total P&L
        strategy_stats.sort(key=lambda x: x["total_pnl"], reverse=True)

        for stat in strategy_stats:
            report_lines.append(
                f"{stat['strategy']:20s} | Trades: {stat['trades']:3d} | "
                f"Win Rate: {stat['win_rate']:5.1f}% | P&L: ${stat['total_pnl']:10,.2f} | "
                f"PF: {stat['profit_factor']:.2f}"
            )
        report_lines.append("")

    # Symbol Performance
    if "symbol" in df.columns and not trades.empty:
        report_lines.append("SYMBOL PERFORMANCE")
        report_lines.append("-" * 80)
        symbol_stats = []
        for symbol in trades["symbol"].dropna().unique():
            sym_trades = trades[trades["symbol"] == symbol]
            sym_pnl = sym_trades["realized_pnl"].sum()
            sym_win_rate = (
                (
                    len(sym_trades[sym_trades["realized_pnl"] > 0])
                    / len(sym_trades)
                    * 100
                )
                if len(sym_trades) > 0
                else 0.0
            )

            symbol_stats.append(
                {
                    "symbol": symbol,
                    "trades": len(sym_trades),
                    "win_rate": sym_win_rate,
                    "total_pnl": sym_pnl,
                }
            )

        symbol_stats.sort(key=lambda x: x["total_pnl"], reverse=True)

        for stat in symbol_stats:
            report_lines.append(
                f"{stat['symbol']:10s} | Trades: {stat['trades']:3d} | "
                f"Win Rate: {stat['win_rate']:5.1f}% | P&L: ${stat['total_pnl']:10,.2f}"
            )
        report_lines.append("")

    # Time Patterns
    if "time_of_day_hour" in trades.columns and not trades.empty:
        report_lines.append("TIME OF DAY ANALYSIS")
        report_lines.append("-" * 80)
        hourly = trades.groupby("time_of_day_hour")["realized_pnl"].agg(
            ["sum", "mean", "count"]
        )
        for hour, row in hourly.iterrows():
            report_lines.append(
                f"Hour {int(hour):02d}:00 | Trades: {int(row['count']):3d} | "
                f"Total P&L: ${row['sum']:10,.2f} | Avg P&L: ${row['mean']:8,.2f}"
            )
        report_lines.append("")

    # Best/Worst Trades
    if not trades.empty:
        best, worst = find_best_worst_trades(trades, n=5)

        if not best.empty:
            report_lines.append("BEST 5 TRADES")
            report_lines.append("-" * 80)
            for _, trade in best.iterrows():
                report_lines.append(
                    f"{trade['timestamp']} | {trade['symbol']} | {trade['strategy_name']} | "
                    f"{trade['side']} | Entry: ${trade['entry_price']:.2f} | "
                    f"Exit: ${trade['exit_price']:.2f} | P&L: ${trade['realized_pnl']:,.2f}"
                )
            report_lines.append("")

        if not worst.empty:
            report_lines.append("WORST 5 TRADES")
            report_lines.append("-" * 80)
            for _, trade in worst.iterrows():
                report_lines.append(
                    f"{trade['timestamp']} | {trade['symbol']} | {trade['strategy_name']} | "
                    f"{trade['side']} | Entry: ${trade['entry_price']:.2f} | "
                    f"Exit: ${trade['exit_price']:.2f} | P&L: ${trade['realized_pnl']:,.2f}"
                )
            report_lines.append("")

    report = "\n".join(report_lines)

    # Write to file if specified
    if output_file:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(report)
        console.print(f"[green]Report written to: {output_file}[/green]")

    return report


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Analyze trading performance")
    parser.add_argument(
        "--path",
        type=Path,
        default=DEFAULT_PERF_PATH,
        help="Path to performance CSV file",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="Number of days to analyze (default: all)",
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Specific date to analyze (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output file path for report",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Show summary only",
    )

    args = parser.parse_args()

    # Load data
    df = load_performance(args.path)
    if df.empty:
        console.print("[red]No performance data found.[/red]")
        return 1

    # Filter by date if specified
    date_range = None
    if args.days:
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=args.days)
        date_range = (start_date, end_date)
    elif args.date:
        date_obj = pd.to_datetime(args.date).date()
        start_date = datetime.combine(date_obj, datetime.min.time()).replace(
            tzinfo=timezone.utc
        )
        end_date = datetime.combine(date_obj, datetime.max.time()).replace(
            tzinfo=timezone.utc
        )
        date_range = (start_date, end_date)

    if args.summary:
        # Show summary only
        if args.date:
            summary = summarize_daily_performance(args.path, args.date)
        else:
            summary = summarize_daily_performance(args.path)

        table = Table(title="Performance Summary", box=box.ROUNDED)
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="white", justify="right")

        for key, value in summary.items():
            if isinstance(value, float):
                if "rate" in key or "factor" in key:
                    table.add_row(key.replace("_", " ").title(), f"{value:.2f}")
                elif "time" in key:
                    table.add_row(key.replace("_", " ").title(), f"{value:.1f} min")
                else:
                    table.add_row(key.replace("_", " ").title(), f"${value:,.2f}")
            else:
                table.add_row(key.replace("_", " ").title(), str(value))

        console.print(table)
    else:
        # Full report
        report = create_performance_report(
            df, date_range=date_range, output_file=args.output
        )
        console.print(Panel(report, title="Performance Analysis", border_style="cyan"))

    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
