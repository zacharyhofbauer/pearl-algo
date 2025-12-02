"""Main CLI entry point for PearlAlgo trading system."""

from __future__ import annotations

import click
from rich.console import Console
from rich.panel import Panel
from rich import box

from pearlalgo.cli.commands import (
    status,
    dashboard,
    signals,
    report,
    trade,
    gateway,
    data,
    setup,
    monitor,
    help,
)

console = Console()


def _suggest_command(ctx: click.Context, param: click.Parameter, value: str) -> None:
    """Suggest similar commands on typo."""
    if value is None:
        return
    
    # Get all available commands
    available_commands = list(ctx.command.commands.keys())
    
    # Simple Levenshtein-like suggestion (find closest match)
    def similarity(s1: str, s2: str) -> float:
        """Simple similarity score."""
        s1, s2 = s1.lower(), s2.lower()
        if s1 == s2:
            return 1.0
        if s1 in s2 or s2 in s1:
            return 0.8
        # Count common characters
        common = sum(1 for c in s1 if c in s2)
        return common / max(len(s1), len(s2))
    
    # Find best match
    best_match = None
    best_score = 0.0
    for cmd in available_commands:
        score = similarity(value, cmd)
        if score > best_score and score > 0.5:
            best_score = score
            best_match = cmd
    
    if best_match:
        console.print(f"\n[yellow]💡 Did you mean '[cyan]{best_match}[/cyan]'?[/yellow]\n")


@click.group(invoke_without_command=False)
@click.version_option(version="0.1.0")
@click.option(
    "--verbosity",
    type=click.Choice(["QUIET", "NORMAL", "VERBOSE", "DEBUG"], case_sensitive=False),
    default="NORMAL",
    help="Output verbosity level",
)
@click.pass_context
def cli(ctx: click.Context, verbosity: str) -> None:
    """
    🎯 PearlAlgo Futures Desk — Professional Trading Console
    
    Unified command-line interface for trading operations, monitoring, and management.
    """
    ctx.ensure_object(dict)
    ctx.obj["verbosity"] = verbosity.upper()
    
    # Show banner on first run
    if not ctx.obj.get("banner_shown"):
        console.print()
        console.print(
            Panel.fit(
                "[bold cyan]🎯 PearlAlgo Futures Desk[/bold cyan]\n"
                "[dim]Professional Trading Console[/dim]",
                border_style="cyan",
                box=box.ROUNDED,
            )
        )
        console.print()
        ctx.obj["banner_shown"] = True


# Register command groups
cli.add_command(status.status_cmd)
cli.add_command(dashboard.dashboard_cmd)
cli.add_command(monitor.monitor_cmd)
cli.add_command(signals.signals_cmd)
cli.add_command(report.report_cmd)
cli.add_command(trade.trade_group)
cli.add_command(gateway.gateway_group)
cli.add_command(data.data_group)
cli.add_command(setup.setup_cmd)
cli.add_command(help.help_cmd)
cli.add_command(help.cheat_sheet_cmd)


if __name__ == "__main__":
    cli()

