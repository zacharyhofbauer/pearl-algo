#!/usr/bin/env python
"""
Check API communication logs for successful order execution
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add project root to path
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rich.console import Console  # noqa: E402
from rich.table import Table
from rich.panel import Panel
from rich import box

console = Console()


def check_logs():
    """Check all logs for API communication evidence."""
    console.print("\n[bold cyan]📋 Checking API Communication Logs...[/bold cyan]\n")

    log_files = [
        ("test_trading.log", "logs/test_trading.log"),
        ("micro_trading.log", "logs/micro_trading.log"),
        ("micro_console.log", "logs/micro_console.log"),
    ]

    success_indicators = [
        "SUBMITTING LIVE ORDER",
        "Order placed successfully",
        "OrderID=",
        "FILLED",
        "Fill",
        "execution",
        "Connected",
        "API connection ready",
        "Logged on to server",
    ]

    error_indicators = [
        "Error",
        "Failed",
        "Cancelled",
        "Rejected",
        "10349",
    ]

    results = []

    for log_name, log_path in log_files:
        log_file = PROJECT_ROOT / log_path
        if not log_file.exists():
            continue

        console.print(f"[bold]Checking {log_name}...[/bold]")

        try:
            with open(log_file, "r") as f:
                lines = f.readlines()

            # Check last 500 lines
            recent_lines = lines[-500:] if len(lines) > 500 else lines

            success_count = 0
            error_count = 0
            success_examples = []
            error_examples = []

            for line in recent_lines:
                line_lower = line.lower()

                # Count successes
                for indicator in success_indicators:
                    if indicator.lower() in line_lower:
                        success_count += 1
                        if len(success_examples) < 5:
                            success_examples.append(line.strip()[:150])
                        break

                # Count errors
                for indicator in error_indicators:
                    if indicator.lower() in line_lower:
                        error_count += 1
                        if len(error_examples) < 5:
                            error_examples.append(line.strip()[:150])
                        break

            results.append(
                {
                    "file": log_name,
                    "lines": len(lines),
                    "success": success_count,
                    "errors": error_count,
                    "success_examples": success_examples,
                    "error_examples": error_examples,
                }
            )

        except Exception as e:
            console.print(f"  [red]Error reading {log_name}: {e}[/red]")

    # Display results
    if not results:
        console.print("[yellow]No log files found[/yellow]\n")
        return

    table = Table(
        title="Log Analysis",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Log File", style="yellow")
    table.add_column("Total Lines", justify="right")
    table.add_column("Success Indicators", justify="right", style="green")
    table.add_column("Error Indicators", justify="right", style="red")

    for result in results:
        table.add_row(
            result["file"],
            str(result["lines"]),
            str(result["success"]),
            str(result["errors"]),
        )

    console.print(table)
    console.print()

    # Show success examples
    console.print("[bold green]✅ Success Indicators Found:[/bold green]\n")
    for result in results:
        if result["success_examples"]:
            console.print(f"[bold]{result['file']}:[/bold]")
            for example in result["success_examples"]:
                console.print(f"  [green]✓[/green] {example}")
            console.print()

    # Show error examples
    if any(r["error_examples"] for r in results):
        console.print("[bold yellow]⚠️  Error Indicators Found:[/bold yellow]\n")
        for result in results:
            if result["error_examples"]:
                console.print(f"[bold]{result['file']}:[/bold]")
                for example in result["error_examples"]:
                    console.print(f"  [yellow]⚠[/yellow] {example}")
                console.print()

    # Check for specific order execution evidence
    console.print(
        "[bold cyan]🔍 Searching for Order Execution Evidence...[/bold cyan]\n"
    )

    for log_name, log_path in log_files:
        log_file = PROJECT_ROOT / log_path
        if not log_file.exists():
            continue

        try:
            with open(log_file, "r") as f:
                content = f.read()

            # Look for specific patterns
            patterns = {
                "Order placed successfully": content.count("Order placed successfully")
                + content.count("OrderID="),
                "API connection ready": content.count("API connection ready"),
                "Logged on to server": content.count("Logged on to server"),
                "Fills/Executions": content.count("Fill") + content.count("execution"),
            }

            if any(count > 0 for count in patterns.values()):
                console.print(f"[bold]{log_name}:[/bold]")
                for pattern, count in patterns.items():
                    if count > 0:
                        console.print(
                            f"  [green]✓[/green] {pattern}: {count} occurrences"
                        )
                console.print()

        except Exception:
            pass


def check_ibkr_connection_logs():
    """Check for IBKR connection and API communication."""
    console.print("[bold cyan]🔌 Checking IBKR Connection Logs...[/bold cyan]\n")

    log_files = [
        "logs/test_trading.log",
        "logs/micro_trading.log",
    ]

    connection_evidence = []

    for log_path in log_files:
        log_file = PROJECT_ROOT / log_path
        if not log_file.exists():
            continue

        try:
            with open(log_file, "r") as f:
                lines = f.readlines()

            # Look for connection evidence in last 200 lines
            for line in lines[-200:]:
                if any(
                    indicator in line
                    for indicator in [
                        "Connected to",
                        "API connection ready",
                        "Logged on to server",
                        "SUBMITTING LIVE ORDER",
                        "Order placed successfully",
                        "OrderID=",
                    ]
                ):
                    connection_evidence.append((log_path, line.strip()[:200]))

        except Exception:
            pass

    if connection_evidence:
        console.print("[green]✅ Found connection/execution evidence:[/green]\n")
        for log_path, evidence in connection_evidence[-10:]:  # Show last 10
            console.print(f"  [dim]{log_path}:[/dim] {evidence}")
        console.print()
    else:
        console.print(
            "[yellow]⚠️  No clear connection/execution evidence in logs[/yellow]\n"
        )


if __name__ == "__main__":
    console.print()
    console.print(
        Panel.fit(
            "[bold cyan]📋 API Communication Log Checker[/bold cyan]\n"
            "[dim]Analyzing logs for successful API communication[/dim]",
            border_style="cyan",
            box=box.ROUNDED,
        )
    )

    check_logs()
    check_ibkr_connection_logs()

    console.print("[bold]Summary:[/bold]")
    console.print(
        "  - Check above for 'SUBMITTING LIVE ORDER' and 'Order placed successfully'"
    )
    console.print("  - These indicate successful API communication")
    console.print("  - 'OrderID=' confirms orders were accepted by IB Gateway")
    console.print()
