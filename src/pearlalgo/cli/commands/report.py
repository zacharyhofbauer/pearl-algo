"""Report command - Generate daily trading report."""

from __future__ import annotations

import click
import sys
from pathlib import Path

# Import existing script logic
SCRIPT_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent
if str(SCRIPT_DIR / "scripts") not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR / "scripts"))

from scripts import daily_report

from rich.console import Console

console = Console()


@click.command(name="report")
@click.option("--date", help="Report date YYYYMMDD (default: today)")
@click.pass_context
def report_cmd(ctx: click.Context, date: str | None) -> None:
    """Generate daily trading report."""
    verbosity = ctx.obj.get("verbosity", "NORMAL")

    console.print("\n[bold cyan]📄 Generating Daily Report...[/bold cyan]\n")

    args = []
    if date:
        args.extend(["--date", date])

    result = daily_report.main(args)

    if result == 0:
        console.print("[bold green]✅ Report generated successfully![/bold green]\n")
    else:
        console.print("[bold red]❌ Failed to generate report[/bold red]\n")

    raise SystemExit(result)
