#!/usr/bin/env python
"""
Verify order execution by checking IB Gateway directly
"""

from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime, timedelta

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

from pearlalgo.brokers.ibkr_broker import IBKRBroker
from pearlalgo.config.settings import get_settings
from pearlalgo.core.portfolio import Portfolio
from pearlalgo.risk.limits import RiskGuard, RiskLimits
from pearlalgo.futures.config import load_profile

console = Console()


def check_recent_orders():
    """Check IB Gateway for recent orders and fills."""
    console.print("\n[bold cyan]🔍 Checking IB Gateway for Recent Orders...[/bold cyan]\n")
    
    try:
        settings = get_settings()
        profile = load_profile()
        
        portfolio = Portfolio(cash=profile.starting_balance)
        risk_guard = RiskGuard(RiskLimits(max_daily_loss=2500))
        broker = IBKRBroker(portfolio, settings=settings, risk_guard=risk_guard)
        
        ib = broker._connect()
        
        console.print(f"[green]✅ Connected to IB Gateway[/green]")
        console.print(f"  Profile: {settings.profile}")
        console.print(f"  Live Trading: {settings.allow_live_trading}\n")
        
        # Get all trades (includes filled orders)
        all_trades = ib.trades()
        
        # Get fills
        fills = ib.fills()
        
        console.print(f"[bold]Recent Activity:[/bold]")
        console.print(f"  Total Trades: {len(all_trades)}")
        console.print(f"  Total Fills: {len(fills)}\n")
        
        if all_trades:
            table = Table(title="Recent Orders", box=box.ROUNDED, show_header=True, header_style="bold cyan")
            table.add_column("Order ID", style="yellow")
            table.add_column("Symbol", style="cyan")
            table.add_column("Action", justify="center")
            table.add_column("Quantity", justify="right")
            table.add_column("Status", justify="center")
            table.add_column("Filled", justify="right")
            table.add_column("Time", style="dim")
            
            # Show last 20 trades
            for trade in all_trades[-20:]:
                order = trade.order
                contract = trade.contract
                order_status = trade.orderStatus if hasattr(trade, 'orderStatus') else None
                
                status = order_status.status if order_status else "Unknown"
                filled = float(order_status.filled) if order_status and hasattr(order_status, 'filled') else 0.0
                total = float(order.totalQuantity) if hasattr(order, 'totalQuantity') else 0.0
                
                # Get time from trade log if available
                time_str = "N/A"
                if hasattr(trade, 'log') and trade.log:
                    last_entry = trade.log[-1] if trade.log else None
                    if last_entry and hasattr(last_entry, 'time'):
                        time_str = str(last_entry.time)[:19]
                
                status_color = "green" if status == "Filled" else "yellow" if status in ["Submitted", "PreSubmitted"] else "red" if status == "Cancelled" else "white"
                
                table.add_row(
                    str(order.orderId),
                    contract.symbol if hasattr(contract, 'symbol') else "N/A",
                    f"[{'green' if order.action == 'BUY' else 'red'}]{order.action}[/]",
                    str(int(total)),
                    f"[{status_color}]{status}[/]",
                    f"{int(filled)}/{int(total)}",
                    time_str
                )
            
            console.print(table)
            console.print()
        else:
            console.print("[dim]No recent orders found[/dim]\n")
        
        if fills:
            console.print(f"[bold]Recent Fills ({len(fills)}):[/bold]\n")
            fill_table = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan")
            fill_table.add_column("Symbol")
            fill_table.add_column("Side")
            fill_table.add_column("Quantity", justify="right")
            fill_table.add_column("Price", justify="right")
            fill_table.add_column("Time", style="dim")
            
            for fill in fills[-10:]:  # Last 10 fills
                # Handle different fill formats
                if isinstance(fill, tuple) and len(fill) >= 2:
                    exec_report, commission = fill[0], fill[1]
                elif hasattr(fill, 'execution'):
                    exec_report = fill.execution
                    commission = getattr(fill, 'commissionReport', None)
                else:
                    exec_report = fill
                    commission = None
                
                contract = exec_report.contract if hasattr(exec_report, 'contract') else None
                symbol = contract.symbol if contract and hasattr(contract, 'symbol') else "N/A"
                side = exec_report.side if hasattr(exec_report, 'side') else "N/A"
                shares = exec_report.shares if hasattr(exec_report, 'shares') else 0
                price = exec_report.price if hasattr(exec_report, 'price') else 0.0
                time_val = exec_report.time if hasattr(exec_report, 'time') else None
                time_str = str(time_val)[:19] if time_val else "N/A"
                
                fill_table.add_row(
                    symbol,
                    side,
                    str(int(shares)),
                    f"${price:,.2f}",
                    time_str
                )
            
            console.print(fill_table)
            console.print()
        else:
            console.print("[dim]No fills found[/dim]\n")
        
        # Summary
        filled_orders = [t for t in all_trades if hasattr(t, 'orderStatus') and t.orderStatus.status == "Filled"]
        cancelled_orders = [t for t in all_trades if hasattr(t, 'orderStatus') and t.orderStatus.status == "Cancelled"]
        
        console.print(f"[bold]Summary:[/bold]")
        console.print(f"  ✅ Filled Orders: {len(filled_orders)}")
        console.print(f"  ❌ Cancelled Orders: {len(cancelled_orders)}")
        console.print(f"  ⏳ Open Orders: {len([t for t in all_trades if hasattr(t, 'orderStatus') and t.orderStatus.status in ['Submitted', 'PreSubmitted']])}")
        console.print()
        
        if filled_orders:
            console.print("[bold green]✅ SUCCESS: Orders are being executed![/bold green]\n")
        elif cancelled_orders:
            console.print("[bold yellow]⚠️  Orders are being cancelled - check error messages above[/bold yellow]\n")
        else:
            console.print("[dim]No order execution evidence found[/dim]\n")
        
    except Exception as e:
        console.print(f"[red]❌ Error: {e}[/red]\n")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    console.print()
    console.print(Panel.fit(
        "[bold cyan]🔍 Order Execution Verification[/bold cyan]\n"
        "[dim]Check IB Gateway directly for order execution evidence[/dim]",
        border_style="cyan",
        box=box.ROUNDED
    ))
    
    check_recent_orders()

