#!/usr/bin/env python
from __future__ import annotations

"""
🎯 PearlAlgo Futures Desk — Enhanced Status Dashboard
Beautiful Rich-based terminal dashboard with real-time updates.
"""

import sys
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

# Add project root to path (for editable install)
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
# Ensure we're in project root and it's in path
import os
original_cwd = os.getcwd()
try:
    os.chdir(PROJECT_ROOT)
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    # Remove any conflicting pearlalgo modules from cache (but keep submodules)
    modules_to_remove = [k for k in list(sys.modules.keys()) if k == 'pearlalgo']
    for mod in modules_to_remove:
        del sys.modules[mod]
except Exception:
    pass  # If chdir fails, continue anyway

import pandas as pd
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.layout import Layout
from rich.live import Live
from rich import box
from rich.text import Text
from rich.progress import Progress, SpinnerColumn, TextColumn

from pearlalgo.futures.config import load_profile
from pearlalgo.futures.performance import DEFAULT_PERF_PATH, load_performance, summarize_daily_performance
from pearlalgo.futures.risk import compute_risk_state

console = Console()


def run_cmd(cmd: list[str]) -> str:
    """Run command and return output."""
    try:
        return subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True).strip()
    except Exception as exc:
        return f"ERROR: {exc}"


def gateway_status() -> tuple[str, str, bool]:
    """Get IB Gateway status."""
    # Check if process is running
    result = subprocess.run(["pgrep", "-f", "IbcGateway"], capture_output=True)
    is_running = result.returncode == 0
    pid = result.stdout.decode().strip() if is_running else None
    
    # Check if port is listening
    result = subprocess.run(["ss", "-tlnp"], capture_output=True, text=True)
    port_listening = "4002" in result.stdout
    
    # Get version from logs
    version = ""
    try:
        log_tail = run_cmd(["journalctl", "-q", "-u", "ibgateway.service", "-n", "20", "--no-pager"])
        for line in log_tail.splitlines():
            if "Running GATEWAY" in line:
                version = line.strip()
                break
    except:
        pass
    
    status = "✅ Running" if (is_running and port_listening) else "❌ Not Running"
    return status, version, is_running and port_listening


def latest_today(prefix: str, suffix: str) -> tuple[str, bool]:
    """Get latest file path and existence."""
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    path = Path(prefix) / f"{today}{suffix}"
    return str(path), path.exists()


def create_gateway_panel() -> Panel:
    """Create IB Gateway status panel."""
    status, version, is_ready = gateway_status()
    
    status_color = "[bold green]" if is_ready else "[bold red]"
    content = f"{status_color}{status}[/]\n"
    
    if is_ready:
        result = subprocess.run(["pgrep", "-f", "IbcGateway"], capture_output=True)
        if result.returncode == 0:
            content += f"PID: {result.stdout.decode().strip()}\n"
        content += "Port 4002: ✅ Listening\n"
    else:
        content += "Port 4002: ❌ Not listening\n"
    
    if version:
        content += f"\n{version[:80]}"
    
    return Panel(content, title="🔌 IB Gateway", border_style="cyan" if is_ready else "red")


def create_files_panel() -> Panel:
    """Create workflow files panel."""
    signals_path, signals_exists = latest_today("signals", "_signals.csv")
    report_path, report_exists = latest_today("reports", "_report.md")
    perf_path = DEFAULT_PERF_PATH
    perf_exists = perf_path.exists()
    
    content = ""
    content += f"Signals:  {'✅' if signals_exists else '❌'} {Path(signals_path).name}\n"
    content += f"Report:   {'✅' if report_exists else '❌'} {Path(report_path).name}\n"
    content += f"Perf CSV: {'✅' if perf_exists else '❌'} {perf_path.name}"
    
    return Panel(content, title="📁 Workflow Files", border_style="cyan")


