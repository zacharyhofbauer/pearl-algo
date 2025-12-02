#!/usr/bin/env python
"""
Test IBKR Broker Connection and Basic Operations
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

from pearlalgo.brokers.ibkr_broker import IBKRBroker
from pearlalgo.config.settings import get_settings
from pearlalgo.core.portfolio import Portfolio
from pearlalgo.risk.limits import RiskGuard, RiskLimits
from pearlalgo.futures.config import load_profile
from pearlalgo.brokers.contracts import resolve_future_contract

console = Console()


def test_connection():
    """Test basic connection to IB Gateway."""
    console.print("\n[bold cyan]🔌 Testing IB Gateway Connection...[/bold cyan]\n")

    try:
        settings = get_settings()
        console.print(
            f"Connecting to {settings.ib_host}:{settings.ib_port} (Client ID: {settings.ib_client_id})..."
        )

        profile = load_profile()
        portfolio = Portfolio(cash=profile.starting_balance)
        risk_guard = RiskGuard(RiskLimits(max_daily_loss=profile.daily_loss_limit))

        broker = IBKRBroker(portfolio, settings=settings, risk_guard=risk_guard)

        console.print("[green]✅ Connection successful![/green]\n")

        return broker, portfolio

    except Exception as e:
        console.print(f"[red]❌ Connection failed: {e}[/red]\n")
        import traceback

        traceback.print_exc()
        return None, None


def test_contract_lookup(broker):
    """Test contract lookup."""
    console.print("\n[bold cyan]🔍 Testing Contract Lookup...[/bold cyan]\n")

    test_symbols = ["MES", "MNQ", "MGC"]

    try:
        ib = broker._connect()

        from pearlalgo.brokers.contracts import _default_exchange_for_symbol

        for symbol in test_symbols:
            try:
                console.print(f"Looking up {symbol}...")
                exchange = _default_exchange_for_symbol(symbol)
                contract = resolve_future_contract(
                    ib, symbol, exchange=exchange, trading_class=symbol
                )
                if contract:
                    console.print(
                        f"  [green]✅[/green] {symbol}: {contract.localSymbol if hasattr(contract, 'localSymbol') else contract.symbol} (Exchange: {exchange})"
                    )
                else:
                    console.print(f"  [yellow]⚠️[/yellow] {symbol}: Contract not found")
            except Exception as e:
                console.print(f"  [red]❌[/red] {symbol}: {e}")

        console.print()
    except Exception as e:
        console.print(f"[red]❌ Error connecting to broker: {e}[/red]\n")


def test_position_check(broker, portfolio):
    """Check current positions."""
    console.print("\n[bold cyan]📊 Checking Current Positions...[/bold cyan]\n")

    try:
        # Get positions from portfolio
        positions = portfolio.positions

        if not positions or all(pos.size == 0 for pos in positions.values()):
            console.print("[dim]No open positions[/dim]\n")
        else:
            table = Table(title="Open Positions", box=box.ROUNDED, show_header=True)
            table.add_column("Symbol", style="yellow")
            table.add_column("Size", justify="right")
            table.add_column("Avg Price", justify="right")
            table.add_column("Realized P&L", justify="right")

            for symbol, position in positions.items():
                if position.size != 0:
                    table.add_row(
                        symbol,
                        str(int(position.size)),
                        f"${position.avg_price:,.2f}",
                        f"${position.realized_pnl:,.2f}",
                    )

            console.print(table)
            console.print()

    except Exception as e:
        console.print(f"[red]❌ Error checking positions: {e}[/red]\n")


def main():
    """Run broker connection tests."""
    console.print()
    console.print(
        Panel.fit(
            "[bold cyan]🧪 IBKR Broker Connection Test[/bold cyan]\n"
            "[dim]Test connection, contract lookup, and position checking[/dim]",
            border_style="cyan",
            box=box.ROUNDED,
        )
    )
    console.print()

    # Test connection
    broker, portfolio = test_connection()
    if not broker:
        return 1

    # Test contract lookup
    test_contract_lookup(broker)

    # Check positions
    test_position_check(broker, portfolio)

    console.print("[bold green]✅ All tests completed![/bold green]\n")
    console.print(
        "[dim]You can now use the manual trading test to place orders[/dim]\n"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
