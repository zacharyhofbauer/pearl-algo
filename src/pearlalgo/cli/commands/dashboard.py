"""Dashboard command - Live updating status dashboard."""

from __future__ import annotations

import click
import time
import os
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
@click.option("--full", is_flag=True, help="Show comprehensive full-screen dashboard with more details")
@click.pass_context
def dashboard_cmd(ctx: click.Context, once: bool, refresh: int, full: bool) -> None:
    """Show real-time status dashboard with live updates.
    
    Two modes available:
    
    \b
    Standard Mode (default):
      Shows gateway status, performance, signals, and risk state
    
    \b
    Full Mode (--full):
      Comprehensive 3-column dashboard with:
      - Gateway status, trading processes, system health
      - Detailed performance metrics, recent trades history
      - Risk state with visual buffer, positions, signals
    """
    verbosity = ctx.obj.get("verbosity", "NORMAL")
    
    # Change to project root for file access
    os.chdir(SCRIPT_DIR)
    
    if full:
        # Use comprehensive dashboard
        from scripts.comprehensive_dashboard import create_comprehensive_dashboard
        create_fn = create_comprehensive_dashboard
        title = "Comprehensive Dashboard"
    else:
        # Use standard dashboard
        create_fn = create_dashboard
        title = "Status Dashboard"
    
    if once:
        # Show once
        console.print(create_fn())
    else:
        # Live updating dashboard
        console.print(f"\n[bold cyan]📊 Starting {title} (refreshes every {refresh}s)[/bold cyan]")
        console.print("[dim]Press Ctrl+C to exit[/dim]\n")
        try:
            with Live(create_fn(), refresh_per_second=1.0/refresh, screen=True) as live_display:
                while True:
                    time.sleep(refresh)
                    live_display.update(create_fn())
        except KeyboardInterrupt:
            console.print("\n[bold yellow]Dashboard closed[/bold yellow]\n")

