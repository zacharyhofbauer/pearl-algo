#!/usr/bin/env python
"""
Backtest Validation Script
Compares backtest results with paper trading results to validate strategy consistency.
"""

from __future__ import annotations

import argparse
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
)

console = Console()


def compare_backtest_paper(
    backtest_results: pd.DataFrame,
    paper_results: pd.DataFrame,
    tolerance_pct: float = 20.0,
) -> dict[str, Any]:
    """
    Compare backtest results with paper trading results.

    Args:
        backtest_results: Backtest performance DataFrame
        paper_results: Paper trading performance DataFrame
        tolerance_pct: Tolerance percentage for differences (default: 20%)

    Returns:
        Comparison metrics and discrepancies
    """
    comparison = {
        "backtest_trades": 0,
        "paper_trades": 0,
        "backtest_pnl": 0.0,
        "paper_pnl": 0.0,
        "backtest_win_rate": 0.0,
        "paper_win_rate": 0.0,
        "backtest_profit_factor": 0.0,
        "paper_profit_factor": 0.0,
        "pnl_difference": 0.0,
        "pnl_difference_pct": 0.0,
        "win_rate_difference": 0.0,
        "discrepancies": [],
    }

    # Process backtest results
    if not backtest_results.empty and "realized_pnl" in backtest_results.columns:
        backtest_trades = backtest_results.dropna(subset=["realized_pnl"])
        comparison["backtest_trades"] = len(backtest_trades)
        comparison["backtest_pnl"] = float(backtest_trades["realized_pnl"].sum())
        backtest_wins = backtest_trades[backtest_trades["realized_pnl"] > 0]
        comparison["backtest_win_rate"] = (
            (len(backtest_wins) / len(backtest_trades) * 100)
            if len(backtest_trades) > 0
            else 0.0
        )
        comparison["backtest_profit_factor"] = calculate_profit_factor(backtest_trades)

    # Process paper results
    if not paper_results.empty and "realized_pnl" in paper_results.columns:
        paper_trades = paper_results.dropna(subset=["realized_pnl"])
        comparison["paper_trades"] = len(paper_trades)
        comparison["paper_pnl"] = float(paper_trades["realized_pnl"].sum())
        paper_wins = paper_trades[paper_trades["realized_pnl"] > 0]
        comparison["paper_win_rate"] = (
            (len(paper_wins) / len(paper_trades) * 100)
            if len(paper_trades) > 0
            else 0.0
        )
        comparison["paper_profit_factor"] = calculate_profit_factor(paper_trades)

    # Calculate differences
    comparison["pnl_difference"] = comparison["backtest_pnl"] - comparison["paper_pnl"]
    if comparison["paper_pnl"] != 0:
        comparison["pnl_difference_pct"] = (
            abs(comparison["pnl_difference"]) / abs(comparison["paper_pnl"]) * 100
        )
    comparison["win_rate_difference"] = (
        comparison["backtest_win_rate"] - comparison["paper_win_rate"]
    )

    # Identify discrepancies
    if comparison["pnl_difference_pct"] > tolerance_pct:
        comparison["discrepancies"].append(
            f"P&L difference ({comparison['pnl_difference_pct']:.1f}%) exceeds tolerance ({tolerance_pct}%)"
        )

    if abs(comparison["win_rate_difference"]) > tolerance_pct:
        comparison["discrepancies"].append(
            f"Win rate difference ({abs(comparison['win_rate_difference']):.1f}%) exceeds tolerance ({tolerance_pct}%)"
        )

    if (
        abs(comparison["backtest_trades"] - comparison["paper_trades"])
        > comparison["paper_trades"] * 0.2
    ):
        comparison["discrepancies"].append(
            f"Trade count mismatch: backtest={comparison['backtest_trades']}, paper={comparison['paper_trades']}"
        )

    return comparison


