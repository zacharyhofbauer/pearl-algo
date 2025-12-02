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

from scripts.dashboard import create_dashboard

console = Console()


@click.command(name="dashboard")
@click.option("--once", is_flag=True, help="Show dashboard once and exit (default: live updating)")
@click.option("--refresh", type=int, default=5, help="Refresh interval in seconds (default: 5)")
@click.option("--full", is_flag=True, help="Show comprehensive full-screen dashboard with more details")
@click.option("--menu", is_flag=True, help="Show interactive menu panel")
@click.option("--interactive", is_flag=True, help="Interactive mode with menu and keyboard commands")
@click.pass_context
def dashboard_cmd(ctx: click.Context, once: bool, refresh: int, full: bool, menu: bool, interactive: bool) -> None:
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
    
    # Use unified dashboard (full mode removed - dashboard is always comprehensive)
    create_fn = create_dashboard
    title = "Trading Dashboard"
    
    # Import main function from dashboard script
    from scripts.dashboard import main as dashboard_main
    import sys
    
    # Build arguments for dashboard script
    sys.argv = ["dashboard"]
    if once:
        sys.argv.append("--once")
    if menu:
        sys.argv.append("--menu")
    if interactive:
        sys.argv.append("--interactive")
    sys.argv.extend(["--refresh", str(refresh)])
    
    # Call the main dashboard function
    dashboard_main()

