#!/usr/bin/env python
"""
🎯 PearlAlgo Futures Desk — Main Workflow CLI
Simple, straightforward interface for all trading operations.
"""

from __future__ import annotations

import argparse
import subprocess
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

console = Console()


def show_menu():
    """Display main menu."""
    console.print("\n[bold cyan]╔═══════════════════════════════════════════════════════════╗[/bold cyan]")
    console.print("[bold cyan]║[/bold cyan]  [bold yellow]🎯 PearlAlgo Futures Desk — Main Menu[/bold yellow]              [bold cyan]║[/bold cyan]")
    console.print("[bold cyan]╚═══════════════════════════════════════════════════════════╝[/bold cyan]\n")
    
    table = Table(show_header=False, box=box.SIMPLE, padding=(0, 2))
    table.add_row("[bold green]1.[/bold green]", "📊 Generate Daily Signals & Report", "Run S/R strategy, generate signals CSV and markdown report")
    table.add_row("[bold green]2.[/bold green]", "📈 View Status Dashboard", "See gateway status, performance, risk state")
    table.add_row("[bold green]3.[/bold green]", "🔄 Run Paper Trading Loop", "Start live paper trading with IBKR")
    table.add_row("[bold green]4.[/bold green]", "📥 Download Historical Data", "Fetch ES/NQ/GC data from IBKR")
    table.add_row("[bold green]5.[/bold green]", "🔍 Test IB Gateway Connection", "Verify Gateway is running and accepting connections")
    table.add_row("[bold green]6.[/bold green]", "⚙️  Gateway Management", "Start/stop/restart IB Gateway")
    table.add_row("[bold green]7.[/bold green]", "📋 View Latest Signals", "Show today's generated signals")
    table.add_row("[bold green]8.[/bold green]", "📄 View Latest Report", "Show today's markdown report")
    table.add_row("[bold green]9.[/bold green]", "🚪 Exit", "Quit the application")
    
    console.print(table)
    console.print()


def run_daily_signals(strategy: str = "sr"):
    """Run daily signals generation."""
    console.print(f"\n[bold cyan]📊 Generating Daily Signals ({strategy.upper()} strategy)...[/bold cyan]\n")
    
    cmd = [sys.executable, "scripts/daily_workflow.py", "--strategy", strategy]
    result = subprocess.run(cmd, cwd=PROJECT_ROOT)
    
    if result.returncode == 0:
        console.print("[bold green]✅ Signals generated successfully![/bold green]\n")
    else:
        console.print("[bold red]❌ Failed to generate signals[/bold red]\n")
    
    return result.returncode


def view_dashboard():
    """View status dashboard."""
    console.print("\n[bold cyan]📈 Loading Status Dashboard...[/bold cyan]\n")
    cmd = [sys.executable, "scripts/status_dashboard.py"]
    subprocess.run(cmd, cwd=PROJECT_ROOT)


def run_paper_loop():
    """Run paper trading loop."""
    console.print("\n[bold yellow]🔄 Paper Trading Loop[/bold yellow]\n")
    
    symbols = Prompt.ask("Symbols", default="ES NQ GC").split()
    strategy = Prompt.ask("Strategy", choices=["sr", "ma_cross"], default="sr")
    interval = int(Prompt.ask("Interval (seconds)", default="300"))
    tiny_size = int(Prompt.ask("Tiny size", default="1"))
    
    console.print(f"\n[bold cyan]Starting paper loop with:[/bold cyan]")
    console.print(f"  Symbols: {', '.join(symbols)}")
    console.print(f"  Strategy: {strategy}")
    console.print(f"  Interval: {interval}s")
    console.print(f"  Size: {tiny_size}\n")
    
    if not Confirm.ask("Start paper trading loop?"):
        return
    
    cmd = [
        sys.executable, "scripts/live_paper_loop.py",
        "--symbols", *symbols,
        "--sec-types", *(["FUT"] * len(symbols)),
        "--strategy", strategy,
        "--interval", str(interval),
        "--tiny-size", str(tiny_size),
        "--mode", "ibkr-paper"
    ]
    
    try:
        subprocess.run(cmd, cwd=PROJECT_ROOT)
    except KeyboardInterrupt:
        console.print("\n[bold yellow]⚠️  Paper loop stopped by user[/bold yellow]\n")


