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
)

console = Console()


@click.group()
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
cli.add_command(signals.signals_cmd)
cli.add_command(report.report_cmd)
cli.add_command(trade.trade_group)
cli.add_command(gateway.gateway_group)
cli.add_command(data.data_group)
cli.add_command(setup.setup_cmd)


if __name__ == "__main__":
    cli()

