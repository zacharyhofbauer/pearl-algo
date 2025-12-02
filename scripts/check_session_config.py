#!/usr/bin/env python
"""
Check current IBKR session configuration
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

from pearlalgo.config.settings import get_settings

console = Console()


def check_config():
    """Check current IBKR session configuration."""
    console.print("\n[bold cyan]🔍 Current IBKR Session Configuration[/bold cyan]\n")

    settings = get_settings()

    table = Table(
        title="Session Settings",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Setting", style="yellow")
    table.add_column("Value", style="cyan")
    table.add_column("Status", justify="center")

    # Port
    port = settings.ib_port
    port_type = (
        "Paper Trading"
        if port == 4002
        else "Live Trading"
        if port == 4001
        else "Custom"
    )
    port_status = "✅" if port == 4002 else "⚠️"
    table.add_row("Port", str(port), f"{port_status} {port_type}")

    # Client ID
    client_id = settings.ib_client_id
    session_type = "Main Session" if client_id <= 1 else "Secondary Session"
    session_status = (
        "⚠️  Conflicts with mobile" if client_id <= 1 else "✅ Compatible with mobile"
    )
    table.add_row("Client ID", str(client_id), session_status)

    # Profile
    profile = settings.profile
    profile_status = "✅" if profile == "live" else "⚠️"
    table.add_row("Profile", profile, profile_status)

    # Live Trading
    live_trading = settings.allow_live_trading
    live_status = "✅ Enabled" if live_trading else "❌ Disabled (DRY RUN)"
    table.add_row("Live Trading", str(live_trading), live_status)

    console.print(table)
    console.print()

    # Recommendations
    console.print("[bold]Recommendations:[/bold]\n")

    if client_id <= 1:
        console.print(
            "[yellow]⚠️  Current Client ID ({}) may conflict with mobile app[/yellow]".format(
                client_id
            )
        )
        console.print("   → Change to Client ID 2 or higher for compatibility\n")
        console.print("[bold]To fix:[/bold]")
        console.print("   1. Edit .env file:")
        console.print("      PEARLALGO_IB_CLIENT_ID=2")
        console.print("   2. Restart automated trading system\n")
    else:
        console.print(
            "[green]✅ Client ID {} is compatible with mobile app[/green]".format(
                client_id
            )
        )
        console.print("   → Mobile app can use Client ID 0/1 (main session)")
        console.print(
            "   → Automated system uses Client ID {} (secondary session)\n".format(
                client_id
            )
        )

    if port == 4002:
        console.print(
            "[green]✅ Port 4002 (Paper Trading) - Both can connect simultaneously[/green]\n"
        )
    else:
        console.print(
            "[yellow]⚠️  Port {} - Make sure this matches your paper trading setup[/yellow]\n".format(
                port
            )
        )

    # Summary
    console.print("[bold]Summary:[/bold]")
    console.print("  • Automated system: Port {}, Client ID {}".format(port, client_id))
    console.print("  • Mobile app: Port {}, Client ID 0 (main session)".format(port))
    console.print("  • Both can connect to paper trading simultaneously\n")


if __name__ == "__main__":
    console.print()
    console.print(
        Panel.fit(
            "[bold cyan]📱 Mobile App Compatibility Check[/bold cyan]\n"
            "[dim]Verify settings for viewing trades on phone while trading runs on server[/dim]",
            border_style="cyan",
            box=box.ROUNDED,
        )
    )

    check_config()