def validate_signal_consistency(
    backtest_signals: pd.DataFrame,
    paper_signals: pd.DataFrame,
    time_window_seconds: int = 300,
) -> dict[str, Any]:
    """
    Validate that signals generated in backtest match paper trading signals.

    Args:
        backtest_signals: Backtest signals DataFrame
        paper_signals: Paper trading signals DataFrame
        time_window_seconds: Time window for matching signals (default: 5 minutes)

    Returns:
        Signal consistency metrics
    """
    if backtest_signals.empty or paper_signals.empty:
        return {
            "backtest_signals": 0,
            "paper_signals": 0,
            "matched_signals": 0,
            "match_rate": 0.0,
            "mismatches": [],
        }

    backtest_signals = backtest_signals.copy()
    paper_signals = paper_signals.copy()

    if (
        "timestamp" not in backtest_signals.columns
        or "timestamp" not in paper_signals.columns
    ):
        return {
            "backtest_signals": len(backtest_signals),
            "paper_signals": len(paper_signals),
            "matched_signals": 0,
            "match_rate": 0.0,
            "mismatches": [],
        }

    backtest_signals["timestamp"] = pd.to_datetime(backtest_signals["timestamp"])
    paper_signals["timestamp"] = pd.to_datetime(paper_signals["timestamp"])

    matched = 0
    mismatches = []

    for _, backtest_sig in backtest_signals.iterrows():
        # Find matching paper signal within time window
        time_diff = abs(
            (paper_signals["timestamp"] - backtest_sig["timestamp"]).dt.total_seconds()
        )
        matches = paper_signals[time_diff <= time_window_seconds]

        if len(matches) > 0:
            # Check if side matches
            paper_side = matches.iloc[0].get("side", "flat")
            backtest_side = backtest_sig.get("side", "flat")

            if paper_side.lower() == backtest_side.lower():
                matched += 1
            else:
                mismatches.append(
                    {
                        "timestamp": backtest_sig["timestamp"],
                        "backtest_side": backtest_side,
                        "paper_side": paper_side,
                    }
                )
        else:
            mismatches.append(
                {
                    "timestamp": backtest_sig["timestamp"],
                    "backtest_side": backtest_sig.get("side", "flat"),
                    "paper_side": "NO_MATCH",
                }
            )

    match_rate = (
        (matched / len(backtest_signals) * 100) if len(backtest_signals) > 0 else 0.0
    )

    return {
        "backtest_signals": len(backtest_signals),
        "paper_signals": len(paper_signals),
        "matched_signals": matched,
        "match_rate": match_rate,
        "mismatches": mismatches[:10],  # Limit to first 10
    }


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Validate backtest results against paper trading"
    )
    parser.add_argument(
        "--backtest",
        type=Path,
        required=True,
        help="Path to backtest results CSV",
    )
    parser.add_argument(
        "--paper",
        type=Path,
        default=DEFAULT_PERF_PATH,
        help="Path to paper trading performance CSV (default: data/performance/futures_decisions.csv)",
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=20.0,
        help="Tolerance percentage for differences (default: 20%)",
    )
    parser.add_argument(
        "--signals",
        action="store_true",
        help="Also validate signal consistency",
    )
    parser.add_argument(
        "--backtest-signals",
        type=Path,
        help="Path to backtest signals CSV (required if --signals)",
    )
    parser.add_argument(
        "--paper-signals",
        type=Path,
        help="Path to paper trading signals CSV (required if --signals)",
    )

    args = parser.parse_args()

    # Load backtest results
    if not args.backtest.exists():
        console.print(f"[red]Backtest file not found: {args.backtest}[/red]")
        return 1

    backtest_df = pd.read_csv(args.backtest)
    backtest_df = calculate_enhanced_metrics(backtest_df)
    console.print(f"[green]Loaded {len(backtest_df)} backtest results[/green]")

    # Load paper results
    if not args.paper.exists():
        console.print(f"[yellow]Paper trading file not found: {args.paper}[/yellow]")
        console.print("[yellow]Creating empty comparison...[/yellow]")
        paper_df = pd.DataFrame()
    else:
        paper_df = load_performance(args.paper)
        paper_df = calculate_enhanced_metrics(paper_df)
        console.print(f"[green]Loaded {len(paper_df)} paper trading results[/green]")

    # Compare results
    comparison = compare_backtest_paper(
        backtest_df, paper_df, tolerance_pct=args.tolerance
    )

    # Display comparison
    table = Table(
        title="Backtest vs Paper Trading Comparison",
        box=box.ROUNDED,
        header_style="bold cyan",
    )
    table.add_column("Metric", style="cyan", width=25)
    table.add_column("Backtest", justify="right", width=15)
    table.add_column("Paper", justify="right", width=15)
    table.add_column("Difference", justify="right", width=15)

    table.add_row(
        "Total Trades",
        str(comparison["backtest_trades"]),
        str(comparison["paper_trades"]),
        str(comparison["backtest_trades"] - comparison["paper_trades"]),
    )
    table.add_row(
        "Total P&L",
        f"${comparison['backtest_pnl']:,.2f}",
        f"${comparison['paper_pnl']:,.2f}",
        f"${comparison['pnl_difference']:,.2f}",
    )
    table.add_row(
        "Win Rate",
        f"{comparison['backtest_win_rate']:.1f}%",
        f"{comparison['paper_win_rate']:.1f}%",
        f"{comparison['win_rate_difference']:.1f}%",
    )
    table.add_row(
        "Profit Factor",
        f"{comparison['backtest_profit_factor']:.2f}",
        f"{comparison['paper_profit_factor']:.2f}",
        f"{comparison['backtest_profit_factor'] - comparison['paper_profit_factor']:.2f}",
    )

    console.print(table)

    # Display discrepancies
    if comparison["discrepancies"]:
        discrepancy_text = "\n".join(f"• {d}" for d in comparison["discrepancies"])
        console.print(
            Panel(
                discrepancy_text, title="⚠️  Discrepancies Found", border_style="yellow"
            )
        )
    else:
        console.print(
            Panel(
                "✅ No significant discrepancies found",
                title="Validation",
                border_style="green",
            )
        )

    # Signal consistency validation
    if args.signals:
        if not args.backtest_signals or not args.backtest_signals.exists():
            console.print(
                "[yellow]Backtest signals file not provided or not found. Skipping signal validation.[/yellow]"
            )
        elif not args.paper_signals or not args.paper_signals.exists():
            console.print(
                "[yellow]Paper signals file not provided or not found. Skipping signal validation.[/yellow]"
            )
        else:
            backtest_sigs = pd.read_csv(args.backtest_signals)
            paper_sigs = pd.read_csv(args.paper_signals)

            signal_validation = validate_signal_consistency(backtest_sigs, paper_sigs)

            sig_table = Table(title="Signal Consistency Validation", box=box.ROUNDED)
            sig_table.add_column("Metric", style="cyan")
            sig_table.add_column("Value", justify="right")

            sig_table.add_row(
                "Backtest Signals", str(signal_validation["backtest_signals"])
            )
            sig_table.add_row("Paper Signals", str(signal_validation["paper_signals"]))
            sig_table.add_row(
                "Matched Signals", str(signal_validation["matched_signals"])
            )
            sig_table.add_row("Match Rate", f"{signal_validation['match_rate']:.1f}%")

            console.print(sig_table)

            if signal_validation["mismatches"]:
                console.print(
                    f"[yellow]Found {len(signal_validation['mismatches'])} signal mismatches (showing first 10)[/yellow]"
                )

    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
