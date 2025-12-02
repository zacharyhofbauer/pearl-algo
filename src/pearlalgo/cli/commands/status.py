"""Status command - Quick system status check."""

from __future__ import annotations

import click
import subprocess
from datetime import datetime, timezone

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

from pearlalgo.futures.config import load_profile
from pearlalgo.futures.performance import DEFAULT_PERF_PATH, load_performance
from pearlalgo.futures.risk import compute_risk_state

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


@click.command(name="status")
@click.pass_context
def status_cmd(ctx: click.Context) -> None:
    """Show quick system status (gateway, risk, performance)."""
    verbosity = ctx.obj.get("verbosity", "NORMAL")

    console.print("\n[bold cyan]📊 System Status[/bold cyan]\n")

    # Gateway status
    is_running, pid = check_gateway_process()
    port_listening = check_gateway_port()
    gateway_ready = is_running and port_listening

    gateway_table = Table(show_header=False, box=box.SIMPLE, padding=(0, 2))
    gateway_table.add_row(
        "Gateway Process",
        "✅ Running" if is_running else "❌ Not Running",
        f"PID: {pid}" if pid else "",
    )
    gateway_table.add_row(
        "Port 4002",
        "✅ Listening" if port_listening else "❌ Not Listening",
        "",
    )
    gateway_table.add_row(
        "Status",
        "✅ Ready" if gateway_ready else "❌ Not Ready",
        "",
    )

    console.print(
        Panel(
            gateway_table,
            title="🔌 IB Gateway",
            border_style="cyan" if gateway_ready else "red",
            box=box.ROUNDED,
        )
    )
    console.print()

    # Risk status
    try:
        profile = load_profile()
        perf_path = DEFAULT_PERF_PATH
        today = datetime.now(timezone.utc).strftime("%Y%m%d")

        df = load_performance(perf_path)
        today_df = (
            df[df["timestamp"].dt.strftime("%Y%m%d") == today]
            if "timestamp" in df.columns and not df.empty
            else df.iloc[0:0]
        )
        trades_today = len(today_df) if not today_df.empty else 0
        realized_pnl = (
            today_df["realized_pnl"].fillna(0).sum() if not today_df.empty else 0.0
        )

        risk_state = compute_risk_state(
            profile,
            day_start_equity=profile.starting_balance,
            realized_pnl=realized_pnl,
            unrealized_pnl=0.0,
            trades_today=trades_today,
            max_trades=profile.max_trades,
            now=datetime.now(timezone.utc),
        )

        risk_table = Table(show_header=False, box=box.SIMPLE, padding=(0, 2))
        risk_color = (
            "green"
            if risk_state.status == "OK"
            else "yellow"
            if risk_state.status == "NEAR_LIMIT"
            else "red"
        )
        risk_table.add_row(
            "Status", f"[{risk_color}]{risk_state.status}[/{risk_color}]", ""
        )
        risk_table.add_row(
            "Remaining Buffer", f"${risk_state.remaining_loss_buffer:,.2f}", ""
        )
        risk_table.add_row(
            "Daily Loss Limit", f"${risk_state.daily_loss_limit:,.2f}", ""
        )
        if risk_state.max_trades:
            remaining = max(0, risk_state.max_trades - trades_today)
            risk_table.add_row(
                "Trades Today",
                f"{trades_today}/{risk_state.max_trades}",
                f"({remaining} remaining)",
            )

        console.print(
            Panel(
                risk_table,
                title="⚠️  Risk State",
                border_style=risk_color,
                box=box.ROUNDED,
            )
        )
        console.print()

        # Performance summary
        total_pnl = df["realized_pnl"].fillna(0).sum() if not df.empty else 0.0
        pnl_color = "green" if total_pnl >= 0 else "red"

        perf_table = Table(show_header=False, box=box.SIMPLE, padding=(0, 2))
        perf_table.add_row(
            "Total P&L", f"[{pnl_color}]${total_pnl:,.2f}[/{pnl_color}]", ""
        )
        perf_table.add_row(
            "Today P&L", f"[{pnl_color}]${realized_pnl:,.2f}[/{pnl_color}]", ""
        )
        perf_table.add_row("Total Trades", f"{len(df)}", "")
        perf_table.add_row("Trades Today", f"{trades_today}", "")

        console.print(
            Panel(
                perf_table, title="📊 Performance", border_style="cyan", box=box.ROUNDED
            )
        )
        console.print()

    except Exception as e:
        console.print(f"[yellow]⚠️  Could not load risk/performance data: {e}[/yellow]")
        console.print()
