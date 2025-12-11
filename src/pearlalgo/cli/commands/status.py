"""Status command - Quick system status check."""

from __future__ import annotations

import click
import subprocess
from datetime import datetime, timezone

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

# Futures modules removed - CLI will be updated for options
# TODO: Create options-specific CLI commands

console = Console()


def check_gateway_process() -> tuple[bool, str | None]:
    """Check if IB Gateway process is running."""
    result = subprocess.run(["pgrep", "-f", "IbcGateway"], capture_output=True)
    if result.returncode == 0:
        pid = result.stdout.decode().strip().split()[0] if result.stdout else None
        return True, pid
    return False, None


def check_gateway_port() -> bool:
    """Check if port 4002 is listening."""
    result = subprocess.run(["ss", "-tlnp"], capture_output=True, text=True)
    return "4002" in result.stdout


@click.command(name="status")
@click.pass_context
def status_cmd(ctx: click.Context) -> None:
    """Show quick system status (gateway, risk, performance)."""
    verbosity = ctx.obj.get("verbosity", "NORMAL")

    console.print("\n[bold cyan]📊 System Status[/bold cyan]\n")

    # Gateway status
    is_running, pid = check_gateway_process()
    port_listening = check_gateway_port()
    gateway_ready = is_running and port_listening

    gateway_table = Table(show_header=False, box=box.SIMPLE, padding=(0, 2))
    gateway_table.add_row(
        "Gateway Process",
        "✅ Running" if is_running else "❌ Not Running",
        f"PID: {pid}" if pid else "",
    )
    gateway_table.add_row(
        "Port 4002",
        "✅ Listening" if port_listening else "❌ Not Listening",
        "",
    )
    gateway_table.add_row(
        "Status",
        "✅ Ready" if gateway_ready else "❌ Not Ready",
        "",
    )

    # Show IB Gateway as optional (v2 doesn't require it)
    gateway_title = "🔌 IB Gateway (Optional)"
    if not gateway_ready:
        gateway_title += " - Not Required for v2 System"
    
    console.print(
        Panel(
            gateway_table,
            title=gateway_title,
            border_style="cyan" if gateway_ready else "yellow",
            box=box.ROUNDED,
        )
    )
    
    if not gateway_ready:
        console.print("[dim yellow]ℹ️  IB Gateway is optional. System works with Paper Broker and other data providers.[/dim yellow]")
    
    console.print()

    # Risk and performance status - TODO: Update for options
    console.print("[dim]Risk and performance tracking will be updated for options trading[/dim]")
    console.print()
