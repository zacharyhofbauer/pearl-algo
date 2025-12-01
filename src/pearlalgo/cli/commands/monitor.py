"""Live trading monitor - Real-time feed of trading activity."""

from __future__ import annotations

import click
import time
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd

from rich.console import Console
from rich.live import Live
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from rich import box
from rich.text import Text

console = Console()


def get_latest_trades(perf_path: Path, limit: int = 10) -> pd.DataFrame:
    """Get latest trades from performance log."""
    if not perf_path.exists():
        return pd.DataFrame()
    
    try:
        df = pd.read_csv(perf_path, parse_dates=["timestamp"])
        # Get most recent entries
        df = df.tail(limit).copy()
        return df
    except Exception:
        return pd.DataFrame()


def get_latest_signals(signals_dir: Path) -> pd.DataFrame:
    """Get latest signals."""
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    signals_file = signals_dir / f"{today}_signals.csv"
    
    if not signals_file.exists():
        return pd.DataFrame()
    
    try:
        df = pd.read_csv(signals_file, parse_dates=["timestamp"])
        return df.tail(10)
    except Exception:
        return pd.DataFrame()


def create_live_monitor() -> Layout:
    """Create live trading monitor layout."""
    from pearlalgo.futures.performance import DEFAULT_PERF_PATH
    from pearlalgo.futures.config import load_profile
    from pearlalgo.futures.risk import compute_risk_state
    from pearlalgo.futures.performance import load_performance
    
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="main"),
        Layout(name="footer", size=2)
    )
    
    layout["main"].split_row(
        Layout(name="left"),
        Layout(name="right")
    )
    
    layout["left"].split_column(
        Layout(name="trades", ratio=2),
        Layout(name="signals", ratio=1)
    )
    
    # Header
    now = datetime.now(timezone.utc)
    header_text = Text(f"📊 Live Trading Monitor", style="bold cyan")
    header_text.append(f" | {now.strftime('%Y-%m-%d %H:%M:%S UTC')}", style="dim")
    layout["header"].update(Panel(header_text, border_style="cyan", box=box.DOUBLE))
    
    # Latest Trades
    perf_path = DEFAULT_PERF_PATH
    trades_df = get_latest_trades(perf_path, limit=15)
    
    if not trades_df.empty:
        trades_table = Table(title="💰 Latest Trades", box=box.ROUNDED, show_header=True, header_style="bold cyan")
        trades_table.add_column("Time", style="dim", width=12)
        trades_table.add_column("Symbol", style="yellow", width=6)
        trades_table.add_column("Side", justify="center", width=6)
        trades_table.add_column("Size", justify="right", width=6)
        trades_table.add_column("Price", justify="right", width=10)
        trades_table.add_column("P&L", justify="right", width=12)
        trades_table.add_column("Status", width=12)
        
        for _, row in trades_df.iterrows():
            timestamp = row.get("timestamp", pd.NaT)
            if pd.notna(timestamp):
                time_str = timestamp.strftime("%H:%M:%S") if hasattr(timestamp, 'strftime') else str(timestamp)[:8]
            else:
                time_str = "N/A"
            
            symbol = str(row.get("symbol", "N/A"))
            side = str(row.get("side", "N/A")).upper()
            size = row.get("filled_size", 0) or row.get("requested_size", 0)
            price = row.get("entry_price", 0.0) or row.get("exit_price", 0.0)
            pnl = row.get("realized_pnl", 0.0) or row.get("unrealized_pnl", 0.0)
            status = str(row.get("risk_status", "OK"))
            
            # Color coding
            side_color = "[bold green]" if side == "LONG" else "[bold red]" if side == "SHORT" else "[dim]"
            pnl_color = "[green]" if pnl > 0 else "[red]" if pnl < 0 else "[dim]"
            status_color = "[green]" if status == "OK" else "[yellow]" if "NEAR" in status else "[red]"
            
            trades_table.add_row(
                time_str,
                symbol,
                f"{side_color}{side}[/]",
                str(int(size)) if size else "0",
                f"${price:,.2f}" if price else "N/A",
                f"{pnl_color}${pnl:,.2f}[/]" if pnl else "$0.00",
                f"{status_color}{status}[/]"
            )
        
        layout["trades"].update(Panel(trades_table, border_style="cyan", box=box.ROUNDED))
    else:
        layout["trades"].update(Panel("[dim]No trades yet...[/dim]", title="💰 Latest Trades", border_style="yellow"))
    
    # Latest Signals
    signals_dir = Path("signals")
    signals_df = get_latest_signals(signals_dir)
    
    if not signals_df.empty:
        signals_table = Table(title="📋 Latest Signals", box=box.SIMPLE, show_header=True, header_style="bold cyan")
        signals_table.add_column("Time", style="dim", width=12)
        signals_table.add_column("Symbol", style="yellow", width=6)
        signals_table.add_column("Direction", justify="center", width=10)
        signals_table.add_column("Size", justify="right", width=6)
        
        for _, row in signals_df.tail(5).iterrows():
            timestamp = row.get("timestamp", "")
            time_str = str(timestamp)[:19] if len(str(timestamp)) > 19 else str(timestamp)
            
            symbol = str(row.get("symbol", "N/A"))
            direction = str(row.get("direction", "FLAT")).upper()
            size = row.get("size_hint", 0)
            
            dir_color = "[bold green]" if direction == "BUY" else "[bold red]" if direction == "SELL" else "[dim]"
            
            signals_table.add_row(
                time_str,
                symbol,
                f"{dir_color}{direction}[/]",
                str(int(size)) if size else "0"
            )
        
        layout["signals"].update(Panel(signals_table, border_style="cyan", box=box.ROUNDED))
    else:
        layout["signals"].update(Panel("[dim]No signals yet...[/dim]", title="📋 Latest Signals", border_style="yellow"))
    
    # Right side - Performance Summary
    perf_df = load_performance(perf_path)
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    today_df = perf_df[perf_df["timestamp"].dt.strftime("%Y%m%d") == today] if "timestamp" in perf_df.columns and not perf_df.empty else pd.DataFrame()
    
    profile = load_profile()
    realized_pnl = today_df["realized_pnl"].fillna(0).sum() if not today_df.empty else 0.0
    unrealized_pnl = 0.0  # Would need to compute from open positions
    
    risk_state = compute_risk_state(
        profile,
        day_start_equity=profile.starting_balance,
        realized_pnl=realized_pnl,
        unrealized_pnl=unrealized_pnl,
        trades_today=len(today_df) if not today_df.empty else 0,
        max_trades=profile.max_trades,
        now=datetime.now(timezone.utc),
    )
    
    perf_table = Table(show_header=False, box=box.SIMPLE, padding=(0, 1))
    total_pnl = realized_pnl + unrealized_pnl
    pnl_color = "[green]" if total_pnl >= 0 else "[red]"
    
    perf_table.add_row("Daily P&L:", f"{pnl_color}${total_pnl:,.2f}[/]")
    perf_table.add_row("  Realized:", f"${realized_pnl:,.2f}")
    perf_table.add_row("  Unrealized:", f"${unrealized_pnl:,.2f}")
    perf_table.add_row("", "")
    perf_table.add_row("Trades Today:", f"{len(today_df)}")
    perf_table.add_row("Total Trades:", f"{len(perf_df)}")
    perf_table.add_row("", "")
    perf_table.add_row("Risk Status:", f"[{'green' if risk_state.status == 'OK' else 'yellow' if 'NEAR' in risk_state.status else 'red'}]{risk_state.status}[/]")
    perf_table.add_row("Buffer:", f"${risk_state.remaining_loss_buffer:,.2f}")
    
    layout["right"].update(Panel(perf_table, title="📊 Performance Summary", border_style="cyan", box=box.ROUNDED))
    
    # Footer
    footer_text = Text("Press Ctrl+C to exit | Auto-refresh: 2s", style="dim", justify="center")
    layout["footer"].update(Panel(footer_text, border_style="dim"))
    
    return layout


@click.command(name="monitor")
@click.option("--refresh", type=float, default=2.0, help="Refresh interval in seconds (default: 2)")
@click.pass_context
def monitor_cmd(ctx: click.Context, refresh: float) -> None:
    """Live trading monitor with real-time activity feed."""
    console.print(f"\n[bold cyan]📊 Starting Live Trading Monitor (refreshes every {refresh}s)[/bold cyan]")
    console.print("[dim]Press Ctrl+C to exit[/dim]\n")
    
    try:
        with Live(create_live_monitor(), refresh_per_second=1.0/refresh, screen=True) as live:
            while True:
                time.sleep(refresh)
                live.update(create_live_monitor())
    except KeyboardInterrupt:
        console.print("\n[bold yellow]Monitor closed[/bold yellow]\n")

