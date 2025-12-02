#!/usr/bin/env python
"""
Debug script to check why trades aren't executing.
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pearlalgo.config.settings import get_settings
from pearlalgo.brokers.ibkr_broker import IBKRBroker
from pearlalgo.core.portfolio import Portfolio
from pearlalgo.risk.limits import RiskGuard, RiskLimits
from rich.console import Console
from rich.table import Table

console = Console()


def main():
    console.print("\n[bold cyan]🔍 Trading System Diagnostic[/bold cyan]\n")

    # Check settings
    settings = get_settings()

    table = Table(title="Settings Check", show_header=True)
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="white")
    table.add_column("Status", style="green")

    table.add_row(
        "Profile", settings.profile, "✅" if settings.profile == "live" else "❌"
    )
    table.add_row(
        "Allow Live Trading",
        str(settings.allow_live_trading),
        "✅" if settings.allow_live_trading else "❌",
    )
    table.add_row("IB Host", settings.ib_host, "✅")
    table.add_row("IB Port", str(settings.ib_port), "✅")
    table.add_row("IB Client ID", str(settings.ib_client_id), "✅")

    console.print(table)
    console.print()

    # Check broker
    console.print("[bold]Testing Broker Connection...[/bold]")
    try:
        portfolio = Portfolio(cash=50000.0)
        risk_guard = RiskGuard(RiskLimits())
        broker = IBKRBroker(portfolio, settings=settings, risk_guard=risk_guard)

        # Check if live enabled
        live_enabled = broker._live_enabled()
        console.print(f"Live Trading Enabled: {'✅ YES' if live_enabled else '❌ NO'}")

        if not live_enabled:
            console.print(
                "\n[bold red]⚠️  ISSUE FOUND: Live trading is disabled![/bold red]"
            )
            console.print(f"   Profile: {settings.profile}")
            console.print(f"   Allow Live Trading: {settings.allow_live_trading}")
            console.print("\n[bold yellow]To fix:[/bold yellow]")
            console.print("   1. Set PEARLALGO_PROFILE=live in .env")
            console.print("   2. Set PEARLALGO_ALLOW_LIVE_TRADING=true in .env")
            console.print("   3. Or use --profile-config with profile=live")
        else:
            console.print(
                "\n[bold green]✅ Broker is configured for live trading[/bold green]"
            )

            # Try to connect
            try:
                ib = broker._connect()
                if ib.isConnected():
                    console.print("[bold green]✅ Connected to IB Gateway[/bold green]")
                else:
                    console.print("[bold red]❌ Not connected to IB Gateway[/bold red]")
            except Exception as e:
                console.print(f"[bold red]❌ Connection error: {e}[/bold red]")

    except Exception as e:
        console.print(f"[bold red]❌ Broker initialization error: {e}[/bold red]")
        import traceback

        console.print(traceback.format_exc())

    console.print()


if __name__ == "__main__":
    main()
