"""Gateway management commands."""

from __future__ import annotations

import click
import subprocess
import time
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeRemainingColumn
from rich import box

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
                await asyncio.wait_for(ib.connectAsync('127.0.0.1', 4002, clientId=999), timeout=3)
                ib.disconnect()
                return True
            except:
                return False
        
        return asyncio.run(test())
    except:
        return False


@click.group(name="gateway")
@click.pass_context
def gateway_group(ctx: click.Context) -> None:
    """IB Gateway management commands."""
    pass


@gateway_group.command(name="start")
@click.option("--wait", is_flag=True, help="Wait for Gateway to be ready")
@click.pass_context
def start_cmd(ctx: click.Context, wait: bool) -> None:
    """Start IB Gateway."""
    ibc_path = Path.home() / "ibc"
    if not (ibc_path / "gatewaystart.sh").exists():
        console.print("[bold red]❌ IBC not found at ~/ibc/gatewaystart.sh[/bold red]")
        raise SystemExit(1)
    
    is_running, _ = check_gateway_process()
    if is_running:
        console.print("[yellow]⚠️  Gateway is already running[/yellow]")
        raise SystemExit(0)
    
    console.print("[bold cyan]🚀 Starting IB Gateway...[/bold cyan]")
    subprocess.Popen(
        ["/usr/bin/xvfb-run", "-a", str(ibc_path / "gatewaystart.sh"), "-inline"],
        cwd=ibc_path,
        stdout=open("/tmp/ibgateway.log", "w"),
        stderr=subprocess.STDOUT
    )
    console.print("[bold green]✅ Gateway starting in background[/bold green]")
    
    if wait:
        console.print("[yellow]   Waiting for Gateway to be ready...[/yellow]\n")
        _wait_for_gateway()
    else:
        console.print("[yellow]   Wait 60-90 seconds for it to be ready[/yellow]\n")


@gateway_group.command(name="stop")
@click.pass_context
def stop_cmd(ctx: click.Context) -> None:
    """Stop IB Gateway."""
    is_running, pid = check_gateway_process()
    if not is_running:
        console.print("[yellow]⚠️  Gateway is not running[/yellow]")
        raise SystemExit(0)
    
    console.print("[bold yellow]🛑 Stopping IB Gateway...[/bold yellow]")
    subprocess.run(["pkill", "-f", "IbcGateway"])
    time.sleep(2)
    console.print("[bold green]✅ Gateway stopped[/bold green]\n")


@gateway_group.command(name="restart")
@click.option("--wait", is_flag=True, help="Wait for Gateway to be ready")
@click.pass_context
def restart_cmd(ctx: click.Context, wait: bool) -> None:
    """Restart IB Gateway."""
    console.print("[bold cyan]🔄 Restarting IB Gateway...[/bold cyan]\n")
    
    # Stop
    is_running, _ = check_gateway_process()
    if is_running:
        subprocess.run(["pkill", "-f", "IbcGateway"])
        time.sleep(2)
    
    # Start
    ibc_path = Path.home() / "ibc"
    subprocess.Popen(
        ["/usr/bin/xvfb-run", "-a", str(ibc_path / "gatewaystart.sh"), "-inline"],
        cwd=ibc_path,
        stdout=open("/tmp/ibgateway.log", "w"),
        stderr=subprocess.STDOUT
    )
    console.print("[bold green]✅ Gateway restarting...[/bold green]")
    
    if wait:
        _wait_for_gateway()
    else:
        console.print("[yellow]   Wait 60-90 seconds for it to be ready[/yellow]\n")


@gateway_group.command(name="status")
@click.pass_context
def status_cmd(ctx: click.Context) -> None:
    """Show Gateway status."""
    is_running, pid = check_gateway_process()
    port_listening = check_gateway_port()
    api_ready = check_gateway_api()
    
    table = Panel(
        f"Process: {'✅ Running' if is_running else '❌ Not Running'} {'(PID: ' + pid + ')' if pid else ''}\n"
        f"Port 4002: {'✅ Listening' if port_listening else '❌ Not Listening'}\n"
        f"API Ready: {'✅ Yes' if api_ready else '❌ No'}",
        title="🔌 IB Gateway Status",
        border_style="green" if (is_running and port_listening and api_ready) else "red",
        box=box.ROUNDED
    )
    console.print(table)
    console.print()


@gateway_group.command(name="logs")
@click.option("--lines", type=int, default=30, help="Number of lines to show")
@click.pass_context
def logs_cmd(ctx: click.Context, lines: int) -> None:
    """Show Gateway logs."""
    ibc_path = Path.home() / "ibc"
    log_dir = ibc_path / "logs"
    
    if not log_dir.exists():
        console.print("[red]❌ Log directory not found[/red]")
        raise SystemExit(1)
    
    log_files = sorted(log_dir.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not log_files:
        console.print("[yellow]⚠️  No log files found[/yellow]")
        raise SystemExit(0)
    
    latest_log = log_files[0]
    console.print(f"\n[bold cyan]Last {lines} lines of {latest_log.name}:[/bold cyan]\n")
    
    with open(latest_log) as f:
        log_lines = f.readlines()
        for line in log_lines[-lines:]:
            console.print(line.rstrip())
    console.print()


def _wait_for_gateway(timeout: int = 120) -> bool:
    """Wait for Gateway to be ready."""
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TimeRemainingColumn(),
        console=console
    ) as progress:
        task = progress.add_task("Initializing...", total=timeout)
        
        for i in range(timeout):
            if check_gateway_api():
                progress.update(task, completed=timeout)
                console.print("\n[bold green]✅ Gateway is READY![/bold green]\n")
                return True
            
            time.sleep(1)
            progress.update(task, advance=1)
            progress.update(task, description=f"Waiting... ({i+1}/{timeout}s)")
        
        console.print("\n[bold red]❌ Gateway did not become ready in time[/bold red]")
        console.print("[yellow]   Check logs: tail -f ~/ibc/logs/ibc-*.txt[/yellow]\n")
        return False

