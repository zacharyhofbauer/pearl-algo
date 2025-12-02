"""Python SDK-style interactive terminal command."""
from __future__ import annotations

import click
from rich.console import Console

from pearlalgo.cli.interactive_terminal import TradingSDK

console = Console()


@click.command(name="sdk")
@click.option("--dashboard", is_flag=True, help="Start live dashboard mode")
@click.option("--refresh", type=float, default=2.0, help="Dashboard refresh rate in seconds")
@click.pass_context
def sdk_cmd(ctx: click.Context, dashboard: bool, refresh: float) -> None:
    """Python SDK-style interactive trading terminal.
    
    Interactive mode with commands:
    - positions: Show open positions
    - performance: Show performance metrics
    - trades: Show recent trades
    - dashboard: Show live updating dashboard
    - help: Show available commands
    - exit: Exit interactive mode
    
    Examples:
        pearlalgo sdk                    # Interactive mode
        pearlalgo sdk --dashboard        # Live dashboard mode
        pearlalgo sdk --dashboard --refresh 1.0  # Dashboard with 1s refresh
    """
    sdk = TradingSDK()
    
    if dashboard:
        sdk.dashboard(refresh=refresh)
    else:
        sdk.interactive()