def download_data():
    """Download historical data."""
    console.print("\n[bold cyan]📥 Downloading Historical Data...[/bold cyan]\n")
    cmd = [sys.executable, "scripts/ibkr_download_data.py"]
    subprocess.run(cmd, cwd=PROJECT_ROOT)


def test_gateway():
    """Test IB Gateway connection."""
    console.print("\n[bold cyan]🔍 Testing IB Gateway Connection...[/bold cyan]\n")
    cmd = [sys.executable, "scripts/test_contracts.py"]
    result = subprocess.run(cmd, cwd=PROJECT_ROOT)
    return result.returncode


def gateway_management():
    """Manage IB Gateway."""
    console.print("\n[bold cyan]⚙️  IB Gateway Management[/bold cyan]\n")
    
    table = Table(show_header=False, box=box.SIMPLE)
    table.add_row("[bold green]1.[/bold green]", "Start Gateway")
    table.add_row("[bold green]2.[/bold green]", "Stop Gateway")
    table.add_row("[bold green]3.[/bold green]", "Restart Gateway")
    table.add_row("[bold green]4.[/bold green]", "Check Status")
    table.add_row("[bold green]5.[/bold green]", "View Logs")
    table.add_row("[bold green]6.[/bold green]", "Back to Main Menu")
    
    console.print(table)
    choice = Prompt.ask("\nChoice", choices=["1", "2", "3", "4", "5", "6"], default="6")
    
    ibc_path = Path.home() / "ibc"
    
    if choice == "1":
        console.print("\n[bold green]Starting IB Gateway...[/bold green]")
        subprocess.Popen(
            ["/usr/bin/xvfb-run", "-a", str(ibc_path / "gatewaystart.sh"), "-inline"],
            cwd=ibc_path,
            stdout=open("/tmp/ibgateway.log", "w"),
            stderr=subprocess.STDOUT
        )
        console.print("[bold green]✅ Gateway starting in background...[/bold green]")
        console.print("[yellow]   Wait 60-90 seconds for it to be ready[/yellow]\n")
    
    elif choice == "2":
        console.print("\n[bold red]Stopping IB Gateway...[/bold red]")
        subprocess.run(["pkill", "-f", "IbcGateway"])
        console.print("[bold green]✅ Gateway stopped[/bold green]\n")
    
    elif choice == "3":
        console.print("\n[bold yellow]Restarting IB Gateway...[/bold yellow]")
        subprocess.run(["pkill", "-f", "IbcGateway"])
        import time
        time.sleep(2)
        subprocess.Popen(
            ["/usr/bin/xvfb-run", "-a", str(ibc_path / "gatewaystart.sh"), "-inline"],
            cwd=ibc_path,
            stdout=open("/tmp/ibgateway.log", "w"),
            stderr=subprocess.STDOUT
        )
        console.print("[bold green]✅ Gateway restarting...[/bold green]")
        console.print("[yellow]   Wait 60-90 seconds for it to be ready[/yellow]\n")
    
    elif choice == "4":
        console.print("\n[bold cyan]Gateway Status:[/bold cyan]")
        result = subprocess.run(["pgrep", "-f", "IbcGateway"], capture_output=True)
        if result.returncode == 0:
            console.print("[bold green]✅ Gateway is running[/bold green]")
            console.print(f"   PID: {result.stdout.decode().strip()}")
        else:
            console.print("[bold red]❌ Gateway is not running[/bold red]")
        
        # Check port
        result = subprocess.run(["ss", "-tlnp"], capture_output=True, text=True)
        if "4002" in result.stdout:
            console.print("[bold green]✅ Port 4002 is listening[/bold green]")
        else:
            console.print("[bold red]❌ Port 4002 is not listening[/bold red]")
        console.print()
    
    elif choice == "5":
        log_file = sorted(Path(ibc_path / "logs").glob("*.txt"), key=lambda p: p.stat().st_mtime)[-1] if (ibc_path / "logs").exists() else None
        if log_file:
            console.print(f"\n[bold cyan]Last 30 lines of {log_file.name}:[/bold cyan]\n")
            with open(log_file) as f:
                lines = f.readlines()
                for line in lines[-30:]:
                    console.print(line.rstrip())
        else:
            console.print("[bold red]No log files found[/bold red]")
        console.print()


