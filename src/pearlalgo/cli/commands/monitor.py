"""Live trading monitor - Real-time feed of trading activity and agentic decision-making."""

from __future__ import annotations

import click
import time
import subprocess
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
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


def parse_agentic_decision(line: str) -> dict[str, Any]:
    """Parse agentic decision-making from log line."""
    decision = {
        "type": "info",
        "symbol": None,
        "action": None,
        "reason": None,
        "details": {},
    }

    line_lower = line.lower()

    # Pattern matching for different decision types
    if "analyzing" in line_lower or "🔍" in line:
        decision["type"] = "analyzing"
        match = re.search(r"Analyzing\s+(\w+)", line, re.IGNORECASE)
        if match:
            decision["symbol"] = match.group(1)

    elif "generating" in line_lower or "🧠" in line:
        decision["type"] = "thinking"
        match = re.search(r"Generating\s+(\w+)\s+signal", line, re.IGNORECASE)
        if match:
            decision["action"] = f"Generating {match.group(1)} signal"

    elif "flat" in line_lower and "signal" in line_lower:
        decision["type"] = "decision"
        decision["action"] = "FLAT"
        match = re.search(r"(\w+):\s+FLAT", line, re.IGNORECASE)
        if match:
            decision["symbol"] = match.group(1)
        # Extract reason
        if "no trade opportunity" in line_lower:
            decision["reason"] = "No trade opportunity - strategy filters"
        elif "reason:" in line_lower:
            reason_match = re.search(r"reason:\s*(.+)", line_lower)
            if reason_match:
                decision["reason"] = reason_match.group(1).strip()

    elif "executing" in line_lower or "✅" in line:
        decision["type"] = "execution"
        decision["action"] = "EXECUTING"
        match = re.search(r"EXECUTING:\s+(\w+)\s+(\d+)\s+contract", line, re.IGNORECASE)
        if match:
            decision["symbol"] = match.group(1)
            decision["details"]["side"] = match.group(1)
            decision["details"]["size"] = match.group(2)

    elif "blocked" in line_lower or "🚫" in line:
        decision["type"] = "blocked"
        decision["action"] = "BLOCKED"
        match = re.search(r"(\w+):\s+TRADE\s+BLOCKED", line, re.IGNORECASE)
        if match:
            decision["symbol"] = match.group(1)
        if "risk state" in line_lower:
            decision["reason"] = "Risk limits prevent trading"

    elif "skip" in line_lower or "⏸️" in line:
        decision["type"] = "skip"
        decision["action"] = "SKIP"
        match = re.search(r"(\w+):\s+SKIP", line, re.IGNORECASE)
        if match:
            decision["symbol"] = match.group(1)
        if "cooldown" in line_lower:
            decision["reason"] = "Cooldown period active"
        elif "paused" in line_lower:
            decision["reason"] = "Trading paused"

    elif "risk-based exit" in line_lower or "🛑" in line:
        decision["type"] = "exit"
        decision["action"] = "RISK EXIT"
        decision["reason"] = "Risk-based exit triggered"

    elif "fetching" in line_lower or "📊" in line:
        decision["type"] = "data"
        decision["action"] = "Fetching data"

    elif "computing position size" in line_lower or "💰" in line:
        decision["type"] = "sizing"
        decision["action"] = "Computing position size"

    return decision


def create_agentic_thinking_panel(recent_decisions: list[dict]) -> Panel:
    """Create panel showing agentic thinking process."""
    table = Table(show_header=True, box=box.SIMPLE, header_style="bold cyan")
    table.add_column("Time", style="dim", width=10)
    table.add_column("Symbol", style="yellow", width=8)
    table.add_column("Action", width=20)
    table.add_column("Reasoning", width=35)

    if not recent_decisions:
        table.add_row("", "[dim]Waiting for activity...[/dim]", "", "")
    else:
        for decision in recent_decisions[-10:]:  # Show last 10
            time_str = (
                decision.get("time", "N/A")[:8] if decision.get("time") else "N/A"
            )
            symbol = decision.get("symbol", "")
            action = decision.get("action", "")
            reason = decision.get("reason", "")

            # Color code by type
            action_color = {
                "analyzing": "cyan",
                "thinking": "blue",
                "decision": "yellow",
                "execution": "green",
                "blocked": "red",
                "skip": "yellow",
                "exit": "red",
                "data": "dim",
                "sizing": "dim",
            }.get(decision.get("type", "info"), "white")

            table.add_row(
                time_str,
                symbol,
                f"[{action_color}]{action}[/]",
                reason[:35] if reason else "[dim]No reason provided[/dim]",
            )

    return Panel(table, title="🧠 Agentic Thinking Process", border_style="cyan")


