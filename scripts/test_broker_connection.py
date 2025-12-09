#!/usr/bin/env python3
"""
Test broker connection for PearlAlgo v2 system.

Tests connections to configured brokers (Paper, Alpaca, Bybit, IBKR optional).
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

from pearlalgo.config.settings import settings
from pearlalgo.brokers.factory import create_broker

console = Console()


def test_paper_broker():
    """Test paper broker (always available)."""
    console.print("[cyan]Testing Paper Broker...[/cyan]")
    try:
        from pearlalgo.core.portfolio import Portfolio
        from pearlalgo.brokers.paper_broker import PaperBroker
        
        portfolio = Portfolio(cash=50000.0)
        
        def price_lookup(symbol: str):
            # Mock prices for testing
            prices = {"ES": 4000.0, "NQ": 12000.0, "QQQ": 400.0}
            return prices.get(symbol, 100.0)
        
        broker = PaperBroker(portfolio=portfolio, price_lookup=price_lookup)
        account = broker.get_account_summary()
        
        console.print(f"  ✅ Paper Broker: Connected")
        console.print(f"     Cash: ${account.cash:,.2f}")
        console.print(f"     Equity: ${account.equity:,.2f}")
        return True
    except Exception as e:
        console.print(f"  ❌ Paper Broker: Failed - {e}")
        return False


def test_alpaca_broker():
    """Test Alpaca broker connection."""
    console.print("\n[cyan]Testing Alpaca Broker...[/cyan]")
    try:
        if not settings.alpaca_api_key or not settings.alpaca_secret_key:
            console.print("  ⚠️  Alpaca: Not configured (missing API keys)")
            return None
        
        broker = create_broker("alpaca")
        account = broker.get_account_summary()
        
        console.print(f"  ✅ Alpaca: Connected")
        console.print(f"     Cash: ${account.cash:,.2f}")
        console.print(f"     Equity: ${account.equity:,.2f}")
        return True
    except Exception as e:
        console.print(f"  ❌ Alpaca: Failed - {e}")
        return False


def test_bybit_broker():
    """Test Bybit broker connection."""
    console.print("\n[cyan]Testing Bybit Broker...[/cyan]")
    try:
        if not settings.bybit_api_key or not settings.bybit_secret_key:
            console.print("  ⚠️  Bybit: Not configured (missing API keys)")
            return None
        
        broker = create_broker("bybit")
        account = broker.get_account_summary()
        
        console.print(f"  ✅ Bybit: Connected")
        console.print(f"     Cash: ${account.cash:,.2f}")
        console.print(f"     Equity: ${account.equity:,.2f}")
        return True
    except Exception as e:
        console.print(f"  ❌ Bybit: Failed - {e}")
        return False


def test_ibkr_broker():
    """Test IBKR broker connection (optional/deprecated)."""
    console.print("\n[cyan]Testing IBKR Broker (optional)...[/cyan]")
    try:
        import subprocess
        
        # Check if gateway is running
        result = subprocess.run(["pgrep", "-f", "IbcGateway"], capture_output=True)
        if result.returncode != 0:
            console.print("  ⚠️  IBKR: Gateway not running (optional - system works without it)")
            return None
        
        broker = create_broker("ibkr")
        account = broker.get_account_summary()
        
        console.print(f"  ✅ IBKR: Connected")
        console.print(f"     Cash: ${account.cash:,.2f}")
        console.print(f"     Equity: ${account.equity:,.2f}")
        return True
    except Exception as e:
        console.print(f"  ⚠️  IBKR: Not available - {e}")
        console.print("     (This is optional - system works without IBKR)")
        return None


def main():
    """Run all broker connection tests."""
    console.print("\n[bold cyan]🔌 Broker Connection Test[/bold cyan]\n")
    
    results = {}
    
    # Paper broker (always available)
    results["Paper"] = test_paper_broker()
    
    # Optional brokers
    results["Alpaca"] = test_alpaca_broker()
    results["Bybit"] = test_bybit_broker()
    results["IBKR"] = test_ibkr_broker()
    
    # Summary
    console.print("\n[bold]Summary:[/bold]\n")
    
    table = Table(show_header=True, header_style="bold cyan", box=box.ROUNDED)
    table.add_column("Broker", style="cyan")
    table.add_column("Status", justify="center")
    table.add_column("Notes")
    
    for broker_name, result in results.items():
        if result is True:
            table.add_row(broker_name, "[green]✅ Connected[/green]", "Ready to use")
        elif result is False:
            table.add_row(broker_name, "[red]❌ Failed[/red]", "Check configuration")
        else:
            table.add_row(broker_name, "[yellow]⚠️  Not Configured[/yellow]", "Optional")
    
    console.print(table)
    
    # Check if at least paper broker works
    if results.get("Paper") is True:
        console.print("\n[bold green]✅ System is operational![/bold green]")
        console.print("   Paper broker is always available for testing.")
        console.print("   Configure additional brokers in your .env file if needed.\n")
        return 0
    else:
        console.print("\n[bold red]❌ System check failed![/bold red]")
        console.print("   Paper broker should always work. Check your installation.\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())

