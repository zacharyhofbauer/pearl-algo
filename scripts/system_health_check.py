#!/usr/bin/env python
"""
Comprehensive system health check for trading infrastructure
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
from rich.live import Live
import time

from pearlalgo.brokers.ibkr_broker import IBKRBroker
from pearlalgo.config.settings import get_settings
from pearlalgo.core.portfolio import Portfolio
from pearlalgo.risk.limits import RiskGuard, RiskLimits
from pearlalgo.futures.config import load_profile

console = Console()


def check_configuration():
    """Check configuration settings."""
    console.print("\n[bold cyan]1️⃣  Configuration Check[/bold cyan]\n")
    
    settings = get_settings()
    
    table = Table(box=box.ROUNDED, show_header=True, header_style="bold cyan")
    table.add_column("Setting", style="yellow")
    table.add_column("Value", style="cyan")
    table.add_column("Status", justify="center")
    
    # Port
    port = settings.ib_port
    port_ok = port == 4002
    table.add_row("Port", str(port), "✅" if port_ok else "❌")
    
    # Client ID
    client_id = settings.ib_client_id
    client_ok = client_id >= 2
    table.add_row("Client ID", str(client_id), "✅" if client_ok else "⚠️")
    
    # Host
    host = settings.ib_host
    host_ok = host in ["127.0.0.1", "localhost"]
    table.add_row("Host", host, "✅" if host_ok else "⚠️")
    
    # Profile
    profile = settings.profile
    profile_ok = profile == "live"
    table.add_row("Profile", profile, "✅" if profile_ok else "⚠️")
    
    # Live Trading
    live = settings.allow_live_trading
    table.add_row("Live Trading", str(live), "✅" if live else "⚠️")
    
    console.print(table)
    
    all_ok = port_ok and client_ok and host_ok
    return all_ok


def check_connection():
    """Check IB Gateway connection."""
    console.print("\n[bold cyan]2️⃣  IB Gateway Connection[/bold cyan]\n")
    
    try:
        settings = get_settings()
        profile = load_profile()
        
        portfolio = Portfolio(cash=profile.starting_balance)
        risk_guard = RiskGuard(RiskLimits(max_daily_loss=profile.daily_loss_limit))
        broker = IBKRBroker(portfolio, settings=settings, risk_guard=risk_guard)
        
        ib = broker._connect()
        
        if ib.isConnected():
            console.print("[green]✅ Connected to IB Gateway[/green]")
            console.print(f"   Host: {settings.ib_host}")
            console.print(f"   Port: {settings.ib_port}")
            console.print(f"   Client ID: {settings.ib_client_id}")
            account = ib.accountValues()[0].account if ib.accountValues() else 'N/A'
            console.print(f"   Account: {account}\n")
            return True, ib
        else:
            console.print("[red]❌ Not connected[/red]\n")
            return False, None
            
    except Exception as e:
        console.print(f"[red]❌ Connection failed: {e}[/red]\n")
        return False, None


def check_positions(ib):
    """Check position access."""
    console.print("\n[bold cyan]3️⃣  Position Access[/bold cyan]\n")
    
    try:
        if not ib.isConnected():
            ib.connect(ib.host, ib.port, clientId=ib.client.clientId)
        
        positions = ib.positions()
        
        console.print(f"[green]✅ Can access positions[/green]")
        console.print(f"   Open positions: {len([p for p in positions if p.position != 0])}\n")
        
        if positions:
            pos_table = Table(box=box.SIMPLE, show_header=True)
            pos_table.add_column("Symbol")
            pos_table.add_column("Size", justify="right")
            pos_table.add_column("Avg Cost", justify="right")
            
            for pos in positions[:5]:  # Show first 5
                if pos.position != 0:
                    pos_table.add_row(
                        pos.contract.symbol,
                        str(int(pos.position)),
                        f"${pos.avgCost:,.2f}"
                    )
            
            if any(p.position != 0 for p in positions):
                console.print(pos_table)
                console.print()
        
        return True
        
    except Exception as e:
        console.print(f"[red]❌ Position access failed: {e}[/red]\n")
        return False


def check_contract_lookup(ib):
    """Check contract lookup."""
    console.print("\n[bold cyan]4️⃣  Contract Lookup[/bold cyan]\n")
    
    try:
        if not ib.isConnected():
            ib.connect(ib.host, ib.port, clientId=ib.client.clientId)
        
        test_symbols = ["MES", "MNQ", "MGC"]
        success_count = 0
        
        from pearlalgo.brokers.contracts import resolve_future_contract, _default_exchange_for_symbol
        
        for symbol in test_symbols:
            try:
                exchange = _default_exchange_for_symbol(symbol)
                contract = resolve_future_contract(ib, symbol, exchange=exchange, trading_class=symbol)
                if contract:
                    success_count += 1
            except:
                pass
        
        if success_count == len(test_symbols):
            console.print(f"[green]✅ Contract lookup working[/green]")
            console.print(f"   Tested {len(test_symbols)} symbols: {success_count}/{len(test_symbols)} successful\n")
            return True
        else:
            console.print(f"[yellow]⚠️  Contract lookup partial[/yellow]")
            console.print(f"   Tested {len(test_symbols)} symbols: {success_count}/{len(test_symbols)} successful\n")
            return False
            
    except Exception as e:
        console.print(f"[red]❌ Contract lookup failed: {e}[/red]\n")
        return False


def check_order_capability():
    """Check if orders can be placed (dry-run test)."""
    console.print("\n[bold cyan]5️⃣  Order Capability[/bold cyan]\n")
    
    try:
        settings = get_settings()
        profile = load_profile()
        
        portfolio = Portfolio(cash=profile.starting_balance)
        risk_guard = RiskGuard(RiskLimits(max_daily_loss=profile.daily_loss_limit))
        broker = IBKRBroker(portfolio, settings=settings, risk_guard=risk_guard)
        
        # Check if live trading is enabled
        if broker._live_enabled():
            console.print("[green]✅ Live trading enabled[/green]")
            console.print("   Orders will be placed to IB Gateway\n")
        else:
            console.print("[yellow]⚠️  Live trading disabled (DRY RUN)[/yellow]")
            console.print("   Orders will be logged but not executed\n")
        
        return True
        
    except Exception as e:
        console.print(f"[red]❌ Order capability check failed: {e}[/red]\n")
        return False


def check_mobile_compatibility():
    """Check mobile app compatibility."""
    console.print("\n[bold cyan]6️⃣  Mobile App Compatibility[/bold cyan]\n")
    
    settings = get_settings()
    
    client_id = settings.ib_client_id
    port = settings.ib_port
    
    if client_id >= 2 and port == 4002:
        console.print("[green]✅ Mobile app compatible[/green]")
        console.print(f"   Client ID {client_id} (secondary session)")
        console.print(f"   Port {port} (paper trading)")
        console.print("   Mobile app can use Client ID 0/1 simultaneously\n")
        return True
    else:
        console.print("[yellow]⚠️  May conflict with mobile app[/yellow]")
        console.print(f"   Client ID: {client_id}")
        console.print(f"   Port: {port}\n")
        return False


def main():
    """Run all health checks."""
    console.print()
    console.print(Panel.fit(
        "[bold cyan]🏥 System Health Check[/bold cyan]\n"
        "[dim]Comprehensive verification of trading infrastructure[/dim]",
        border_style="cyan",
        box=box.ROUNDED
    ))
    
    results = {}
    
    results["config"] = check_configuration()
    connection_result, ib = check_connection()
    results["connection"] = connection_result
    
    if connection_result and ib:
        results["positions"] = check_positions(ib)
        results["contracts"] = check_contract_lookup(ib)
        # Disconnect after tests
        try:
            if ib.isConnected():
                ib.disconnect()
        except:
            pass
    else:
        results["positions"] = False
        results["contracts"] = False
    
    results["orders"] = check_order_capability()
    results["mobile"] = check_mobile_compatibility()
    
    # Summary
    console.print("\n[bold cyan]📊 Health Check Summary[/bold cyan]\n")
    
    summary_table = Table(box=box.ROUNDED, show_header=True, header_style="bold cyan")
    summary_table.add_column("Check", style="yellow")
    summary_table.add_column("Status", justify="center")
    
    for check, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        summary_table.add_row(check.replace("_", " ").title(), status)
    
    console.print(summary_table)
    console.print()
    
    all_passed = all(results.values())
    
    if all_passed:
        console.print("[bold green]✅ All systems operational![/bold green]\n")
        console.print("Your trading system is ready to use:")
        console.print("  • Configuration: ✅")
        console.print("  • IB Gateway: ✅")
        console.print("  • Position access: ✅")
        console.print("  • Contract lookup: ✅")
        console.print("  • Order capability: ✅")
        console.print("  • Mobile compatibility: ✅\n")
    else:
        console.print("[bold yellow]⚠️  Some checks failed[/bold yellow]\n")
        console.print("Please review the errors above and fix any issues.\n")
    
    return all_passed


if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        console.print("\n[yellow]Health check interrupted[/yellow]\n")
        sys.exit(1)
    except Exception as e:
        console.print(f"\n[red]Health check failed: {e}[/red]\n")
        import traceback
        traceback.print_exc()
        sys.exit(1)

