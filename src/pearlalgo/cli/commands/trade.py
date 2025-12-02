"""Trading commands - Paper trading, automated trading, risk monitoring."""

from __future__ import annotations

import click
import sys
from pathlib import Path

from rich.console import Console
from pearlalgo.strategies.base import list_strategies

console = Console()

# Get available strategies dynamically
_AVAILABLE_STRATEGIES = list_strategies()
# Add legacy strategies if not already registered
if "sr" not in _AVAILABLE_STRATEGIES:
    _AVAILABLE_STRATEGIES.append("sr")
if "ma_cross" not in _AVAILABLE_STRATEGIES:
    _AVAILABLE_STRATEGIES.append("ma_cross")


@click.group(name="trade")
@click.pass_context
def trade_group(ctx: click.Context) -> None:
    """Trading operations (paper trading, automated trading, risk monitoring)."""
    pass


@trade_group.command(name="paper")
@click.option(
    "--symbols", multiple=True, default=["ES", "NQ", "GC"], help="Symbols to trade"
)
@click.option(
    "--strategy",
    type=str,
    default="sr",
    help=f"Trading strategy (available: {', '.join(_AVAILABLE_STRATEGIES)})",
)
@click.option("--interval", type=int, default=300, help="Loop interval in seconds")
@click.option("--tiny-size", type=int, default=1, help="Base contract size")
@click.pass_context
def paper_cmd(
    ctx: click.Context, symbols: tuple, strategy: str, interval: int, tiny_size: int
) -> None:
    """Start paper trading loop."""
    verbosity = ctx.obj.get("verbosity", "NORMAL")

    # Import and run existing script
    SCRIPT_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent
    if str(SCRIPT_DIR / "scripts") not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR / "scripts"))

    from scripts import live_paper_loop

    args = (
        ["--symbols"]
        + list(symbols)
        + [
            "--strategy",
            strategy,
            "--interval",
            str(interval),
            "--tiny-size",
            str(tiny_size),
            "--mode",
            "ibkr-paper",
        ]
    )

    console.print("\n[bold cyan]🔄 Starting Paper Trading Loop...[/bold cyan]\n")
    console.print(f"Symbols: {', '.join(symbols)}")
    console.print(f"Strategy: {strategy}")
    console.print(f"Interval: {interval}s\n")

    raise SystemExit(live_paper_loop.main(args))


@trade_group.command(name="auto")
@click.option(
    "--symbols",
    multiple=True,
    default=[],
    help="Symbols to trade (repeat --symbols for each, or pass as arguments)",
)
@click.option(
    "--strategy",
    type=str,
    default="sr",
    help=f"Trading strategy (available: {', '.join(_AVAILABLE_STRATEGIES)})",
)
@click.option("--interval", type=int, default=300, help="Loop interval in seconds")
@click.option("--tiny-size", type=int, default=1, help="Base contract size")
@click.option(
    "--profile-config",
    type=click.Path(exists=True),
    help="Profile config file (YAML/JSON)",
)
@click.option("--ib-client-id", type=int, help="IB Gateway client ID override")
@click.option("--log-file", type=click.Path(), help="Log file path")
@click.option(
    "--log-level",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"]),
    default="INFO",
    help="Log level",
)
@click.argument("symbol_args", nargs=-1, required=False)
@click.pass_context
def auto_cmd(
    ctx: click.Context,
    symbols: tuple,
    strategy: str,
    interval: int,
    tiny_size: int,
    profile_config: str | None,
    ib_client_id: int | None,
    log_file: str | None,
    log_level: str,
    symbol_args: tuple,
) -> None:
    """Start automated trading agent.

    Examples:
        pearlalgo trade auto ES NQ GC
        pearlalgo trade auto --symbols ES --symbols NQ --symbols GC
        pearlalgo trade auto ES NQ GC --strategy sr --interval 300
        pearlalgo trade auto MES MNQ --strategy scalping --interval 60
        pearlalgo trade auto ES NQ --strategy intraday_swing --interval 900
    """
    verbosity = ctx.obj.get("verbosity", "NORMAL")

    # Validate strategy
    if strategy not in _AVAILABLE_STRATEGIES:
        console.print(
            f"[yellow]⚠️  Warning: Strategy '{strategy}' not in registered strategies.[/yellow]"
        )
        console.print(
            f"[dim]Available strategies: {', '.join(_AVAILABLE_STRATEGIES)}[/dim]"
        )
        console.print(
            "[dim]Continuing anyway - strategy may be handled by signal generator...[/dim]\n"
        )

    # Combine symbols from --symbols option and positional arguments
    all_symbols = list(symbols) + list(symbol_args)

    # If no symbols provided, use defaults
    if not all_symbols:
        all_symbols = ["ES", "NQ", "GC"]

    # Remove duplicates while preserving order
    seen = set()
    unique_symbols = []
    for s in all_symbols:
        if s not in seen:
            seen.add(s)
            unique_symbols.append(s)

    # Import and run existing script
    SCRIPT_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent
    if str(SCRIPT_DIR / "scripts") not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR / "scripts"))

    from scripts import automated_trading

    args = (
        ["--symbols"]
        + unique_symbols
        + [
            "--strategy",
            strategy,
            "--interval",
            str(interval),
            "--tiny-size",
            str(tiny_size),
        ]
    )

    if profile_config:
        args.extend(["--profile-config", profile_config])

    if ib_client_id:
        args.extend(["--ib-client-id", str(ib_client_id)])

    if log_file:
        args.extend(["--log-file", log_file])

    if log_level:
        args.extend(["--log-level", log_level])

    console.print("\n[bold cyan]🤖 Starting Automated Trading Agent...[/bold cyan]\n")
    console.print(f"Symbols: {', '.join(unique_symbols)}")
    console.print(f"Strategy: {strategy}")
    console.print(f"Interval: {interval}s")
    console.print(f"Contract Size: {tiny_size}")
    if profile_config:
        console.print(f"Profile: {profile_config}")
    if ib_client_id:
        console.print(f"IB Client ID: {ib_client_id}")
    if log_file:
        console.print(f"Log File: {log_file}")
    if log_level:
        console.print(f"Log Level: {log_level}")
    console.print()

    raise SystemExit(automated_trading.main(args))


@trade_group.command(name="monitor")
@click.option(
    "--max-daily-loss", type=float, required=True, help="Maximum daily loss limit"
)
@click.option("--interval", type=int, default=60, help="Check interval in seconds")
@click.pass_context
def monitor_cmd(ctx: click.Context, max_daily_loss: float, interval: int) -> None:
    """Monitor risk limits and halt trading if breached."""
    verbosity = ctx.obj.get("verbosity", "NORMAL")

    # Import and run existing script
    SCRIPT_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent
    if str(SCRIPT_DIR / "scripts") not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR / "scripts"))

    from scripts import risk_monitor

    args = [
        "--max-daily-loss",
        str(max_daily_loss),
        "--interval",
        str(interval),
    ]

    console.print("\n[bold cyan]⚠️  Starting Risk Monitor...[/bold cyan]\n")
    console.print(f"Max Daily Loss: ${max_daily_loss:,.2f}")
    console.print(f"Check Interval: {interval}s\n")

    raise SystemExit(risk_monitor.main(args))
