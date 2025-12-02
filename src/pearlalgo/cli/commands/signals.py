"""Signals command - Generate daily trading signals."""

from __future__ import annotations

import click
import sys
from pathlib import Path

# Import existing script logic
SCRIPT_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent
if str(SCRIPT_DIR / "scripts") not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR / "scripts"))

from scripts import run_daily_signals

from rich.console import Console

console = Console()


@click.command(name="signals")
@click.option(
    "--strategy",
    type=click.Choice(["ma_cross", "sr"]),
    default="sr",
    help="Trading strategy",
)
@click.option(
    "--symbols", multiple=True, default=["ES", "NQ", "GC"], help="Symbols to process"
)
@click.option(
    "--source", type=click.Choice(["ibkr", "csv"]), default="ibkr", help="Data source"
)
@click.pass_context
def signals_cmd(ctx: click.Context, strategy: str, symbols: tuple, source: str) -> None:
    """Generate daily trading signals."""
    verbosity = ctx.obj.get("verbosity", "NORMAL")

    console.print(
        f"\n[bold cyan]📊 Generating Daily Signals ({strategy.upper()} strategy)...[/bold cyan]\n"
    )

    # Build args for run_daily_signals
    args = [
        "--strategy",
        strategy,
        "--source",
        source,
    ]

    if symbols:
        args.extend(["--symbols"] + list(symbols))

    result = run_daily_signals.main(args)

    if result == 0:
        console.print("[bold green]✅ Signals generated successfully![/bold green]\n")
    else:
        console.print("[bold red]❌ Failed to generate signals[/bold red]\n")

    raise SystemExit(result)
