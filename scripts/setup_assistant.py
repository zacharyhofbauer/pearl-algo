#!/usr/bin/env python
"""
🎯 PearlAlgo Futures Desk — Setup & Management Assistant
Interactive assistant for setup, troubleshooting, and daily operations.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
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
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TimeRemainingColumn,
)

console = Console()


def check_gateway_process() -> tuple[bool, str | None]:
    """Check if IB Gateway process is running."""
    result = subprocess.run(["pgrep", "-f", "IbcGateway"], capture_output=True)
    if result.returncode == 0:
        pid = result.stdout.decode().strip().split()[0] if result.stdout else None
        return True, pid
    return False, None


def check_gateway_port() -> bool:
    """Check if port 4002 is listening."""
    result = subprocess.run(["ss", "-tlnp"], capture_output=True, text=True)
    return "4002" in result.stdout


def check_gateway_api() -> bool:
    """Test if Gateway API is accepting connections."""
    try:
        from ib_insync import IB
        import asyncio

        async def test():
            ib = IB()
            try:
                await asyncio.wait_for(
                    ib.connectAsync("127.0.0.1", 4002, clientId=999), timeout=3
                )
                ib.disconnect()
                return True
            except:
                return False

        return asyncio.run(test())
    except:
        return False


def start_gateway() -> bool:
    """Start IB Gateway."""
    ibc_path = Path.home() / "ibc"
    if not (ibc_path / "gatewaystart.sh").exists():
        console.print("[bold red]❌ IBC not found at ~/ibc/gatewaystart.sh[/bold red]")
        return False

    console.print("[bold cyan]🚀 Starting IB Gateway...[/bold cyan]")
    subprocess.Popen(
        ["/usr/bin/xvfb-run", "-a", str(ibc_path / "gatewaystart.sh"), "-inline"],
        cwd=ibc_path,
        stdout=open("/tmp/ibgateway.log", "w"),
        stderr=subprocess.STDOUT,
    )
    console.print("[bold green]✅ Gateway starting in background[/bold green]")
    console.print("[yellow]   Waiting 60-90 seconds for initialization...[/yellow]\n")
    return True


def stop_gateway() -> bool:
    """Stop IB Gateway."""
    is_running, pid = check_gateway_process()
    if not is_running:
        console.print("[yellow]⚠️  Gateway is not running[/yellow]\n")
        return False

    console.print("[bold yellow]🛑 Stopping IB Gateway...[/bold yellow]")
    subprocess.run(["pkill", "-f", "IbcGateway"])
    time.sleep(2)
    console.print("[bold green]✅ Gateway stopped[/bold green]\n")
    return True


def restart_gateway() -> bool:
    """Restart IB Gateway."""
    console.print("[bold cyan]🔄 Restarting IB Gateway...[/bold cyan]\n")
    stop_gateway()
    time.sleep(2)
    return start_gateway()


def wait_for_gateway(timeout: int = 120) -> bool:
    """Wait for Gateway to be ready."""
    console.print("[bold cyan]⏳ Waiting for Gateway to be ready...[/bold cyan]\n")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Initializing...", total=timeout)

        for i in range(timeout):
            if check_gateway_api():
                progress.update(task, completed=timeout)
                console.print("\n[bold green]✅ Gateway is READY![/bold green]\n")
                return True

            time.sleep(1)
            progress.update(task, advance=1)
            progress.update(task, description=f"Waiting... ({i + 1}/{timeout}s)")

        console.print("\n[bold red]❌ Gateway did not become ready in time[/bold red]")
        console.print("[yellow]   Check logs: tail -f ~/ibc/logs/ibc-*.txt[/yellow]\n")
        return False


def show_status():
    """Show comprehensive status of all components."""
    console.print(
        "\n[bold cyan]╔═══════════════════════════════════════════════════════════╗[/bold cyan]"
    )
    console.print(
        "[bold cyan]║[/bold cyan]  [bold yellow]🎯 PearlAlgo Futures Desk — System Status[/bold yellow]            [bold cyan]║[/bold cyan]"
    )
    console.print(
        "[bold cyan]╚═══════════════════════════════════════════════════════════╝[/bold cyan]\n"
    )

    # Gateway Status
    is_running, pid = check_gateway_process()
    port_listening = check_gateway_port()
    api_ready = check_gateway_api()

    table = Table(title="🔌 IB Gateway Status", box=box.ROUNDED, show_header=True)
    table.add_column("Component", style="cyan")
    table.add_column("Status", justify="center")
    table.add_column("Details")

    status_icon = "✅" if is_running else "❌"
    table.add_row("Process", status_icon, f"PID: {pid}" if pid else "Not running")

    port_icon = "✅" if port_listening else "❌"
    table.add_row(
        "Port 4002", port_icon, "Listening" if port_listening else "Not listening"
    )

    api_icon = "✅" if api_ready else "⏳"
    table.add_row(
        "API Ready", api_icon, "Accepting connections" if api_ready else "Not ready yet"
    )

    console.print(table)
    console.print()

    # Configuration Check
    config_table = Table(title="⚙️  Configuration", box=box.ROUNDED, show_header=True)
    config_table.add_column("Item", style="cyan")
    config_table.add_column("Status", justify="center")
    config_table.add_column("Path")

    ibc_config = Path.home() / "ibc" / "config-auto.ini"
    config_table.add_row(
        "IBC Config", "✅" if ibc_config.exists() else "❌", str(ibc_config)
    )

    venv_path = PROJECT_ROOT / ".venv"
    config_table.add_row(
        "Virtual Env", "✅" if venv_path.exists() else "❌", str(venv_path)
    )

    perf_path = PROJECT_ROOT / "data" / "performance" / "futures_decisions.csv"
    config_table.add_row(
        "Perf Log", "✅" if perf_path.exists() else "⚠️ ", str(perf_path)
    )

    console.print(config_table)
    console.print()

    # Recommendations
    if not is_running:
        console.print(
            Panel(
                "[bold yellow]⚠️  Gateway is not running[/bold yellow]\n"
                "Run: [cyan]python scripts/setup_assistant.py --start-gateway[/cyan]",
                title="Action Required",
                border_style="yellow",
            )
        )
    elif not api_ready:
        console.print(
            Panel(
                "[bold yellow]⏳ Gateway is starting but API not ready yet[/bold yellow]\n"
                "Wait 30-60 more seconds, or run: [cyan]python scripts/setup_assistant.py --wait-gateway[/cyan]",
                title="In Progress",
                border_style="yellow",
            )
        )
    else:
        console.print(
            Panel(
                "[bold green]✅ All systems operational![/bold green]\n"
                "You can now run: [cyan]python scripts/workflow.py[/cyan]",
                title="Ready",
                border_style="green",
            )
        )
    console.print()


def setup_wizard():
    """Interactive setup wizard."""
    console.print(
        "\n[bold cyan]╔═══════════════════════════════════════════════════════════╗[/bold cyan]"
    )
    console.print(
        "[bold cyan]║[/bold cyan]  [bold yellow]🎯 PearlAlgo Futures Desk — Setup Wizard[/bold yellow]         [bold cyan]║[/bold cyan]"
    )
    console.print(
        "[bold cyan]╚═══════════════════════════════════════════════════════════╝[/bold cyan]\n"
    )

    console.print("[bold]Let's check your setup step by step...[/bold]\n")

    # Step 1: Virtual Environment
    console.print("[bold cyan]Step 1:[/bold cyan] Checking virtual environment...")
    venv_path = PROJECT_ROOT / ".venv"
    if venv_path.exists():
        console.print("[green]✅ Virtual environment found[/green]")
    else:
        console.print("[red]❌ Virtual environment not found[/red]")
        if Confirm.ask("Create virtual environment?"):
            subprocess.run([sys.executable, "-m", "venv", ".venv"], cwd=PROJECT_ROOT)
            console.print("[green]✅ Virtual environment created[/green]")
            console.print(
                "[yellow]   Run: source .venv/bin/activate && pip install -e .[/yellow]\n"
            )
            return
    console.print()

    # Step 2: IBC Configuration
    console.print("[bold cyan]Step 2:[/bold cyan] Checking IBC configuration...")
    ibc_config = Path.home() / "ibc" / "config-auto.ini"
    if ibc_config.exists():
        console.print("[green]✅ IBC config found[/green]")
        # Check if it has required fields
        config_content = ibc_config.read_text()
        if "IbLoginId" in config_content and "IbPassword" in config_content:
            console.print("[green]✅ IBC config has credentials[/green]")
        else:
            console.print("[yellow]⚠️  IBC config missing credentials[/yellow]")
    else:
        console.print("[red]❌ IBC config not found at ~/ibc/config-auto.ini[/red]")
        console.print("[yellow]   Create it with your IBKR credentials[/yellow]")
    console.print()

    # Step 3: Gateway Status
    console.print("[bold cyan]Step 3:[/bold cyan] Checking IB Gateway...")
    is_running, pid = check_gateway_process()
    if is_running:
        console.print(f"[green]✅ Gateway is running (PID: {pid})[/green]")
        if check_gateway_port():
            console.print("[green]✅ Port 4002 is listening[/green]")
            if check_gateway_api():
                console.print("[green]✅ API is ready![/green]")
            else:
                console.print(
                    "[yellow]⏳ API not ready yet (may need more time)[/yellow]"
                )
                if Confirm.ask("Wait for API to be ready?"):
                    wait_for_gateway()
        else:
            console.print(
                "[yellow]⚠️  Port 4002 not listening (Gateway may still be starting)[/yellow]"
            )
    else:
        console.print("[red]❌ Gateway is not running[/red]")
        if Confirm.ask("Start IB Gateway now?"):
            start_gateway()
            if Confirm.ask("Wait for Gateway to be ready?"):
                wait_for_gateway()
    console.print()

    # Step 4: Test Connection
    console.print("[bold cyan]Step 4:[/bold cyan] Testing IBKR connection...")
    if check_gateway_api():
        console.print("[green]✅ Connection test successful![/green]")
        console.print(
            "[bold]You're all set! Run: [cyan]python scripts/workflow.py[/cyan][/bold]\n"
        )
    else:
        console.print("[yellow]⚠️  Connection test failed[/yellow]")
        console.print(
            "[yellow]   Make sure Gateway is running and API is enabled[/yellow]\n"
        )


def quick_start():
    """Quick start - ensure everything is running."""
    console.print(
        "\n[bold cyan]🚀 Quick Start — Ensuring everything is ready...[/bold cyan]\n"
    )

    # Check and start Gateway if needed
    is_running, _ = check_gateway_process()
    if not is_running:
        console.print("[yellow]Gateway not running, starting...[/yellow]")
        start_gateway()
        wait_for_gateway()
    elif not check_gateway_api():
        console.print("[yellow]Gateway running but API not ready, waiting...[/yellow]")
        wait_for_gateway()
    else:
        console.print("[green]✅ Gateway is ready![/green]\n")

    # Show status
    show_status()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="PearlAlgo Futures Desk — Setup & Management Assistant"
    )
    parser.add_argument("--status", action="store_true", help="Show system status")
    parser.add_argument("--setup", action="store_true", help="Run setup wizard")
    parser.add_argument(
        "--quick-start",
        action="store_true",
        help="Quick start (ensure Gateway is running)",
    )
    parser.add_argument("--start-gateway", action="store_true", help="Start IB Gateway")
    parser.add_argument("--stop-gateway", action="store_true", help="Stop IB Gateway")
    parser.add_argument(
        "--restart-gateway", action="store_true", help="Restart IB Gateway"
    )
    parser.add_argument(
        "--wait-gateway", action="store_true", help="Wait for Gateway to be ready"
    )
    parser.add_argument(
        "--test-connection", action="store_true", help="Test IBKR API connection"
    )

    args = parser.parse_args()

    if args.status:
        show_status()
    elif args.setup:
        setup_wizard()
    elif args.quick_start:
        quick_start()
    elif args.start_gateway:
        start_gateway()
        if Confirm.ask("\nWait for Gateway to be ready?"):
            wait_for_gateway()
    elif args.stop_gateway:
        stop_gateway()
    elif args.restart_gateway:
        restart_gateway()
        if Confirm.ask("\nWait for Gateway to be ready?"):
            wait_for_gateway()
    elif args.wait_gateway:
        wait_for_gateway()
    elif args.test_connection:
        if check_gateway_api():
            console.print("\n[bold green]✅ Connection test successful![/bold green]\n")
        else:
            console.print("\n[bold red]❌ Connection test failed[/bold red]")
            console.print(
                "[yellow]   Make sure Gateway is running: python scripts/setup_assistant.py --start-gateway[/yellow]\n"
            )
    else:
        # Interactive menu
        while True:
            console.print(
                "\n[bold cyan]╔═══════════════════════════════════════════════════════════╗[/bold cyan]"
            )
            console.print(
                "[bold cyan]║[/bold cyan]  [bold yellow]🎯 PearlAlgo Setup & Management Assistant[/bold yellow]    [bold cyan]║[/bold cyan]"
            )
            console.print(
                "[bold cyan]╚═══════════════════════════════════════════════════════════╝[/bold cyan]\n"
            )

            table = Table(show_header=False, box=box.SIMPLE, padding=(0, 2))
            table.add_row(
                "[bold green]1.[/bold green]",
                "📊 Show System Status",
                "Check Gateway, config, and connections",
            )
            table.add_row(
                "[bold green]2.[/bold green]",
                "🔧 Run Setup Wizard",
                "Interactive setup guide",
            )
            table.add_row(
                "[bold green]3.[/bold green]",
                "🚀 Quick Start",
                "Ensure Gateway is running and ready",
            )
            table.add_row(
                "[bold green]4.[/bold green]",
                "▶️  Start IB Gateway",
                "Start Gateway in background",
            )
            table.add_row(
                "[bold green]5.[/bold green]",
                "⏹️  Stop IB Gateway",
                "Stop running Gateway",
            )
            table.add_row(
                "[bold green]6.[/bold green]",
                "🔄 Restart IB Gateway",
                "Stop and start Gateway",
            )
            table.add_row(
                "[bold green]7.[/bold green]",
                "⏳ Wait for Gateway",
                "Wait until API is ready",
            )
            table.add_row(
                "[bold green]8.[/bold green]",
                "🔍 Test Connection",
                "Test IBKR API connection",
            )
            table.add_row("[bold green]9.[/bold green]", "🚪 Exit", "Quit assistant")

            console.print(table)
            console.print()

            choice = Prompt.ask(
                "Select option",
                choices=["1", "2", "3", "4", "5", "6", "7", "8", "9"],
                default="9",
            )

            if choice == "1":
                show_status()
            elif choice == "2":
                setup_wizard()
            elif choice == "3":
                quick_start()
            elif choice == "4":
                start_gateway()
                if Confirm.ask("\nWait for Gateway to be ready?"):
                    wait_for_gateway()
            elif choice == "5":
                stop_gateway()
            elif choice == "6":
                restart_gateway()
                if Confirm.ask("\nWait for Gateway to be ready?"):
                    wait_for_gateway()
            elif choice == "7":
                wait_for_gateway()
            elif choice == "8":
                if check_gateway_api():
                    console.print(
                        "\n[bold green]✅ Connection test successful![/bold green]\n"
                    )
                else:
                    console.print("\n[bold red]❌ Connection test failed[/bold red]\n")
            elif choice == "9":
                console.print("\n[bold cyan]👋 Goodbye![/bold cyan]\n")
                break

            if choice != "9":
                Prompt.ask("\n[dim]Press Enter to continue...[/dim]", default="")


if __name__ == "__main__":
    main()