def create_performance_panel() -> Panel:
    """Create performance metrics panel."""
    perf_path = DEFAULT_PERF_PATH
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    
    df = load_performance(perf_path)
    
    if df.empty:
        return Panel("[bold red]No performance data yet[/bold red]\nRun live_paper_loop.py to start logging", 
                    title="📊 Performance", border_style="yellow")
    
    total_stats = {"rows": len(df), "realized": df["realized_pnl"].fillna(0).sum()}
    today_df = df[df["timestamp"].dt.strftime("%Y%m%d") == today] if "timestamp" in df.columns else pd.DataFrame()
    today_stats = {"rows": len(today_df), "realized": today_df["realized_pnl"].fillna(0).sum() if not today_df.empty else 0.0}
    
    daily_summary = summarize_daily_performance(perf_path, date=today)
    
    # Create table
    table = Table(show_header=False, box=box.SIMPLE, padding=(0, 1))
    
    # Total stats
    total_pnl = total_stats["realized"]
    total_color = "[bold green]" if total_pnl >= 0 else "[bold red]"
    table.add_row("Total P&L:", f"{total_color}${total_pnl:,.2f}[/]")
    table.add_row("Total Trades:", f"{int(total_stats['rows'])}")
    
    # Today stats
    today_pnl = today_stats["realized"]
    today_color = "[bold green]" if today_pnl >= 0 else "[bold red]"
    table.add_row("", "")  # Spacer
    table.add_row("[bold cyan]Today:[/bold cyan]", "")
    table.add_row("  P&L:", f"{today_color}${today_pnl:,.2f}[/]")
    table.add_row("  Trades:", f"{int(today_stats['rows'])}")
    
    # Enhanced metrics
    if daily_summary:
        win_rate = daily_summary.get("win_rate", 0.0) * 100
        avg_pnl = daily_summary.get("avg_realized_pnl", 0.0)
        worst_dd = daily_summary.get("worst_drawdown", 0.0)
        avg_time = daily_summary.get("avg_time_in_trade_minutes", 0.0)
        trades = int(daily_summary.get("trades", 0))
        
        table.add_row("", "")  # Spacer
        table.add_row("Win Rate:", f"{win_rate:.1f}%")
        table.add_row("Avg P&L:", f"${avg_pnl:,.2f}")
        table.add_row("Worst DD:", f"${worst_dd:,.2f}")
        table.add_row("Avg Time:", f"{avg_time:.1f} min")
    
    # Per-symbol
    if not today_df.empty:
        table.add_row("", "")  # Spacer
        table.add_row("[bold cyan]Per Symbol:[/bold cyan]", "")
        for sym in ("ES", "NQ", "GC"):
            sym_df = today_df[today_df["symbol"] == sym]
            if not sym_df.empty:
                sym_pnl = sym_df["realized_pnl"].fillna(0).sum()
                sym_color = "[green]" if sym_pnl >= 0 else "[red]"
                table.add_row(f"  {sym}:", f"{sym_color}${sym_pnl:,.2f}[/] ({len(sym_df)} trades)")
    
    return Panel(table, title="📊 Performance", border_style="cyan")


def create_risk_panel() -> Panel:
    """Create risk state panel."""
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
    
    # Status color
    if risk_state.status == "OK":
        status_style = "[bold green]"
        border_style = "green"
    elif risk_state.status == "NEAR_LIMIT":
        status_style = "[bold yellow]"
        border_style = "yellow"
    else:
        status_style = "[bold red]"
        border_style = "red"
    
    table = Table(show_header=False, box=box.SIMPLE, padding=(0, 1))
    table.add_row("Status:", f"{status_style}{risk_state.status}[/]")
    table.add_row("Remaining Buffer:", f"${risk_state.remaining_loss_buffer:,.2f}")
    table.add_row("Daily Loss Limit:", f"${risk_state.daily_loss_limit:,.2f}")
    
    if risk_state.max_trades:
        remaining = max(0, risk_state.max_trades - trades_today)
        table.add_row("", "")  # Spacer
        table.add_row("Trades Today:", f"{trades_today}/{risk_state.max_trades}")
        table.add_row("Remaining:", f"{remaining}")
    
    if risk_state.cooldown_until:
        table.add_row("", "")  # Spacer
        table.add_row("[bold yellow]Cooldown Until:[/bold yellow]", risk_state.cooldown_until.strftime("%H:%M:%S UTC"))
    
    return Panel(table, title="⚠️  Risk State", border_style=border_style)