def create_live_monitor() -> Layout:
    """Create live trading monitor layout."""
    # Futures modules removed - CLI will be updated for options
    # TODO: Create options-specific performance and risk tracking

    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="main"),
        Layout(name="footer", size=2),
    )

    layout["main"].split_row(
        Layout(name="left", ratio=1), Layout(name="right", ratio=1)
    )

    layout["left"].split_column(
        Layout(name="thinking", ratio=2), Layout(name="trades", ratio=1)
    )

    layout["right"].split_column(
        Layout(name="signals", ratio=1), Layout(name="performance", ratio=1)
    )

    # Header
    now = datetime.now(timezone.utc)
    header_text = Text(
        "📊 Live Trading Monitor - Agentic Decision Feed", style="bold cyan"
    )
    header_text.append(f" | {now.strftime('%Y-%m-%d %H:%M:%S UTC')}", style="dim")
    layout["header"].update(Panel(header_text, border_style="cyan", box=box.DOUBLE))

    # Latest Trades
    perf_path = DEFAULT_PERF_PATH
    trades_df = get_latest_trades(perf_path, limit=15)

    if not trades_df.empty:
        trades_table = Table(
            title="💰 Latest Trades",
            box=box.ROUNDED,
            show_header=True,
            header_style="bold cyan",
        )
        trades_table.add_column("Time", style="dim", width=12)
        trades_table.add_column("Symbol", style="yellow", width=6)
        trades_table.add_column("Side", justify="center", width=6)
        trades_table.add_column("Size", justify="right", width=6)
        trades_table.add_column("Price", justify="right", width=10)
        trades_table.add_column("P&L", justify="right", width=12)

        for _, row in trades_df.iterrows():
            timestamp = row.get("timestamp", pd.NaT)
            time_str = timestamp.strftime("%H:%M:%S") if pd.notna(timestamp) else "N/A"

            symbol = str(row.get("symbol", "N/A"))
            side = str(row.get("side", "N/A")).upper()
            size = row.get("filled_size", 0) or row.get("requested_size", 0)
            price = row.get("entry_price", 0.0) or row.get("exit_price", 0.0)
            pnl = row.get("realized_pnl", 0.0) or row.get("unrealized_pnl", 0.0)

            side_color = (
                "[bold green]"
                if side == "LONG"
                else "[bold red]"
                if side == "SHORT"
                else "[dim]"
            )
            pnl_color = "[green]" if pnl > 0 else "[red]" if pnl < 0 else "[dim]"

            trades_table.add_row(
                time_str,
                symbol,
                f"{side_color}{side}[/]",
                str(int(size)) if size else "0",
                f"${price:,.2f}" if price else "N/A",
                f"{pnl_color}${pnl:,.2f}[/]" if pnl else "$0.00",
            )

        layout["trades"].update(
            Panel(trades_table, border_style="cyan", box=box.ROUNDED)
        )
    else:
        layout["trades"].update(
            Panel(
                "[dim]No trades yet...[/dim]",
                title="💰 Latest Trades",
                border_style="yellow",
            )
        )

    # Latest Signals
    signals_dir = Path("signals")
    signals_df = get_latest_signals(signals_dir)

    if not signals_df.empty:
        signals_table = Table(
            title="📋 Latest Signals",
            box=box.SIMPLE,
            show_header=True,
            header_style="bold cyan",
        )
        signals_table.add_column("Time", style="dim", width=12)
        signals_table.add_column("Symbol", style="yellow", width=6)
        signals_table.add_column("Direction", justify="center", width=10)
        signals_table.add_column("Size", justify="right", width=6)

        for _, row in signals_df.tail(5).iterrows():
            timestamp = row.get("timestamp", "")
            time_str = (
                str(timestamp)[:19] if len(str(timestamp)) > 19 else str(timestamp)
            )

            symbol = str(row.get("symbol", "N/A"))
            direction = str(row.get("direction", "FLAT")).upper()
            size = row.get("size_hint", 0)

            dir_color = (
                "[bold green]"
                if direction == "BUY"
                else "[bold red]"
                if direction == "SELL"
                else "[dim]"
            )

            signals_table.add_row(
                time_str,
                symbol,
                f"{dir_color}{direction}[/]",
                str(int(size)) if size else "0",
            )

        layout["signals"].update(
            Panel(signals_table, border_style="cyan", box=box.ROUNDED)
        )
    else:
        layout["signals"].update(
            Panel(
                "[dim]No signals yet...[/dim]",
                title="📋 Latest Signals",
                border_style="yellow",
            )
        )

    # Performance Summary
    perf_df = load_performance(perf_path)
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    today_df = (
        perf_df[perf_df["timestamp"].dt.strftime("%Y%m%d") == today]
        if "timestamp" in perf_df.columns and not perf_df.empty
        else pd.DataFrame()
    )

    profile = load_profile()
    realized_pnl = (
        today_df["realized_pnl"].fillna(0).sum() if not today_df.empty else 0.0
    )
    unrealized_pnl = 0.0

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
    perf_table.add_row(
        "Risk Status:",
        f"[{'green' if risk_state.status == 'OK' else 'yellow' if 'NEAR' in risk_state.status else 'red'}]{risk_state.status}[/]",
    )
    perf_table.add_row("Buffer:", f"${risk_state.remaining_loss_buffer:,.2f}")

    layout["performance"].update(
        Panel(
            perf_table,
            title="📊 Performance Summary",
            border_style="cyan",
            box=box.ROUNDED,
        )
    )

    # Agentic thinking (will be updated from log tailing)
    layout["thinking"].update(create_agentic_thinking_panel([]))

    # Footer
    footer_text = Text(
        "Press Ctrl+C to exit | Auto-refresh: 2s", style="dim", justify="center"
    )
    layout["footer"].update(Panel(footer_text, border_style="dim"))

    return layout


