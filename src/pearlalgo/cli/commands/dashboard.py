"""Dashboard command - Live updating status dashboard."""

from __future__ import annotations

import click
import time
from datetime import datetime, timezone

from rich.console import Console
from rich.live import Live
from rich.layout import Layout
from rich.panel import Panel
from rich import box

# Import the existing dashboard logic
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from scripts.status_dashboard import create_dashboard

console = Console()


@click.command(name="dashboard")
@click.option("--once", is_flag=True, help="Show dashboard once and exit (default: live updating)")
@click.option("--refresh", type=int, default=5, help="Refresh interval in seconds (default: 5)")
@click.pass_context
def dashboard_cmd(ctx: click.Context, once: bool, refresh: int) -> None:
    """Show real-time status dashboard with live updates."""
    verbosity = ctx.obj.get("verbosity", "NORMAL")
    
    if once:
        # Show once
        console.print(create_dashboard())
    else:
        # Live updating dashboard
        console.print(f"\n[bold cyan]📊 Starting Live Dashboard (refreshes every {refresh}s)[/bold cyan]")
        console.print("[dim]Press Ctrl+C to exit[/dim]\n")
        try:
            with Live(create_dashboard(), refresh_per_second=1.0/refresh, screen=True) as live_display:
                while True:
                    time.sleep(refresh)
                    live_display.update(create_dashboard())
        except KeyboardInterrupt:
            console.print("\n[bold yellow]Dashboard closed[/bold yellow]\n")

