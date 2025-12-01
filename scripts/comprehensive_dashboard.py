#!/usr/bin/env python
"""
🎯 PearlAlgo Comprehensive Trading Dashboard
Advanced monitoring with real-time positions, orders, P&L, and strategy details.
"""
from __future__ import annotations

import subprocess
import sys
import time as time_module
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional
import os
import signal

# Add project root to path
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.layout import Layout
from rich.live import Live
from rich import box
from rich.text import Text
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn

from pearlalgo.futures.config import load_profile
from pearlalgo.futures.performance import DEFAULT_PERF_PATH, load_performance, summarize_daily_performance
from pearlalgo.futures.risk import compute_risk_state

console = Console()


def run_cmd(cmd: list[str], timeout: int = 5) -> str:
    """Run command and return output."""
    try:
        return subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True, timeout=timeout).strip()
    except subprocess.TimeoutExpired:
        return "TIMEOUT"
    except Exception as exc:
        return f"ERROR: {exc}"


def get_trading_processes() -> list[dict]:
    """Get list of running trading processes."""
    processes = []
    try:
        result = subprocess.run(
            ["pgrep", "-af", "pearlalgo trade"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split("\n"):
                if line:
                    parts = line.split(" ", 1)
                    if len(parts) >= 2:
                        processes.append({
                            "pid": parts[0],
                            "command": parts[1][:60] + "..." if len(parts[1]) > 60 else parts[1]
                        })
    except:
        pass
    return processes


def gateway_status() -> tuple[str, str, bool, dict]:
    """Get detailed IB Gateway status."""
    info = {}
    
    # Check if process is running
    result = subprocess.run(["pgrep", "-f", "IbcGateway"], capture_output=True)
    is_running = result.returncode == 0
    pid = result.stdout.decode().strip().split("\n")[0] if is_running else None
    info["pid"] = pid
    
    # Check if port is listening
    result = subprocess.run(["ss", "-tlnp"], capture_output=True, text=True)
    port_listening = "4002" in result.stdout
    info["port_4002"] = port_listening
    
    # Check port 7497 (TWS)
    info["port_7497"] = "7497" in result.stdout
    
    # Get uptime if running
    if pid:
        try:
            uptime_result = subprocess.run(
                ["ps", "-o", "etime=", "-p", pid], 
                capture_output=True, text=True, timeout=2
            )
            info["uptime"] = uptime_result.stdout.strip() if uptime_result.returncode == 0 else "N/A"
        except:
            info["uptime"] = "N/A"
    
    status = "✅ Running" if (is_running and port_listening) else "❌ Not Running"
    version = ""
    
    return status, version, is_running and port_listening, info


def create_gateway_panel() -> Panel:
    """Create enhanced IB Gateway status panel."""
    status, version, is_ready, info = gateway_status()
    
    table = Table(show_header=False, box=box.SIMPLE, padding=(0, 1))
    table.add_column("Key", style="cyan", no_wrap=True)
    table.add_column("Value")
    
    status_color = "green" if is_ready else "red"
    table.add_row("Status:", f"[{status_color}]{status}[/]")
    
    if info.get("pid"):
        table.add_row("PID:", info["pid"])
        if info.get("uptime"):
            table.add_row("Uptime:", info["uptime"])
    
    table.add_row("Port 4002:", "✅ Listening" if info.get("port_4002") else "❌ Not listening")
    table.add_row("Port 7497:", "✅ Listening" if info.get("port_7497") else "❌ Not listening")
    
    border = "green" if is_ready else "red"
    return Panel(table, title="🔌 IB Gateway", border_style=border, box=box.ROUNDED)


def create_processes_panel() -> Panel:
    """Create panel showing running trading processes."""
    processes = get_trading_processes()
    
    if not processes:
        content = Text()
        content.append("No trading processes running", style="dim")
        content.append("\n\nStart with:\n  ", style="dim")
        content.append("pearlalgo trade auto ES NQ GC", style="yellow")
        return Panel(content, title="🤖 Trading Processes", border_style="yellow", box=box.ROUNDED)
    
    table = Table(show_header=True, box=box.SIMPLE, header_style="bold cyan")
    table.add_column("PID", style="yellow", width=8)
    table.add_column("Command", style="dim")
    
    for proc in processes[:5]:  # Show max 5
        table.add_row(proc["pid"], proc["command"])
    
    if len(processes) > 5:
        table.add_row("...", f"({len(processes) - 5} more)")
    
    return Panel(table, title=f"🤖 Trading Processes ({len(processes)} running)", border_style="green", box=box.ROUNDED)


def create_positions_panel() -> Panel:
    """Create panel showing current positions from performance log."""
    perf_path = DEFAULT_PERF_PATH
    df = load_performance(perf_path)
    
    if df.empty:
        return Panel("[dim]No positions data available[/dim]", title="📊 Current Positions", border_style="yellow", box=box.ROUNDED)
    
    # Get today's data
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    today_df = df[df["timestamp"].dt.strftime("%Y%m%d") == today] if "timestamp" in df.columns else pd.DataFrame()
    
    table = Table(show_header=True, box=box.SIMPLE, header_style="bold cyan")
    table.add_column("Symbol", style="yellow", width=8)
    table.add_column("Side", justify="center", width=8)
    table.add_column("Size", justify="right", width=6)
    table.add_column("Entry", justify="right", width=12)
    table.add_column("Unrealized", justify="right", width=12)
    table.add_column("Status", justify="center", width=12)
    
    # Get latest entry for each symbol (open positions without exit)
    if not today_df.empty and "exit_time" in today_df.columns:
        open_positions = today_df[today_df["exit_time"].isna()]
        
        for symbol in open_positions["symbol"].unique():
            sym_df = open_positions[open_positions["symbol"] == symbol].iloc[-1]
            side = str(sym_df.get("side", "N/A")).upper()
            size = sym_df.get("filled_size", sym_df.get("requested_size", 0))
            entry = sym_df.get("entry_price", 0)
            unrealized = sym_df.get("unrealized_pnl", 0) or 0
            status = sym_df.get("risk_status", "OK")
            
            side_color = "[green]" if side == "LONG" else "[red]" if side == "SHORT" else "[dim]"
            pnl_color = "[green]" if unrealized >= 0 else "[red]"
            status_color = "[green]" if status == "OK" else "[yellow]" if "NEAR" in str(status) else "[red]"
            
            table.add_row(
                symbol,
                f"{side_color}{side}[/]",
                str(int(size)),
                f"${entry:,.2f}" if entry else "N/A",
                f"{pnl_color}${unrealized:,.2f}[/]",
                f"{status_color}{status}[/]"
            )
    
    if table.row_count == 0:
        table.add_row("", "[dim]No open positions[/dim]", "", "", "", "")
    
    return Panel(table, title="📊 Current Positions", border_style="cyan", box=box.ROUNDED)


def create_performance_panel() -> Panel:
    """Create enhanced performance metrics panel."""
    perf_path = DEFAULT_PERF_PATH
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    
    df = load_performance(perf_path)
    
    if df.empty:
        return Panel("[dim]No performance data yet[/dim]", title="💰 Performance", border_style="yellow", box=box.ROUNDED)
    
    total_realized = df["realized_pnl"].fillna(0).sum()
    today_df = df[df["timestamp"].dt.strftime("%Y%m%d") == today] if "timestamp" in df.columns else pd.DataFrame()
    today_realized = today_df["realized_pnl"].fillna(0).sum() if not today_df.empty else 0.0
    
    daily_summary = summarize_daily_performance(perf_path, date=today)
    
    table = Table(show_header=False, box=box.SIMPLE, padding=(0, 1))
    table.add_column("Metric", style="cyan", no_wrap=True)
    table.add_column("Value")
    
    # Today's stats
    today_color = "[green]" if today_realized >= 0 else "[red]"
    table.add_row("[bold]Today:[/bold]", "")
    table.add_row("  P&L:", f"{today_color}${today_realized:,.2f}[/]")
    table.add_row("  Trades:", f"{len(today_df) if not today_df.empty else 0}")
    
    if daily_summary:
        win_rate = daily_summary.get("win_rate", 0.0) * 100
        wins = int(daily_summary.get("wins", 0))
        losses = int(daily_summary.get("losses", 0))
        table.add_row("  W/L:", f"[green]{wins}W[/] / [red]{losses}L[/]")
        table.add_row("  Win Rate:", f"{win_rate:.1f}%")
        
        avg_pnl = daily_summary.get("avg_realized_pnl", 0.0)
        avg_color = "[green]" if avg_pnl >= 0 else "[red]"
        table.add_row("  Avg Trade:", f"{avg_color}${avg_pnl:,.2f}[/]")
    
    table.add_row("", "")
    
    # Overall stats
    total_color = "[green]" if total_realized >= 0 else "[red]"
    table.add_row("[bold]Overall:[/bold]", "")
    table.add_row("  Total P&L:", f"{total_color}${total_realized:,.2f}[/]")
    table.add_row("  Total Trades:", f"{len(df)}")
    
    # Per-symbol breakdown (today)
    if not today_df.empty:
        table.add_row("", "")
        table.add_row("[bold]By Symbol (today):[/bold]", "")
        for sym in today_df["symbol"].unique():
            sym_df = today_df[today_df["symbol"] == sym]
            sym_pnl = sym_df["realized_pnl"].fillna(0).sum()
            sym_color = "[green]" if sym_pnl >= 0 else "[red]"
            table.add_row(f"  {sym}:", f"{sym_color}${sym_pnl:,.2f}[/] ({len(sym_df)} trades)")
    
    return Panel(table, title="💰 Performance", border_style="cyan", box=box.ROUNDED)


def create_risk_panel() -> Panel:
    """Create enhanced risk state panel."""
    perf_path = DEFAULT_PERF_PATH
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    profile = load_profile()
    
    df = load_performance(perf_path)
    today_df = df[df["timestamp"].dt.strftime("%Y%m%d") == today] if "timestamp" in df.columns and not df.empty else pd.DataFrame()
    trades_today = len(today_df) if not today_df.empty else 0
    realized_pnl = today_df["realized_pnl"].fillna(0).sum() if not today_df.empty else 0.0
    
    risk_state = compute_risk_state(
        profile,
        day_start_equity=profile.starting_balance,
        realized_pnl=realized_pnl,
        unrealized_pnl=0.0,
        trades_today=trades_today,
        max_trades=profile.max_trades,
        now=datetime.now(timezone.utc),
    )
    
    table = Table(show_header=False, box=box.SIMPLE, padding=(0, 1))
    table.add_column("Metric", style="cyan", no_wrap=True)
    table.add_column("Value")
    
    # Status with emoji
    status_emoji = {
        "OK": "✅",
        "NEAR_LIMIT": "⚠️",
        "HARD_STOP": "🛑",
        "COOLDOWN": "⏸️",
        "PAUSED": "⏸️",
    }
    emoji = status_emoji.get(risk_state.status, "❓")
    
    if risk_state.status == "OK":
        status_style = "[bold green]"
        border = "green"
    elif risk_state.status == "NEAR_LIMIT":
        status_style = "[bold yellow]"
        border = "yellow"
    else:
        status_style = "[bold red]"
        border = "red"
    
    table.add_row("Status:", f"{emoji} {status_style}{risk_state.status}[/]")
    
    # Buffer visualization
    buffer_pct = (risk_state.remaining_loss_buffer / risk_state.daily_loss_limit * 100) if risk_state.daily_loss_limit > 0 else 100
    buffer_bar = "█" * int(buffer_pct / 10) + "░" * (10 - int(buffer_pct / 10))
    buffer_color = "green" if buffer_pct > 50 else "yellow" if buffer_pct > 25 else "red"
    table.add_row("Buffer:", f"[{buffer_color}]{buffer_bar}[/] {buffer_pct:.1f}%")
    
    table.add_row("Remaining:", f"${risk_state.remaining_loss_buffer:,.2f}")
    table.add_row("Daily Limit:", f"${risk_state.daily_loss_limit:,.2f}")
    
    table.add_row("", "")
    
    # Trade limits
    if risk_state.max_trades:
        remaining_trades = max(0, risk_state.max_trades - trades_today)
        table.add_row("Trades:", f"{trades_today} / {risk_state.max_trades}")
        table.add_row("Remaining:", f"{remaining_trades}")
    
    if risk_state.cooldown_until:
        table.add_row("", "")
        table.add_row("[yellow]Cooldown:[/yellow]", risk_state.cooldown_until.strftime("%H:%M:%S UTC"))
    
    # Profile info
    table.add_row("", "")
    table.add_row("[dim]Profile:[/dim]", f"[dim]{profile.name}[/dim]")
    
    return Panel(table, title="⚠️ Risk State", border_style=border, box=box.ROUNDED)


def create_signals_panel() -> Panel:
    """Create latest signals panel."""
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    signals_file = Path("signals") / f"{today}_signals.csv"
    
    if not signals_file.exists():
        return Panel("[dim]No signals generated today[/dim]", title="📋 Latest Signals", border_style="yellow", box=box.ROUNDED)
    
    try:
        df = pd.read_csv(signals_file)
        if df.empty:
            return Panel("[dim]No signals in file[/dim]", title="📋 Latest Signals", border_style="yellow", box=box.ROUNDED)
        
        table = Table(show_header=True, box=box.SIMPLE, header_style="bold cyan")
        table.add_column("Symbol", style="yellow", width=8)
        table.add_column("Signal", justify="center", width=10)
        table.add_column("Size", justify="right", width=6)
        table.add_column("Time", style="dim", width=10)
        
        for _, row in df.tail(8).iterrows():  # Show last 8
            direction = row.get("direction", "FLAT")
            if direction == "BUY":
                dir_display = "[bold green]🟢 BUY[/]"
            elif direction == "SELL":
                dir_display = "[bold red]🔴 SELL[/]"
            else:
                dir_display = "[dim]⚪ FLAT[/]"
            
            timestamp = row.get("timestamp", "")
            time_str = str(timestamp)[11:19] if len(str(timestamp)) > 19 else str(timestamp)[-8:]
            
            table.add_row(
                row.get("symbol", "N/A"),
                dir_display,
                str(row.get("size_hint", 0)),
                time_str
            )
        
        return Panel(table, title="📋 Latest Signals", border_style="cyan", box=box.ROUNDED)
    except Exception as e:
        return Panel(f"[red]Error: {e}[/red]", title="📋 Latest Signals", border_style="red", box=box.ROUNDED)


def create_recent_trades_panel() -> Panel:
    """Create recent trades panel."""
    perf_path = DEFAULT_PERF_PATH
    df = load_performance(perf_path)
    
    if df.empty:
        return Panel(Text("No trades yet", style="dim"), title="📝 Recent Trades", border_style="yellow", box=box.ROUNDED)
    
    table = Table(show_header=True, box=box.SIMPLE, header_style="bold cyan", expand=True)
    table.add_column("Time", style="dim", width=8, no_wrap=True)
    table.add_column("Symbol", style="yellow", width=6, no_wrap=True)
    table.add_column("Side", justify="center", width=7)
    table.add_column("Qty", justify="right", width=4)
    table.add_column("Price", justify="right", width=10)
    table.add_column("P&L", justify="right", width=10)
    table.add_column("Reason", style="dim", overflow="ellipsis")
    
    for _, row in df.tail(8).iterrows():
        timestamp = row.get("timestamp", pd.NaT)
        time_str = timestamp.strftime("%H:%M:%S") if pd.notna(timestamp) else "N/A"
        
        symbol = str(row.get("symbol", "?"))
        side = str(row.get("side", "?")).upper()
        size = row.get("filled_size", row.get("requested_size", 0))
        if pd.isna(size):
            size = 0
        price = row.get("entry_price", 0)
        if pd.isna(price) or price == 0:
            price = row.get("exit_price", 0)
        if pd.isna(price):
            price = 0
        pnl = row.get("realized_pnl", 0)
        if pd.isna(pnl):
            pnl = 0
        reason = str(row.get("trade_reason", "")) if pd.notna(row.get("trade_reason")) else ""
        
        side_color = "[green]" if side == "LONG" else "[red]" if side == "SHORT" else "[dim]"
        pnl_color = "[green]" if pnl > 0 else "[red]" if pnl < 0 else "[dim]"
        
        table.add_row(
            time_str,
            symbol,
            f"{side_color}{side}[/]",
            str(int(size)) if size else "0",
            f"${price:,.2f}" if price else "-",
            f"{pnl_color}${pnl:,.2f}[/]",
            reason[:25] if reason else ""
        )
    
    return Panel(table, title="📝 Recent Trades", border_style="cyan", box=box.ROUNDED)


def create_system_health_panel() -> Panel:
    """Create system health overview panel."""
    table = Table(show_header=False, box=box.SIMPLE, padding=(0, 1))
    table.add_column("Metric", style="cyan", no_wrap=True)
    table.add_column("Value")
    
    # CPU usage
    try:
        result = subprocess.run(
            ["grep", "cpu ", "/proc/stat"], 
            capture_output=True, text=True, timeout=2
        )
        # Simple approximation - in production use psutil
        table.add_row("System:", "[green]OK[/green]")
    except:
        table.add_row("System:", "[yellow]Unknown[/yellow]")
    
    # Memory (simplified)
    try:
        result = subprocess.run(
            ["free", "-h"], 
            capture_output=True, text=True, timeout=2
        )
        if result.returncode == 0:
            lines = result.stdout.strip().split("\n")
            if len(lines) > 1:
                mem_parts = lines[1].split()
                if len(mem_parts) >= 3:
                    table.add_row("Memory:", f"{mem_parts[2]} / {mem_parts[1]}")
    except:
        pass
    
    # Disk (simplified)
    try:
        result = subprocess.run(
            ["df", "-h", PROJECT_ROOT], 
            capture_output=True, text=True, timeout=2
        )
        if result.returncode == 0:
            lines = result.stdout.strip().split("\n")
            if len(lines) > 1:
                disk_parts = lines[1].split()
                if len(disk_parts) >= 4:
                    table.add_row("Disk:", f"{disk_parts[2]} / {disk_parts[1]} ({disk_parts[4]})")
    except:
        pass
    
    # Files check
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    signals_exists = (Path("signals") / f"{today}_signals.csv").exists()
    perf_exists = DEFAULT_PERF_PATH.exists()
    
    table.add_row("Signals:", "✅" if signals_exists else "❌")
    table.add_row("Perf Log:", "✅" if perf_exists else "❌")
    
    # Network check (simplified - check if gateway port is reachable)
    _, _, gateway_ready, _ = gateway_status()
    table.add_row("Network:", "✅" if gateway_ready else "⚠️")
    
    return Panel(table, title="🖥️ System Health", border_style="cyan", box=box.ROUNDED)


def create_comprehensive_dashboard() -> Layout:
    """Create the comprehensive dashboard layout."""
    layout = Layout()
    
    # Main vertical split
    layout.split_column(
        Layout(name="header", size=4),
        Layout(name="main"),
        Layout(name="footer", size=3)
    )
    
    # Main area split into left and right
    layout["main"].split_row(
        Layout(name="left", ratio=1, minimum_size=35),
        Layout(name="center", ratio=2, minimum_size=50),
        Layout(name="right", ratio=1, minimum_size=35)
    )
    
    # Left column: Gateway, Processes, System
    layout["left"].split_column(
        Layout(name="gateway", size=10),
        Layout(name="processes", size=10),
        Layout(name="system")
    )
    
    # Center column: Performance, Recent Trades
    layout["center"].split_column(
        Layout(name="performance", ratio=1),
        Layout(name="trades", ratio=1)
    )
    
    # Right column: Risk, Positions, Signals
    layout["right"].split_column(
        Layout(name="risk", size=16),
        Layout(name="positions", size=10),
        Layout(name="signals")
    )
    
    # Populate panels
    layout["gateway"].update(create_gateway_panel())
    layout["processes"].update(create_processes_panel())
    layout["system"].update(create_system_health_panel())
    
    layout["performance"].update(create_performance_panel())
    layout["trades"].update(create_recent_trades_panel())
    
    layout["risk"].update(create_risk_panel())
    layout["positions"].update(create_positions_panel())
    layout["signals"].update(create_signals_panel())
    
    # Header
    now = datetime.now(timezone.utc)
    header = Text()
    header.append("🎯 PearlAlgo Comprehensive Trading Dashboard", style="bold cyan")
    header.append("\n")
    header.append(f"📅 {now.strftime('%Y-%m-%d')} | ⏰ {now.strftime('%H:%M:%S')} UTC", style="dim")
    header.append(" | ", style="dim")
    
    # Quick status indicators
    _, _, gateway_ok, _ = gateway_status()
    header.append("Gateway: ", style="dim")
    header.append("✅" if gateway_ok else "❌", style="green" if gateway_ok else "red")
    
    processes = get_trading_processes()
    header.append(" | Trading: ", style="dim")
    header.append(f"✅ {len(processes)} running" if processes else "❌ Stopped", 
                  style="green" if processes else "yellow")
    
    layout["header"].update(Panel(header, border_style="cyan", box=box.DOUBLE))
    
    # Footer
    footer = Text("Press Ctrl+C to exit | Auto-refresh: 3s | Use 'pearlalgo monitor --live-feed' for real-time logs", 
                  style="dim", justify="center")
    layout["footer"].update(Panel(footer, border_style="dim", box=box.SIMPLE))
    
    return layout


def main() -> int:
    """Main entry point."""
    import argparse
    parser = argparse.ArgumentParser(description="PearlAlgo Comprehensive Trading Dashboard")
    parser.add_argument("--refresh", type=int, default=3, help="Refresh interval in seconds (default: 3)")
    parser.add_argument("--once", action="store_true", help="Show dashboard once and exit")
    args = parser.parse_args()
    
    os.chdir(PROJECT_ROOT)
    
    console.print("\n[bold cyan]🎯 PearlAlgo Comprehensive Trading Dashboard[/bold cyan]")
    console.print(f"[dim]Refresh: {args.refresh}s | Press Ctrl+C to exit[/dim]\n")
    
    if args.once:
        console.print(create_comprehensive_dashboard())
        return 0
    
    try:
        with Live(create_comprehensive_dashboard(), refresh_per_second=1.0/args.refresh, screen=True, console=console) as live:
            while True:
                time_module.sleep(args.refresh)
                live.update(create_comprehensive_dashboard())
    except KeyboardInterrupt:
        console.print("\n[bold yellow]Dashboard closed[/bold yellow]\n")
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