def create_signals_panel() -> Panel:
    """Create latest signals panel."""
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    signals_file = Path("signals") / f"{today}_signals.csv"
    
    if not signals_file.exists():
        return Panel("[dim]No signals generated today[/dim]", title="📋 Latest Signals", border_style="yellow")
    
    try:
        df = pd.read_csv(signals_file)
        if df.empty:
            return Panel("[dim]No signals in file[/dim]", title="📋 Latest Signals", border_style="yellow")
        
        table = Table(show_header=True, box=box.SIMPLE, header_style="bold cyan")
        table.add_column("Symbol", style="yellow")
        table.add_column("Direction", justify="center")
        table.add_column("Size", justify="right")
        table.add_column("Time", style="dim")
        
        for _, row in df.tail(5).iterrows():  # Show last 5
            direction = row.get("direction", "FLAT")
            if direction == "BUY":
                dir_display = "[bold green]BUY[/]"
            elif direction == "SELL":
                dir_display = "[bold red]SELL[/]"
            else:
                dir_display = "[dim]FLAT[/]"
            
            timestamp = row.get("timestamp", "")[:19] if pd.notna(row.get("timestamp")) else "N/A"
            table.add_row(
                row.get("symbol", "N/A"),
                dir_display,
                str(row.get("size_hint", 0)),
                timestamp
            )
        
        return Panel(table, title="📋 Latest Signals", border_style="cyan")
    except Exception as e:
        return Panel(f"[red]Error loading signals: {e}[/red]", title="📋 Latest Signals", border_style="red")


def create_dashboard() -> Layout:
    """Create the main dashboard layout."""
    layout = Layout()
    
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="main"),
        Layout(name="footer", size=3)
    )
    
    layout["main"].split_row(
        Layout(name="left"),
        Layout(name="right")
    )
    
    layout["left"].split_column(
        Layout(create_gateway_panel(), name="gateway"),
        Layout(create_files_panel(), name="files"),
        Layout(create_risk_panel(), name="risk")
    )
    
    layout["right"].split_column(
        Layout(create_performance_panel(), name="performance"),
        Layout(create_signals_panel(), name="signals")
    )
    
    # Header
    now = datetime.now(timezone.utc)
    header_text = Text(f"🎯 PearlAlgo Futures Desk — Status Dashboard", style="bold cyan")
    header_text.append(f"\n{now.strftime('%Y-%m-%d %H:%M:%S UTC')}", style="dim")
    layout["header"].update(Panel(header_text, border_style="cyan", box=box.DOUBLE))
    
    # Footer
    footer_text = Text("Press Ctrl+C to exit", style="dim", justify="center")
    layout["footer"].update(Panel(footer_text, border_style="dim"))
    
    return layout


def main() -> int:
    """Main entry point."""
    import argparse
    parser = argparse.ArgumentParser(description="PearlAlgo Futures Desk — Enhanced Status Dashboard")
    parser.add_argument("--live", action="store_true", help="Live updating dashboard (refreshes every 5s)")
    parser.add_argument("--once", action="store_true", help="Show dashboard once and exit")
    args = parser.parse_args()
    
    if args.live:
        # Live updating dashboard
        with Live(create_dashboard(), refresh_per_second=0.2, screen=True) as live:
            try:
                while True:
                    import time
                    time.sleep(5)
                    live.update(create_dashboard())
            except KeyboardInterrupt:
                console.print("\n[bold yellow]Dashboard closed[/bold yellow]\n")
    else:
        # Show once
        console.print(create_dashboard())
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
