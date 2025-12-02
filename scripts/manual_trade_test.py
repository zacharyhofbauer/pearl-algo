#!/usr/bin/env python
"""
Manual Trading Test - Test entering and closing trades manually
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add project root to path
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt, Confirm
from rich import box

from pearlalgo.brokers.ibkr_broker import IBKRBroker
from pearlalgo.config.settings import get_settings
from pearlalgo.core.portfolio import Portfolio
from pearlalgo.risk.limits import RiskGuard, RiskLimits
from pearlalgo.futures.config import load_profile

console = Console()


def show_positions(broker: IBKRBroker, portfolio: Portfolio) -> None:
    """Display current positions."""
    console.print("\n[bold cyan]📊 Current Positions[/bold cyan]\n")

    try:
        # Get positions from IB
        ib = broker._connect()

        # Request fresh position data
        ib.reqPositions()
        import time

        time.sleep(0.5)  # Give IB time to send position updates

        positions = ib.positions()

        if not positions and not any(
            pos.size != 0 for pos in portfolio.positions.values()
        ):
            console.print("[dim]No open positions[/dim]\n")
            return

        table = Table(
            title="Open Positions",
            box=box.ROUNDED,
            show_header=True,
            header_style="bold cyan",
        )
        table.add_column("Symbol", style="yellow")
        table.add_column("Size", justify="right")
        table.add_column("Avg Price", justify="right")
        table.add_column("Market Price", justify="right")
        table.add_column("Unrealized P&L", justify="right")
        table.add_column("Realized P&L", justify="right")

        # Show IB positions
        for pos in positions:
            contract = pos.contract
            symbol = contract.symbol
            size = pos.position
            avg_cost = pos.avgCost
            market_price = pos.marketPrice if hasattr(pos, "marketPrice") else avg_cost
            unrealized = pos.unrealizedPNL if hasattr(pos, "unrealizedPNL") else 0.0
            realized = pos.realizedPNL if hasattr(pos, "realizedPNL") else 0.0

            if size == 0:
                continue

            pnl_color = "green" if unrealized >= 0 else "red"
            table.add_row(
                symbol,
                str(int(size)),
                f"${avg_cost:,.2f}",
                f"${market_price:,.2f}",
                f"[{pnl_color}]${unrealized:,.2f}[/{pnl_color}]",
                f"${realized:,.2f}",
            )

        # Also show portfolio positions
        for symbol, position in portfolio.positions.items():
            if position.size == 0:
                continue
            # Check if already shown
            if not any(p.contract.symbol == symbol for p in positions):
                table.add_row(
                    symbol,
                    str(int(position.size)),
                    f"${position.avg_price:,.2f}",
                    "N/A",
                    "N/A",
                    f"${position.realized_pnl:,.2f}",
                )

        console.print(table)
        console.print()

    except Exception as e:
        console.print(f"[red]❌ Error fetching positions: {e}[/red]\n")
        import traceback

        traceback.print_exc()


def enter_trade(broker: IBKRBroker, portfolio: Portfolio) -> None:
    """Manually enter a trade."""
    console.print("\n[bold cyan]📈 Enter Trade[/bold cyan]\n")

    symbol = Prompt.ask("Symbol", default="MES")
    side = Prompt.ask("Side", choices=["LONG", "SHORT"], default="LONG")
    size = int(Prompt.ask("Size (contracts)", default="1"))
    order_type = Prompt.ask("Order Type", choices=["MKT", "LMT"], default="MKT")
    limit_price = None
    if order_type == "LMT":
        limit_price = float(Prompt.ask("Limit Price", default=""))

    console.print("\n[bold yellow]Placing order:[/bold yellow]")
    console.print(f"  Symbol: {symbol}")
    console.print(f"  Side: {side}")
    console.print(f"  Size: {abs(size)} contracts")
    console.print(f"  Order Type: {order_type}")
    if limit_price:
        console.print(f"  Limit Price: ${limit_price:,.2f}")

    if not Confirm.ask("\nConfirm order?"):
        console.print("[yellow]Order cancelled[/yellow]\n")
        return

    try:
        from datetime import datetime, timezone
        from pearlalgo.core.events import OrderEvent

        # Create order event
        order = OrderEvent(
            timestamp=datetime.now(timezone.utc),
            symbol=symbol,
            side="BUY" if side.upper() == "LONG" else "SELL",
            quantity=abs(size),
            order_type=order_type,
            limit_price=limit_price,
            metadata={
                "profile": "live",
                "sec_type": "FUT",
                "trading_class": symbol,
            },
        )

        console.print(
            f"\n[dim]Submitting {side} order for {abs(size)} {symbol}...[/dim]"
        )
        order_id = broker.submit_order(order)

        if order_id:
            console.print("[green]✅ Order submitted successfully![/green]")
            console.print(f"  Order ID: {order_id}\n")
        else:
            console.print(
                "[yellow]⚠️  Order may be in dry-run mode (check settings)[/yellow]\n"
            )

    except Exception as e:
        console.print(f"[red]❌ Error placing order: {e}[/red]\n")
        import traceback

        traceback.print_exc()


def check_orders(broker: IBKRBroker) -> None:
    """Check recent orders and their status."""
    console.print("\n[bold cyan]📋 Recent Orders[/bold cyan]\n")

    try:
        ib = broker._connect()

        # Get open orders
        open_orders = ib.openOrders()

        # Get all trades (filled orders)
        all_trades = ib.trades()

        if not open_orders and not all_trades:
            console.print("[dim]No recent orders[/dim]\n")
            return

        table = Table(
            title="Recent Orders",
            box=box.ROUNDED,
            show_header=True,
            header_style="bold cyan",
        )
        table.add_column("Order ID", style="yellow")
        table.add_column("Symbol", style="cyan")
        table.add_column("Action", justify="center")
        table.add_column("Quantity", justify="right")
        table.add_column("Order Type", justify="center")
        table.add_column("Status", justify="center")
        table.add_column("Filled", justify="right")

        # Show open orders
        for trade in open_orders:
            order = trade.order
            contract = trade.contract
            order_status = trade.orderStatus if hasattr(trade, "orderStatus") else None
            status = order_status.status if order_status else "Unknown"
            filled = (
                float(order_status.filled)
                if order_status and hasattr(order_status, "filled")
                else 0.0
            )
            total = (
                float(order.totalQuantity) if hasattr(order, "totalQuantity") else 0.0
            )

            # Check if cancelled
            if status == "Cancelled":
                status_display = "[red]CANCELLED[/red]"
                if (
                    order_status
                    and hasattr(order_status, "whyHeld")
                    and order_status.whyHeld
                ):
                    status_display += f" ({order_status.whyHeld})"
            elif status in ["Submitted", "PreSubmitted", "PendingSubmit"]:
                status_display = "[yellow]OPEN[/]"
            elif status == "Filled":
                status_display = "[green]FILLED[/]"
            else:
                status_display = status

            action_color = "[bold green]" if order.action == "BUY" else "[bold red]"
            table.add_row(
                str(order.orderId),
                contract.symbol if hasattr(contract, "symbol") else "N/A",
                f"{action_color}{order.action}[/]",
                str(int(total)),
                order.orderType,
                status_display,
                f"{int(filled)}/{int(total)}",
            )

        # Show recent filled orders (last 10)
        for trade in all_trades[-10:]:
            order = trade.order
            contract = trade.contract
            order_status = trade.orderStatus if hasattr(trade, "orderStatus") else None
            filled = (
                order_status.filled
                if order_status and hasattr(order_status, "filled")
                else 0
            )

            if filled > 0 or (order_status and order_status.status == "Filled"):
                status = order_status.status if order_status else "Filled"
                total = order.totalQuantity if hasattr(order, "totalQuantity") else 0
                table.add_row(
                    str(order.orderId),
                    contract.symbol if hasattr(contract, "symbol") else "N/A",
                    f"[{'green' if order.action == 'BUY' else 'red'}]{order.action}[/]",
                    str(int(total)),
                    order.orderType,
                    "[green]FILLED[/]"
                    if status == "Filled"
                    else f"[yellow]{status}[/]",
                    f"{int(filled)}/{int(total)}",
                )

        console.print(table)
        console.print()

    except Exception as e:
        console.print(f"[red]❌ Error checking orders: {e}[/red]\n")
        import traceback

        traceback.print_exc()


def close_position(broker: IBKRBroker, portfolio: Portfolio) -> None:
    """Close an open position."""
    console.print("\n[bold cyan]📤 Close Position[/bold cyan]\n")

    try:
        # Get positions from IB
        ib = broker._connect()
        positions = ib.positions()

        open_positions = [p for p in positions if p.position != 0]

        if not open_positions:
            console.print("[yellow]No open positions to close[/yellow]\n")
            return

        console.print("Open positions:")
        for i, pos in enumerate(open_positions, 1):
            symbol = pos.contract.symbol
            size = pos.position
            avg_cost = pos.avgCost
            console.print(f"  {i}. {symbol}: {int(size)} contracts @ ${avg_cost:,.2f}")

        choice = Prompt.ask("\nSelect position to close (number)", default="1")

        try:
            idx = int(choice) - 1
            selected_pos = open_positions[idx]
            symbol = selected_pos.contract.symbol
            size = selected_pos.position
            avg_cost = selected_pos.avgCost
        except (ValueError, IndexError):
            console.print("[red]Invalid selection[/red]\n")
            return

        # Determine close side (opposite of current position)
        close_side = "SELL" if size > 0 else "BUY"
        close_size = abs(int(size))

        console.print("\n[bold yellow]Closing position:[/bold yellow]")
        console.print(f"  Symbol: {symbol}")
        console.print(f"  Current Size: {int(size)} contracts")
        console.print(f"  Entry Price: ${avg_cost:,.2f}")
        console.print(f"  Close Side: {close_side}")
        console.print(f"  Close Size: {close_size} contracts")

        if not Confirm.ask("\nConfirm close?"):
            console.print("[yellow]Close cancelled[/yellow]\n")
            return

        try:
            from datetime import datetime, timezone
            from pearlalgo.core.events import OrderEvent

            # Create close order (opposite side, same size)
            order = OrderEvent(
                timestamp=datetime.now(timezone.utc),
                symbol=symbol,
                side=close_side,
                quantity=close_size,
                order_type="MKT",
                limit_price=None,
                metadata={
                    "profile": "live",
                    "sec_type": "FUT",
                    "trading_class": symbol,
                    "action": "close_position",
                },
            )

            console.print(f"\n[dim]Closing {close_size} {symbol} contracts...[/dim]")
            order_id = broker.submit_order(order)

            if order_id:
                console.print("[green]✅ Close order submitted successfully![/green]")
                console.print(f"  Order ID: {order_id}\n")
            else:
                console.print("[yellow]⚠️  Order may be in dry-run mode[/yellow]\n")

        except Exception as e:
            console.print(f"[red]❌ Error closing position: {e}[/red]\n")
            import traceback

            traceback.print_exc()

    except Exception as e:
        console.print(f"[red]❌ Error: {e}[/red]\n")
        import traceback

        traceback.print_exc()


def test_connection():
    """Test IB Gateway connection."""
    console.print("\n[bold cyan]🔌 Testing IB Gateway Connection...[/bold cyan]\n")

    try:
        settings = get_settings()
        profile = load_profile()

        portfolio = Portfolio(cash=profile.starting_balance)
        risk_guard = RiskGuard(RiskLimits(max_daily_loss=profile.daily_loss_limit))
        broker = IBKRBroker(portfolio, settings=settings, risk_guard=risk_guard)

        # Test connection
        ib = broker._connect()

        console.print("[green]✅ Connection successful![/green]")
        console.print(f"  Host: {settings.ib_host}")
        console.print(f"  Port: {settings.ib_port}")
        console.print(f"  Client ID: {settings.ib_client_id}")
        console.print(f"  Profile: {settings.profile}")
        console.print(
            f"  Live Trading: {'✅ Enabled' if settings.allow_live_trading else '❌ Disabled (DRY RUN)'}\n"
        )

        if not settings.allow_live_trading:
            console.print("[yellow]⚠️  WARNING: Live trading is disabled![/yellow]")
            console.print(
                "[yellow]   Orders will be logged but not executed (DRY RUN mode)[/yellow]\n"
            )

        return True, broker, portfolio

    except Exception as e:
        console.print(f"[red]❌ Connection failed: {e}[/red]\n")
        import traceback

        traceback.print_exc()
        return False, None, None


def main():
    """Main manual trading test interface."""
    console.print()
    console.print(
        Panel.fit(
            "[bold cyan]🧪 Manual Trading Test[/bold cyan]\n"
            "[dim]Test entering and closing trades manually[/dim]",
            border_style="cyan",
            box=box.ROUNDED,
        )
    )
    console.print()

    # Test connection
    success, broker, portfolio = test_connection()
    if not success:
        console.print("[red]Cannot proceed without connection[/red]\n")
        return 1

    while True:
        console.print(
            "[bold cyan]╔═══════════════════════════════════════════════════════════╗[/bold cyan]"
        )
        console.print(
            "[bold cyan]║[/bold cyan]  [bold yellow]🧪 Manual Trading Test Menu[/bold yellow]                        [bold cyan]║[/bold cyan]"
        )
        console.print(
            "[bold cyan]╚═══════════════════════════════════════════════════════════╝[/bold cyan]\n"
        )

        table = Table(show_header=False, box=box.SIMPLE, padding=(0, 2))
        table.add_row(
            "[bold green]1.[/bold green]",
            "📊 Show Positions",
            "View current open positions",
        )
        table.add_row(
            "[bold green]2.[/bold green]",
            "📈 Enter Trade",
            "Manually enter a new trade",
        )
        table.add_row(
            "[bold green]3.[/bold green]", "📤 Close Position", "Close an open position"
        )
        table.add_row(
            "[bold green]4.[/bold green]",
            "🔄 Refresh Positions",
            "Update position data",
        )
        table.add_row(
            "[bold green]5.[/bold green]",
            "📋 Check Orders",
            "View recent orders and fills",
        )
        table.add_row(
            "[bold green]6.[/bold green]", "🚪 Exit", "Quit manual trading test"
        )

        console.print(table)
        console.print()

        choice = Prompt.ask(
            "Select option", choices=["1", "2", "3", "4", "5", "6"], default="6"
        )

        if choice == "1":
            show_positions(broker, portfolio)
        elif choice == "2":
            enter_trade(broker, portfolio)
        elif choice == "3":
            close_position(broker, portfolio)
        elif choice == "4":
            console.print("\n[dim]Refreshing positions...[/dim]")
            try:
                # Force refresh from IB
                ib = broker._connect()
                ib.reqPositions()  # Request position updates
                import time

                time.sleep(1)  # Give IB time to send updates
                console.print("[green]✅ Positions refreshed[/green]\n")
            except Exception as e:
                console.print(
                    f"[yellow]⚠️  Refresh completed (may need to check positions again): {e}[/yellow]\n"
                )
        elif choice == "5":
            check_orders(broker)
        elif choice == "6":
            console.print("\n[bold cyan]👋 Exiting manual trading test[/bold cyan]\n")
            break

        if choice != "6":
            Prompt.ask("\n[dim]Press Enter to continue...[/dim]", default="")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