def view_signals():
    """View latest signals."""
    from datetime import datetime
    today = datetime.now().strftime("%Y%m%d")
    signals_file = PROJECT_ROOT / "signals" / f"{today}_signals.csv"
    
    if not signals_file.exists():
        console.print(f"[bold red]❌ No signals file found for today ({today})[/bold red]\n")
        return
    
    import pandas as pd
    df = pd.read_csv(signals_file)
    
    table = Table(title=f"📋 Today's Signals ({today})", box=box.ROUNDED)
    table.add_column("Timestamp", style="cyan")
    table.add_column("Symbol", style="yellow")
    table.add_column("Direction", style="green")
    table.add_column("Size", justify="right")
    
    for _, row in df.iterrows():
        direction_color = "[bold green]" if row["direction"] == "BUY" else "[bold red]" if row["direction"] == "SELL" else "[dim]"
        table.add_row(
            row.get("timestamp", "N/A")[:19],
            row["symbol"],
            f"{direction_color}{row['direction']}[/]",
            str(row.get("size_hint", 0))
        )
    
    console.print()
    console.print(table)
    console.print()


def view_report():
    """View latest report."""
    from datetime import datetime
    today = datetime.now().strftime("%Y%m%d")
    report_file = PROJECT_ROOT / "reports" / f"{today}_report.md"
    
    if not report_file.exists():
        console.print(f"[bold red]❌ No report found for today ({today})[/bold red]\n")
        return
    
    console.print(f"\n[bold cyan]📄 Today's Report ({today}):[/bold cyan]\n")
    with open(report_file) as f:
        content = f.read()
        console.print(Panel(content, title="Daily Report", border_style="cyan"))
    console.print()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="PearlAlgo Futures Desk — Main Workflow CLI")
    parser.add_argument("--menu", action="store_true", help="Show interactive menu")
    parser.add_argument("--signals", action="store_true", help="Generate daily signals")
    parser.add_argument("--dashboard", action="store_true", help="View status dashboard")
    parser.add_argument("--strategy", default="sr", choices=["sr", "ma_cross"], help="Strategy to use")
    
    args = parser.parse_args()
    
    # If no args, show menu
    if not any([args.menu, args.signals, args.dashboard]):
        args.menu = True
    
    if args.menu:
        while True:
            show_menu()
            choice = Prompt.ask("Select option", choices=["1", "2", "3", "4", "5", "6", "7", "8", "9"], default="9")
            
            if choice == "1":
                strategy = Prompt.ask("Strategy", choices=["sr", "ma_cross"], default="sr")
                run_daily_signals(strategy)
            elif choice == "2":
                view_dashboard()
            elif choice == "3":
                run_paper_loop()
            elif choice == "4":
                download_data()
            elif choice == "5":
                test_gateway()
            elif choice == "6":
                gateway_management()
            elif choice == "7":
                view_signals()
            elif choice == "8":
                view_report()
            elif choice == "9":
                console.print("\n[bold cyan]👋 Goodbye![/bold cyan]\n")
                break
            
            if choice != "9":
                Prompt.ask("\n[dim]Press Enter to continue...[/dim]", default="")
    
    elif args.signals:
        run_daily_signals(args.strategy)
    
    elif args.dashboard:
        view_dashboard()


if __name__ == "__main__":
    main()