@click.command(name="monitor")
@click.option(
    "--refresh",
    type=float,
    default=2.0,
    help="Refresh interval in seconds for dashboard view (default: 2)",
)
@click.option(
    "--live-feed",
    is_flag=True,
    default=False,
    help="Show live trading cycle feed with agentic thinking",
)
@click.option(
    "--log-file", type=click.Path(), help="Log file to tail (default: auto-detect)"
)
@click.pass_context
def monitor_cmd(
    ctx: click.Context, refresh: float, live_feed: bool, log_file: str | None
) -> None:
    """Live trading monitor with real-time activity feed and agentic decision-making.

    Two modes:
    1. Dashboard mode (default): Shows trades, signals, performance, and agentic thinking
    2. Live feed mode (--live-feed): Shows real-time trading cycle activity with decision reasoning
    """
    if live_feed:
        _show_live_feed(log_file)
    else:
        console.print(
            f"\n[bold cyan]📊 Starting Live Trading Monitor (refreshes every {refresh}s)[/bold cyan]"
        )
        console.print("[dim]Press Ctrl+C to exit[/dim]\n")

        # Track recent decisions for agentic thinking panel
        recent_decisions = []

        try:
            with Live(
                create_live_monitor(), refresh_per_second=1.0 / refresh, screen=True
            ) as live:
                # Also tail log file in background to update thinking panel
                log_path = _detect_log_file()
                if log_path and log_path.exists():
                    _update_thinking_from_log(log_path, recent_decisions, live, refresh)
                else:
                    while True:
                        time.sleep(refresh)
                        live.update(create_live_monitor())
        except KeyboardInterrupt:
            console.print("\n[bold yellow]Monitor closed[/bold yellow]\n")


def _detect_log_file() -> Path | None:
    """Auto-detect log file."""
    log_paths = [
        Path("logs/micro_console.log"),
        Path("logs/test_trading.log"),
        Path("logs/automated_trading.log"),
        Path("logs/standard_console.log"),
    ]
    for path in log_paths:
        if path.exists():
            return path
    return None


def _update_thinking_from_log(
    log_path: Path, recent_decisions: list, live: Live, refresh: float
) -> None:
    """Update thinking panel from log file."""
    try:
        # Read last 50 lines
        with open(log_path, "r") as f:
            lines = f.readlines()
            for line in lines[-50:]:
                decision = parse_agentic_decision(line.strip())
                if decision["type"] != "info":
                    decision["time"] = datetime.now(timezone.utc).strftime("%H:%M:%S")
                    recent_decisions.append(decision)
                    if len(recent_decisions) > 20:
                        recent_decisions.pop(0)

        # Update dashboard
        while True:
            time.sleep(refresh)
            # Re-read log for new lines
            with open(log_path, "r") as f:
                new_lines = f.readlines()
                if len(new_lines) > len(lines):
                    for line in new_lines[len(lines) :]:
                        decision = parse_agentic_decision(line.strip())
                        if decision["type"] != "info":
                            decision["time"] = datetime.now(timezone.utc).strftime(
                                "%H:%M:%S"
                            )
                            recent_decisions.append(decision)
                            if len(recent_decisions) > 20:
                                recent_decisions.pop(0)
                    lines = new_lines

            # Update layout with new decisions
            layout = create_live_monitor()

            thinking_panel = create_agentic_thinking_panel(recent_decisions)
            layout["thinking"].update(thinking_panel)
            live.update(layout)
    except Exception as e:
        console.print(f"[yellow]Could not update thinking panel: {e}[/yellow]")


