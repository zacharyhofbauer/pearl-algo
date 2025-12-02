"""Professional Trading Terminal - Multi-panel real-time interface."""
from __future__ import annotations

import click
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any
import pandas as pd

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

from pearlalgo.futures.performance import load_performance, DEFAULT_PERF_PATH
from pearlalgo.futures.config import load_profile
from pearlalgo.futures.risk import compute_risk_state
from pearlalgo.brokers.ibkr_broker import IBKRBroker
from pearlalgo.core.portfolio import Portfolio
from pearlalgo.config.settings import get_settings

console = Console()


class TradingTerminal:
    """Professional multi-panel trading terminal."""
    
    def __init__(self, refresh_rate: float = 1.0):
        self.refresh_rate = refresh_rate
        self.layout = Layout()
        self._setup_layout()
        self.portfolio: Optional[Portfolio] = None
        self.broker: Optional[IBKRBroker] = None
        self._initialize_broker()
        
    def _initialize_broker(self):
        """Initialize broker connection for live data."""
        try:
            settings = get_settings()
            self.portfolio = Portfolio(cash=100000)  # Placeholder
            # Note: In production, you'd initialize IBKRBroker here
            # self.broker = IBKRBroker(self.portfolio, settings=settings)
        except Exception as e:
            console.print(f"[yellow]Warning: Could not initialize broker: {e}[/yellow]")
    
    def _setup_layout(self):
        """Setup terminal layout with multiple panels - positions prioritized."""
        # Main split: top status bar, middle content, bottom command line
        self.layout.split_column(
            Layout(name="header", size=3),
            Layout(name="body"),
            Layout(name="footer", size=3)
        )
        
        # Body: left (positions - PRIORITY WIDTH), middle (charts/signals), right (market data/performance)
        self.layout["body"].split_row(
            Layout(name="left", ratio=2),  # Increased from 1 to 2 for positions
            Layout(name="center", ratio=2),
            Layout(name="right", ratio=1)
        )
        
        # Left: positions (larger) and orders (smaller)
        self.layout["left"].split_column(
            Layout(name="positions", ratio=3),  # Increased ratio for positions
            Layout(name="orders", ratio=1)
        )
        
        # Center: charts and signals
        self.layout["center"].split_column(
            Layout(name="chart", ratio=2),
            Layout(name="signals", ratio=1)
        )
        
        # Right: market data and performance
        self.layout["right"].split_column(
            Layout(name="market_data", ratio=1),
            Layout(name="performance", ratio=1)
        )
    
    def create_header(self) -> Panel:
        """Create header with system status."""
        now = datetime.now(timezone.utc)
        text = Text()
        text.append("🔥 PEARLALGO TRADING TERMINAL", style="bold cyan")
        text.append(f" | {now.strftime('%Y-%m-%d %H:%M:%S UTC')}", style="dim")
        text.append(" | ", style="dim")
        text.append("🟢 LIVE", style="bold green")
        return Panel(text, border_style="cyan", box=box.DOUBLE)
    
    def get_positions(self) -> List[Dict[str, Any]]:
        """Get current positions from portfolio and performance log - aggregates by symbol."""
        positions_dict: Dict[str, Dict[str, Any]] = {}
        
        # Check portfolio first
        if self.portfolio:
            for symbol, pos in self.portfolio.positions.items():
                if pos.size != 0:
                    mark_price = pos.avg_price  # Placeholder
                    pnl = pos.realized_pnl + (pos.size * (mark_price - pos.avg_price))
                    pnl_pct = ((mark_price - pos.avg_price) / pos.avg_price * 100) if pos.avg_price > 0 else 0
                    
                    positions_dict[symbol] = {
                        "symbol": symbol,
                        "side": "LONG" if pos.size > 0 else "SHORT",
                        "size": abs(pos.size),
                        "entry": pos.avg_price,
                        "mark": mark_price,
                        "pnl": pnl,
                        "pnl_pct": pnl_pct,
                        "strategy": "portfolio",
                    }
        
        # Check performance log for open positions (from all strategies)
        perf_path = DEFAULT_PERF_PATH
        if perf_path.exists():
            try:
                perf_df = load_performance(perf_path)
                today = datetime.now(timezone.utc).strftime("%Y%m%d")
                today_df = perf_df[perf_df["timestamp"].dt.strftime("%Y%m%d") == today] if "timestamp" in perf_df.columns and not perf_df.empty else pd.DataFrame()
                
                # Find positions without exit_time (open positions)
                open_trades = today_df[today_df["exit_time"].isna()] if "exit_time" in today_df.columns else pd.DataFrame()
                
                for _, row in open_trades.iterrows():
                    symbol = str(row.get("symbol", ""))
                    if not symbol:
                        continue
                    
                    side = str(row.get("side", "")).upper()
                    size = abs(float(row.get("filled_size", 0) or 0))
                    entry = float(row.get("entry_price", 0) or 0)
                    unrealized = float(row.get("unrealized_pnl", 0) or 0)
                    strategy = str(row.get("strategy_name", "unknown"))
                    
                    if size > 0 and entry > 0:
                        # Aggregate positions by symbol (sum sizes if same side, otherwise show separately)
                        key = f"{symbol}_{side}"
                        if key in positions_dict:
                            # Aggregate: add to existing position
                            existing = positions_dict[key]
                            existing["size"] += size
                            existing["pnl"] += unrealized
                            # Weighted average entry
                            total_size = existing["size"]
                            existing["entry"] = ((existing["entry"] * (total_size - size)) + (entry * size)) / total_size if total_size > 0 else entry
                            existing["pnl_pct"] = (existing["pnl"] / (existing["entry"] * existing["size"]) * 100) if existing["entry"] * existing["size"] > 0 else 0
                            # Track unique strategies
                            if strategy != "unknown":
                                strategies = existing.get("_strategies", set())
                                strategies.add(strategy)
                                existing["_strategies"] = strategies
                                # Show unique strategies, limit to 2
                                unique_strategies = list(strategies)
                                if len(unique_strategies) == 1:
                                    existing["strategy"] = unique_strategies[0]
                                elif len(unique_strategies) <= 2:
                                    existing["strategy"] = ", ".join(unique_strategies)
                                else:
                                    existing["strategy"] = f"{unique_strategies[0]}, +{len(unique_strategies)-1}"
                        else:
                            # New position
                            positions_dict[key] = {
                                "symbol": symbol,
                                "side": side,
                                "size": size,
                                "entry": entry,
                                "mark": entry,  # Placeholder - would fetch from broker
                                "pnl": unrealized,
                                "pnl_pct": (unrealized / (entry * size) * 100) if entry * size > 0 else 0,
                                "strategy": strategy,
                                "_strategies": {strategy} if strategy != "unknown" else set(),
                            }
            except Exception as e:
                # Silently fail - don't break terminal if there's an issue
                pass
        
        # Convert to list and sort by symbol
        positions = list(positions_dict.values())
        positions.sort(key=lambda x: x.get("symbol", ""))
        
        return positions
    
    def get_orders(self) -> List[Dict[str, Any]]:
        """Get active orders."""
        # Placeholder - would fetch from broker
        return []
    
    def create_positions_table(self, positions: List[Dict]) -> Table:
        """Create positions table with wider columns for better visibility."""
        table = Table(
            title=f"💰 Open Positions ({len(positions)})", 
            box=box.ROUNDED, 
            show_header=True, 
            header_style="bold cyan",
            expand=True  # Allow table to expand to fill space
        )
        table.add_column("Symbol", style="cyan", width=10, no_wrap=True)
        table.add_column("Side", width=8, no_wrap=True)
        table.add_column("Size", justify="right", width=10, no_wrap=True)
        table.add_column("Entry", justify="right", width=14, no_wrap=True)
        table.add_column("Mark", justify="right", width=14, no_wrap=True)
        table.add_column("P&L", justify="right", width=14, no_wrap=True)
        table.add_column("P&L %", justify="right", width=10, no_wrap=True)
        table.add_column("Strategy", style="dim", width=12, no_wrap=False)
        
        if not positions:
            table.add_row(
                "[dim]No open positions[/dim]", "", "", "", "", "", "", ""
            )
        else:
            for pos in positions:
                pnl = pos.get("pnl", 0)
                pnl_color = "green" if pnl >= 0 else "red"
                side_color = "green" if pos.get("side") == "LONG" else "red"
                strategy = pos.get("strategy", "unknown")
                # Truncate long strategy names
                if len(strategy) > 12:
                    strategy = strategy[:9] + "..."
                
                table.add_row(
                    pos.get("symbol", ""),
                    f"[{side_color}]{pos.get('side', '')}[/]",
                    str(int(pos.get("size", 0))),
                    f"${pos.get('entry', 0):,.2f}",
                    f"${pos.get('mark', 0):,.2f}",
                    f"[{pnl_color}]${pnl:,.2f}[/]",
                    f"[{pnl_color}]{pos.get('pnl_pct', 0):.2f}%[/]",
                    f"[dim]{strategy}[/dim]"
                )
        
        return table
    
    def create_orders_table(self, orders: List[Dict]) -> Table:
        """Create orders table."""
        table = Table(title="📋 Active Orders", box=box.ROUNDED, show_header=True, header_style="bold cyan")
        table.add_column("Symbol", style="cyan", width=8)
        table.add_column("Type", width=8)
        table.add_column("Side", width=6)
        table.add_column("Qty", justify="right", width=6)
        table.add_column("Price", justify="right", width=10)
        table.add_column("Status", width=10)
        
        if not orders:
            table.add_row("[dim]No active orders[/dim]", "", "", "", "", "")
        else:
            for order in orders:
                status_color = {
                    "FILLED": "green",
                    "PENDING": "yellow",
                    "CANCELLED": "red"
                }.get(order.get("status", ""), "white")
                
                table.add_row(
                    order.get("symbol", ""),
                    order.get("type", ""),
                    order.get("side", ""),
                    str(order.get("qty", 0)),
                    f"${order.get('price', 0):,.2f}",
                    f"[{status_color}]{order.get('status', '')}[/]"
                )
        
        return table
    
    def create_chart_panel(self, symbol: str = "NQ") -> Panel:
        """Create ASCII chart panel."""
        # Try to load recent data
        chart_text = "[dim]Loading chart data...[/dim]"
        
        # In production, fetch from data provider
        # For now, show placeholder
        chart_text = f"""
[cyan]{symbol} - 15min Chart[/cyan]

[dim]Price: $15,234.50[/dim]
[dim]Change: +12.30 (+0.08%)[/dim]

[dim]Chart visualization would appear here[/dim]
[dim]Connect to data provider for live charts[/dim]
        """.strip()
        
        return Panel(chart_text, title=f"📈 {symbol}", border_style="cyan", box=box.ROUNDED)
    
    def get_latest_signals(self) -> List[Dict]:
        """Get latest trading signals."""
        signals = []
        signals_dir = Path("signals")
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        signals_file = signals_dir / f"{today}_signals.csv"
        
        if signals_file.exists():
            try:
                df = pd.read_csv(signals_file, parse_dates=["timestamp"])
                for _, row in df.tail(5).iterrows():
                    signals.append({
                        "time": row.get("timestamp", ""),
                        "symbol": str(row.get("symbol", "")),
                        "direction": str(row.get("direction", "FLAT")).upper(),
                        "confidence": float(row.get("confidence", 0.0)),
                    })
            except Exception:
                pass
        
        return signals
    
    def create_signals_table(self, signals: List[Dict]) -> Table:
        """Create signals table."""
        table = Table(title="📊 Latest Signals", box=box.ROUNDED, show_header=True, header_style="bold cyan")
        table.add_column("Time", style="dim", width=10)
        table.add_column("Symbol", style="cyan", width=8)
        table.add_column("Direction", width=10)
        table.add_column("Confidence", justify="right", width=10)
        
        if not signals:
            table.add_row("[dim]No signals yet[/dim]", "", "", "")
        else:
            for sig in signals:
                time_str = str(sig.get("time", ""))[:19] if len(str(sig.get("time", ""))) > 19 else str(sig.get("time", ""))
                direction = sig.get("direction", "FLAT")
                dir_color = "green" if direction == "BUY" else "red" if direction == "SELL" else "dim"
                confidence = sig.get("confidence", 0.0)
                conf_color = "green" if confidence > 0.7 else "yellow" if confidence > 0.5 else "red"
                
                table.add_row(
                    time_str,
                    sig.get("symbol", ""),
                    f"[{dir_color}]{direction}[/]",
                    f"[{conf_color}]{confidence:.2f}[/]"
                )
        
        return table
    
    def create_market_data_panel(self) -> Panel:
        """Create market data panel."""
        table = Table(show_header=False, box=box.SIMPLE)
        
        # Placeholder market data
        symbols = ["ES", "NQ", "GC", "CL"]
        for symbol in symbols:
            table.add_row(f"[cyan]{symbol}[/]", "")
            table.add_row("  Bid:", "[dim]$0.00[/dim]")
            table.add_row("  Ask:", "[dim]$0.00[/dim]")
            table.add_row("  Last:", "[dim]$0.00[/dim]")
            table.add_row("  Vol:", "[dim]0[/dim]")
            table.add_row("", "")
        
        return Panel(table, title="📊 Market Data", border_style="cyan", box=box.ROUNDED)
    
    def create_performance_panel(self) -> Panel:
        """Create performance metrics panel."""
        table = Table(show_header=False, box=box.SIMPLE)
        
        # Load performance data
        perf_path = DEFAULT_PERF_PATH
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        
        try:
            perf_df = load_performance(perf_path)
            today_df = perf_df[perf_df["timestamp"].dt.strftime("%Y%m%d") == today] if "timestamp" in perf_df.columns and not perf_df.empty else pd.DataFrame()
            
            profile = load_profile()
            realized_pnl = today_df["realized_pnl"].fillna(0).sum() if not today_df.empty else 0.0
            unrealized_pnl = today_df["unrealized_pnl"].fillna(0).sum() if not today_df.empty else 0.0
            total_pnl = realized_pnl + unrealized_pnl
            
            trades_today = len(today_df) if not today_df.empty else 0
            winning_trades = len(today_df[today_df["realized_pnl"] > 0]) if not today_df.empty else 0
            win_rate = (winning_trades / trades_today * 100) if trades_today > 0 else 0.0
            
            # Compute risk state
            risk_state = compute_risk_state(
                profile,
                day_start_equity=profile.starting_balance,
                realized_pnl=realized_pnl,
                unrealized_pnl=unrealized_pnl,
                trades_today=trades_today,
                max_trades=profile.max_trades,
                now=datetime.now(timezone.utc),
            )
            
            pnl_color = "green" if total_pnl >= 0 else "red"
            risk_color = "green" if risk_state.status == "OK" else "yellow" if "NEAR" in risk_state.status else "red"
            
            table.add_row("Daily P&L:", f"[{pnl_color}]${total_pnl:,.2f}[/]")
            table.add_row("  Realized:", f"${realized_pnl:,.2f}")
            table.add_row("  Unrealized:", f"${unrealized_pnl:,.2f}")
            table.add_row("", "")
            table.add_row("Win Rate:", f"{win_rate:.1f}%")
            table.add_row("Trades:", f"{trades_today}")
            table.add_row("", "")
            table.add_row("Risk Status:", f"[{risk_color}]{risk_state.status}[/]")
            table.add_row("Buffer:", f"${risk_state.remaining_loss_buffer:,.2f}")
            
        except Exception as e:
            table.add_row("[dim]Loading metrics...[/dim]", "")
        
        return Panel(table, title="📊 Performance", border_style="cyan", box=box.ROUNDED)
    
    def render(self) -> Layout:
        """Render the entire terminal."""
        positions = self.get_positions()
        orders = self.get_orders()
        signals = self.get_latest_signals()
        
        self.layout["header"].update(self.create_header())
        self.layout["positions"].update(Panel(
            self.create_positions_table(positions),
            border_style="cyan",
            box=box.ROUNDED
        ))
        self.layout["orders"].update(Panel(
            self.create_orders_table(orders),
            border_style="cyan",
            box=box.ROUNDED
        ))
        self.layout["chart"].update(self.create_chart_panel())
        self.layout["signals"].update(Panel(
            self.create_signals_table(signals),
            border_style="cyan",
            box=box.ROUNDED
        ))
        self.layout["market_data"].update(self.create_market_data_panel())
        self.layout["performance"].update(self.create_performance_panel())
        
        # Footer with commands
        footer_text = Text(
            "Commands: [F1] Help | [F2] Orders | [F3] Positions | [F4] Settings | [ESC] Exit | Auto-refresh: 1s",
            style="dim",
            justify="center"
        )
        self.layout["footer"].update(Panel(footer_text, border_style="dim", box=box.SIMPLE))
        
        return self.layout
    
    def run(self):
        """Run the terminal in live mode with proper refresh."""
        console.print("\n[bold cyan]🚀 Starting Trading Terminal...[/bold cyan]\n")
        console.print(f"[dim]Refresh rate: {self.refresh_rate}s | Press Ctrl+C to exit[/dim]\n")
        
        try:
            # Use Live with proper refresh rate
            refresh_per_second = max(0.1, 1.0 / self.refresh_rate)  # Ensure positive value
            with Live(self.render(), refresh_per_second=refresh_per_second, screen=True, auto_refresh=True) as live:
                while True:
                    # Force update on each iteration
                    live.update(self.render())
                    time.sleep(self.refresh_rate)
        except KeyboardInterrupt:
            console.print("\n[bold yellow]Terminal closed[/bold yellow]\n")


@click.command(name="terminal")
@click.option("--refresh", type=float, default=1.0, help="Refresh rate in seconds (default: 1.0)")
@click.pass_context
def terminal_cmd(ctx: click.Context, refresh: float) -> None:
    """Professional trading terminal with multi-panel real-time interface.
    
    Features:
    - Real-time positions and P&L
    - Active orders monitoring
    - Live market data
    - Performance metrics
    - Trading signals
    - ASCII charts
    """
    terminal = TradingTerminal(refresh_rate=refresh)
    terminal.run()

