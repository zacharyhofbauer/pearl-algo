"""Data commands - Download and validate market data."""

from __future__ import annotations

import click
import sys
from pathlib import Path

from rich.console import Console

console = Console()


@click.group(name="data")
@click.pass_context
def data_group(ctx: click.Context) -> None:
    """Data operations (download, validate)."""
    pass


@data_group.command(name="download")
@click.pass_context
def download_cmd(ctx: click.Context) -> None:
    """Download historical data from IBKR."""
    verbosity = ctx.obj.get("verbosity", "NORMAL")

    # Import and run existing script
    SCRIPT_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent
    if str(SCRIPT_DIR / "scripts") not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR / "scripts"))

    from scripts import ibkr_download_data

    console.print("\n[bold cyan]📥 Downloading Historical Data...[/bold cyan]\n")

    raise SystemExit(ibkr_download_data.main())


@data_group.command(name="validate")
@click.pass_context
def validate_cmd(ctx: click.Context) -> None:
    """Validate data quality (placeholder)."""
    console.print("\n[bold cyan]🔍 Validating Data Quality...[/bold cyan]\n")
    console.print("[yellow]⚠️  Data validation not yet implemented[/yellow]\n")
