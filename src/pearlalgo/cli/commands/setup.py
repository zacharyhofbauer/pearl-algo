"""Setup command - Interactive setup wizard."""

from __future__ import annotations

import click
import sys
from pathlib import Path

from rich.console import Console

console = Console()


@click.command(name="setup")
@click.pass_context
def setup_cmd(ctx: click.Context) -> None:
    """Run interactive setup wizard."""
    verbosity = ctx.obj.get("verbosity", "NORMAL")
    
    # Import and run existing script
    SCRIPT_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent
    if str(SCRIPT_DIR / "scripts") not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR / "scripts"))
    
    from scripts import setup_assistant
    
    console.print("\n[bold cyan]🔧 Running Setup Wizard...[/bold cyan]\n")
    
    # Run setup wizard (it has its own interactive menu)
    setup_assistant.main()