def _show_live_feed(log_file: str | None = None) -> None:
    """Show live trading cycle feed from console logs with enhanced agentic thinking display."""
    console.print(
        "\n[bold cyan]📡 Live Trading Cycle Feed - Agentic Decision Making[/bold cyan]"
    )
    console.print(
        "[dim]Shows real-time trading activity, cycles, and decision reasoning[/dim]"
    )
    console.print("[dim]Press Ctrl+C to exit[/dim]\n")

    # Auto-detect log file
    if not log_file:
        log_path = _detect_log_file()
        if log_path:
            log_file = str(log_path)

    if not log_file or not Path(log_file).exists():
        console.print("[red]❌ No log file found![/red]")
        console.print("\n[dim]Make sure trading is running. Try:[/dim]")
        console.print("  [yellow]pearlalgo trade auto ES NQ GC --strategy sr[/yellow]")
        console.print("\n[dim]Or specify log file:[/dim]")
        console.print(
            "  [yellow]pearlalgo monitor --live-feed --log-file logs/your_log.log[/yellow]\n"
        )
        return

    # Check if trading process is running
    result = subprocess.run(
        ["pgrep", "-f", "pearlalgo trade auto"], capture_output=True
    )
    if result.returncode != 0:
        result = subprocess.run(
            ["pgrep", "-f", "automated_trading"], capture_output=True
        )

    if result.returncode == 0:
        console.print("[green]✅ Trading process is running[/green]")
    else:
        console.print(
            "[yellow]⚠️  No trading process detected (but log exists)[/yellow]"
        )

    console.print(f"[dim]📝 Watching: {log_file}[/dim]\n")

    # Show recent activity with enhanced parsing
    try:
        with open(log_file, "r") as f:
            lines = f.readlines()
            if lines:
                console.print("[dim]📋 Recent Agentic Decisions:[/dim]")
                console.print("[dim]" + "─" * 80 + "[/dim]")
                for line in lines[-30:]:
                    line_stripped = line.strip()
                    if not line_stripped:
                        continue

                    decision = parse_agentic_decision(line_stripped)

                    # Enhanced color coding with reasoning
                    if decision["type"] == "analyzing":
                        console.print(f"[cyan]🔍 {line_stripped}[/cyan]")
                    elif decision["type"] == "thinking":
                        console.print(f"[blue]🧠 {line_stripped}[/blue]")
                    elif decision["type"] == "decision":
                        if decision["action"] == "FLAT":
                            reason = decision.get("reason", "No trade opportunity")
                            console.print(f"[yellow]⚪ {line_stripped}[/yellow]")
                            if reason and reason != "No trade opportunity":
                                console.print(f"[dim]   💭 Reasoning: {reason}[/dim]")
                    elif decision["type"] == "execution":
                        console.print(f"[bold green]✅ {line_stripped}[/bold green]")
                    elif decision["type"] == "blocked":
                        console.print(f"[red]🚫 {line_stripped}[/red]")
                        if decision.get("reason"):
                            console.print(f"[dim]   ⚠️  {decision['reason']}[/dim]")
                    elif decision["type"] == "skip":
                        console.print(f"[yellow]⏸️  {line_stripped}[/yellow]")
                        if decision.get("reason"):
                            console.print(f"[dim]   ⏸️  {decision['reason']}[/dim]")
                    elif decision["type"] == "exit":
                        console.print(f"[bold red]🛑 {line_stripped}[/bold red]")
                    elif decision["type"] == "data":
                        console.print(f"[dim]📊 {line_stripped}[/dim]")
                    elif decision["type"] == "sizing":
                        console.print(f"[dim]💰 {line_stripped}[/dim]")
                    else:
                        # Check for common patterns
                        if any(
                            x in line_stripped for x in ["EXECUTING", "✅ EXECUTING"]
                        ):
                            console.print(f"[bold green]{line_stripped}[/bold green]")
                        elif any(x in line_stripped for x in ["FLAT", "⚪"]):
                            console.print(f"[yellow]{line_stripped}[/yellow]")
                        elif any(x in line_stripped for x in ["LONG", "SHORT"]):
                            console.print(f"[bold]{line_stripped}[/bold]")
                        elif any(x in line_stripped for x in ["SKIP", "BLOCKED", "🚫"]):
                            console.print(f"[red]{line_stripped}[/red]")
                        else:
                            console.print(f"[dim]{line_stripped}[/dim]")
                console.print("[dim]" + "─" * 80 + "[/dim]\n")
    except Exception as e:
        console.print(f"[yellow]⚠️  Could not read recent activity: {e}[/yellow]\n")

    console.print("[bold]👀 Live Agentic Feed (Ctrl+C to stop):[/bold]\n")
    console.print(
        "[dim]💡 The agent shows its thinking process: analyzing → generating signal → decision → execution[/dim]\n"
    )

    # Tail the log file with enhanced parsing
    process = None
    try:
        process = subprocess.Popen(
            ["tail", "-f", log_file],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

        for line in iter(process.stdout.readline, ""):
            if not line:
                break

            line_stripped = line.strip()
            if not line_stripped:
                continue

            decision = parse_agentic_decision(line_stripped)

            # Enhanced display with reasoning
            if decision["type"] == "analyzing":
                console.print(
                    f"[cyan]🔍 Analyzing {decision.get('symbol', '')}...[/cyan]"
                )
            elif decision["type"] == "thinking":
                console.print(f"[blue]🧠 {line_stripped}[/blue]")
            elif decision["type"] == "decision":
                if decision["action"] == "FLAT":
                    symbol = decision.get("symbol", "")
                    reason = decision.get("reason", "No trade opportunity")
                    console.print(
                        f"[yellow]⚪ {symbol}: FLAT signal - {reason}[/yellow]"
                    )
                    # Show why it's FLAT
                    if "no trade opportunity" in reason.lower():
                        console.print(
                            "[dim]   💭 Strategy filters: No clear entry setup (price not near S/R, EMA filter, etc.)[/dim]"
                        )
            elif decision["type"] == "execution":
                symbol = decision.get("symbol", "")
                details = decision.get("details", {})
                console.print(
                    f"[bold green]✅ EXECUTING: {symbol} {details.get('side', '')} {details.get('size', '')} contracts[/bold green]"
                )
            elif decision["type"] == "blocked":
                symbol = decision.get("symbol", "")
                reason = decision.get("reason", "Risk limits")
                console.print(f"[red]🚫 {symbol}: TRADE BLOCKED - {reason}[/red]")
            elif decision["type"] == "skip":
                symbol = decision.get("symbol", "")
                reason = decision.get("reason", "Cooldown")
                console.print(f"[yellow]⏸️  {symbol}: SKIP - {reason}[/yellow]")
            elif decision["type"] == "exit":
                console.print(f"[bold red]🛑 {line_stripped}[/bold red]")
            elif decision["type"] == "data":
                console.print(f"[dim]📊 {line_stripped}[/dim]")
            elif decision["type"] == "sizing":
                console.print(f"[dim]💰 {line_stripped}[/dim]")
            else:
                # Fallback to pattern matching
                if any(x in line_stripped for x in ["Analyzing", "🔍"]):
                    console.print(f"[cyan]{line_stripped}[/cyan]")
                elif any(x in line_stripped for x in ["EXECUTING", "✅ EXECUTING"]):
                    console.print(f"[bold green]{line_stripped}[/bold green]")
                elif any(x in line_stripped for x in ["FLAT", "⚪"]):
                    console.print(f"[yellow]{line_stripped}[/yellow]")
                elif any(x in line_stripped for x in ["LONG", "SHORT"]):
                    console.print(f"[bold]{line_stripped}[/bold]")
                elif any(
                    x in line_stripped for x in ["SKIP", "BLOCKED", "🚫", "Risk-based"]
                ):
                    console.print(f"[red]{line_stripped}[/red]")
                elif any(
                    x in line_stripped for x in ["Fetching", "📊", "Generating", "🧠"]
                ):
                    console.print(f"[dim]{line_stripped}[/dim]")
                elif "Cycle" in line_stripped or "P&L" in line_stripped:
                    console.print(f"[bold cyan]{line_stripped}[/bold cyan]")
                else:
                    console.print(line_stripped)

    except KeyboardInterrupt:
        console.print("\n[bold yellow]Live feed closed[/bold yellow]\n")
        if process:
            process.terminate()
    except Exception as e:
        console.print(f"\n[red]Error: {e}[/red]\n")
